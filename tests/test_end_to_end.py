"""Comprehensive Phase 8 End-to-End Integration and Offline Readiness Tests."""
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.database.models import (
    NormalizedTradeRecord,
    OfacSanctionRecord,
    RiskAnalysis,
    RiskRuleResult,
    EvidenceSnapshot,
    GeneratedReport,
    AuditEvent,
)
from app.ingestion.service import IngestionService
from app.risk.service import RiskEngineService
from app.classification.service import ClassificationService
from app.ranking.service import RankingService
from app.evidence.service import EvidenceService, EvidenceValidationService
from app.rag.service import RAGService
from app.schemas.ai import ExplainRequest
from app.reports.service import PDFReportService
from app.schemas.reports import GeneratePDFReportRequest
from app.api.routes.health import get_readiness


def test_complete_phase1_through_phase7_lifecycle(test_db, fixtures_dir, tmp_path):
    """
    Executes and validates the complete 12-step end-to-end MineTrace supply-chain risk workflow:
    1. Ingest trade records from Comtrade fixture.
    2. Verify normalized storage in SQLite.
    3. Run deterministic risk analysis (R1-R5).
    4. Verify individual rule outcomes, weights, and anomaly score.
    5. Classify the analysis (GREEN/AMBER/RED/INSUFFICIENT_DATA).
    6. Retrieve record in risk rankings (verifying score order).
    7. Generate immutable Phase 5 evidence snapshot.
    8. Validate evidence snapshot (9-point audit verification).
    9. Generate evidence-grounded AI explanation (local RAG).
    10. Generate printable PDF evidence report.
    11. Download report and verify valid, readable PDF file.
    12. Verify historical immutability across the entire lifecycle.
    """
    # ---------------- 1. Ingest Trade Records ----------------
    trade_fixture = fixtures_dir / "comtrade_sample.json"
    ofac_fixture = fixtures_dir / "ofac_sample.csv"

    ingest_svc = IngestionService(test_db)
    trade_run = ingest_svc.ingest_trade_data(fixture_path=str(trade_fixture))
    assert trade_run["clean_records_count"] > 0

    ofac_run = ingest_svc.ingest_sanctions_data(fixture_path=str(ofac_fixture))
    assert ofac_run["clean_records_count"] > 0

    # ---------------- 2. Verify Storage in SQLite ----------------
    trade_records = test_db.query(NormalizedTradeRecord).all()
    assert len(trade_records) >= 4
    sample_trade = trade_records[0]
    assert sample_trade.commodity_code is not None
    assert sample_trade.trade_value_usd > 0

    # ---------------- 3. Run Deterministic Risk Analysis ----------------
    risk_svc = RiskEngineService(test_db)
    analysis = risk_svc.analyze_record(sample_trade)

    assert analysis.analysis_id is not None
    assert analysis.trade_record_id == sample_trade.id
    assert 0.0 <= analysis.combined_anomaly_score <= 100.0

    # ---------------- 4. Verify Individual Rule Outcomes ----------------
    rule_results = (
        test_db.query(RiskRuleResult)
        .filter(RiskRuleResult.analysis_id == analysis.analysis_id)
        .all()
    )
    rule_map = {r.rule_id: r for r in rule_results}
    assert "R1" in rule_map
    assert "R2" in rule_map
    assert "R3" in rule_map
    assert "R4" in rule_map
    assert "R5" in rule_map

    # Check weights sum up to 100 for R1-R4
    assert rule_map["R1"].weight == 30
    assert rule_map["R2"].weight == 20
    assert rule_map["R3"].weight == 30
    assert rule_map["R4"].weight == 20

    # ---------------- 5. Classify the Analysis ----------------
    class_svc = ClassificationService(test_db)
    db_analysis, class_result = class_svc.classify_analysis(analysis)

    assert class_result.classification in ["GREEN", "AMBER", "RED", "INSUFFICIENT_DATA"]
    if analysis.score_completeness in ["PARTIAL", "UNAVAILABLE"]:
        assert class_result.classification == "INSUFFICIENT_DATA"
    elif analysis.combined_anomaly_score >= 50.0:
        assert class_result.classification == "RED"
    elif analysis.combined_anomaly_score >= 20.0:
        assert class_result.classification == "AMBER"
    else:
        assert class_result.classification == "GREEN"

    # ---------------- 6. Retrieve in Risk Rankings ----------------
    ranking_svc = RankingService(test_db)
    rankings = ranking_svc.get_primary_ranking(page=1, page_size=20)

    if analysis.score_completeness == "COMPLETE":
        matching = [r for r in rankings.rankings if r.analysis_id == analysis.analysis_id]
        assert len(matching) == 1
        assert matching[0].anomaly_score == analysis.combined_anomaly_score
    else:
        # Partial/unavailable records are isolated in incomplete endpoint
        incompletes = ranking_svc.get_incomplete_records(page=1, page_size=20)
        matching_inc = [r for r in incompletes.records if r.analysis_id == analysis.analysis_id]
        assert len(matching_inc) == 1

    # ---------------- 7. Freeze Evidence Snapshot ----------------
    evidence_svc = EvidenceService(test_db)
    snapshot = evidence_svc.create_or_get_snapshot(analysis)

    assert snapshot.evidence_id is not None
    assert snapshot.analysis_id == analysis.analysis_id
    assert snapshot.combined_anomaly_score == analysis.combined_anomaly_score
    assert snapshot.classification == class_result.classification

    # ---------------- 8. Validate Evidence ----------------
    val_svc = EvidenceValidationService(test_db)
    val_report = val_svc.validate_analysis_evidence(analysis.analysis_id)

    assert val_report.analysis_id == analysis.analysis_id
    assert val_report.validation_status in ["VALID", "WARNINGS"]
    assert len(val_report.checks_performed) + len(val_report.unavailable_checks) >= 9

    # ---------------- 9. Local RAG AI Explanation ----------------
    rag_svc = RAGService(test_db)
    explain_req = ExplainRequest(
        analysis_id=analysis.analysis_id,
        question=f"Explain risk factors and rule evaluations for transaction {analysis.analysis_id}.",
        use_template_only=True,  # Deterministic grounding
    )
    explanation = rag_svc.explain(explain_req)

    assert explanation.analysis_id == analysis.analysis_id
    assert explanation.answer is not None
    assert len(explanation.answer) > 50
    assert explanation.validation_status in ["VALID", "WARNINGS"]

    # ---------------- 10. Generate PDF Evidence Report ----------------
    report_svc = PDFReportService(test_db, reports_dir=tmp_path)
    pdf_req = GeneratePDFReportRequest(
        analysis_id=analysis.analysis_id,
        include_ai_explanation=True,
        notes="End-to-end integration verification report.",
    )
    report_summary = report_svc.generate_report(pdf_req)

    assert report_summary.report_id.startswith("REP-")
    assert report_summary.analysis_id == analysis.analysis_id
    assert report_summary.has_evidence_snapshot is True
    assert report_summary.file_size_bytes > 0

    # ---------------- 11. Download and Verify PDF File ----------------
    file_path, filename = report_svc.get_report_file_path(report_summary.report_id)
    assert file_path.exists()
    assert filename == f"{report_summary.report_id}.pdf"

    pdf_bytes = file_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert pdf_bytes.strip().endswith(b"%%EOF")

    text_content = pdf_bytes.decode("latin1")
    assert report_summary.report_id in text_content
    assert analysis.analysis_id in text_content
    assert "Critical Mineral Supply-Chain Risk Assessment" in text_content
    assert "NOTICE & DISCLAIMER" in text_content
    assert "METHODOLOGY & LIMITATIONS" in text_content

    # ---------------- 12. Confirm Historical Immutability ----------------
    db_analysis = test_db.query(RiskAnalysis).filter(RiskAnalysis.analysis_id == analysis.analysis_id).first()
    assert db_analysis.combined_anomaly_score == analysis.combined_anomaly_score
    assert db_analysis.classification == class_result.classification
    assert db_analysis.flag_status == class_result.flag_status


def test_edge_case_zero_baseline_volume_spike(test_db):
    """
    R2 Volume Spike requires a historical baseline.
    When baseline volume is zero or missing, R2 must return NOT_EVALUATED or INSUFFICIENT_DATA,
    score completeness must be PARTIAL, and classification must be INSUFFICIENT_DATA (never GREEN).
    """
    trade = NormalizedTradeRecord(
        commodity_code="283691",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        reporter_country_name="Chile",
        partner_country_code="USA",
        partner_country_name="United States",
        period="2023",
        period_year=2023,
        flow_type="EXPORT",
        trade_value_usd=500000.0,
        net_weight_kg=25000.0,
        record_hash="hash-single-record-nobaseline",
        retrieval_timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    risk_svc = RiskEngineService(test_db)
    analysis = risk_svc.analyze_record(trade)

    # Incompleteness checks
    assert analysis.score_completeness in ["PARTIAL", "UNAVAILABLE"]

    class_svc = ClassificationService(test_db)
    _, class_res = class_svc.classify_analysis(analysis)

    # Under strict sufficiency policy, partial data MUST receive INSUFFICIENT_DATA
    assert class_res.classification == "INSUFFICIENT_DATA"


def test_edge_case_duplicate_trade_ingestion_prevention(test_db, fixtures_dir):
    """Ingesting the same trade records repeatedly must not duplicate records."""
    ingest_svc = IngestionService(test_db)
    fixture_path = str(fixtures_dir / "comtrade_sample.json")

    run1 = ingest_svc.ingest_trade_data(fixture_path=fixture_path)
    count1 = test_db.query(NormalizedTradeRecord).count()

    # Ingest again
    run2 = ingest_svc.ingest_trade_data(fixture_path=fixture_path)
    count2 = test_db.query(NormalizedTradeRecord).count()

    assert count1 == count2
    assert run2["clean_records_count"] == 0  # All duplicates safely skipped


def test_edge_case_missing_evidence_pdf_report_graceful_warning(test_db, tmp_path):
    """
    When generating a PDF report for an analysis that lacks a Phase 5 evidence snapshot,
    the system must not crash; it produces a valid PDF containing prominent data sufficiency warnings.
    """
    analysis = RiskAnalysis(
        analysis_id="ORPHAN-ANALYSIS-1",
        commodity_code="283691",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        partner_country_code="USA",
        period="2023",
        combined_anomaly_score=35.0,
        score_completeness="COMPLETE",
        evaluated_rules=json.dumps(["R1"]),
        insufficient_rules=json.dumps([]),
        flagged_rules=json.dumps([]),
        classification="AMBER",
        flag_status="NOT_FLAGGED",
        created_at=datetime.now(timezone.utc),
    )
    test_db.add(analysis)
    test_db.commit()

    report_svc = PDFReportService(test_db, reports_dir=tmp_path)
    req = GeneratePDFReportRequest(
        analysis_id="ORPHAN-ANALYSIS-1",
        include_ai_explanation=False,
    )
    summary = report_svc.generate_report(req)

    assert summary.has_evidence_snapshot is False
    assert summary.report_status == "COMPLETED"

    file_path, _ = report_svc.get_report_file_path(summary.report_id)
    pdf_bytes = file_path.read_bytes()
    text = pdf_bytes.decode("latin1")

    assert "DATA COMPLETENESS WARNING" in text
    assert "No frozen Phase 5 evidence snapshot" in text


def test_edge_case_security_path_traversal_defense(test_db, tmp_path):
    """Path traversal attempts on PDF report downloads must be blocked with HTTP 400 or 403."""
    report_svc = PDFReportService(test_db, reports_dir=tmp_path)

    with pytest.raises(Exception) as exc_info:
        report_svc.get_report_file_path("../../windows/win.ini")
    assert "400" in str(exc_info.value) or "Invalid report ID" in str(exc_info.value)


def test_system_readiness_comprehensive_status(test_db):
    """Verifies that the /health/readiness endpoint reports statuses across all 10 subsystems."""
    readiness = get_readiness(db=test_db)

    assert readiness.status == "READY"
    assert readiness.offline_mode is True
    assert len(readiness.components) == 10

    expected_components = [
        "application",
        "database",
        "data_availability",
        "risk_engine",
        "classification_engine",
        "ranking_engine",
        "evidence_system",
        "vector_store",
        "ollama_inference",
        "pdf_reporting",
    ]
    for comp in expected_components:
        assert comp in readiness.components
        assert readiness.components[comp].status in ["READY", "DEGRADED", "OFFLINE", "EMPTY"]
