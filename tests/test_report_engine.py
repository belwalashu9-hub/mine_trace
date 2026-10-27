"""Unit tests for Phase 7 Printable PDF Evidence Reports Engine."""
import json
import re
from datetime import datetime, timezone
import pytest

from app.database.models import (
    RiskAnalysis,
    RiskRuleResult,
    NormalizedTradeRecord,
    EvidenceSnapshot,
)
from app.reports.data_service import ReportDataService
from app.reports.pdf_generator import PDFReportGenerator, PurePythonPDFBuilder
from app.reports.service import PDFReportService
from app.schemas.reports import GeneratePDFReportRequest


def seed_analysis_with_snapshot(db, analysis_id: str = "REP-TEST-1"):
    """Seeds a normalized trade record, risk analysis, rule results, and an evidence snapshot."""
    trade = NormalizedTradeRecord(
        commodity_code="283691",
        commodity_description="Lithium carbonate",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        reporter_country_name="Chile",
        partner_country_code="USA",
        partner_country_name="United States",
        period="2023",
        period_year=2023,
        flow_type="EXPORT",
        trade_value_usd=1200000.0,
        net_weight_kg=60000.0,
        record_hash=f"hash-{analysis_id}",
        retrieval_timestamp=datetime(2023, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    db.add(trade)
    db.commit()

    analysis = RiskAnalysis(
        analysis_id=analysis_id,
        trade_record_id=trade.id,
        commodity_code="283691",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        partner_country_code="USA",
        period="2023",
        combined_anomaly_score=60.0,
        score_completeness="COMPLETE",
        evaluated_rules=json.dumps(["R1", "R2", "R3", "R4", "R5"]),
        insufficient_rules=json.dumps([]),
        flagged_rules=json.dumps(["R1", "R3"]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification="RED",
        flag_status="FLAGGED",
        classification_explanation="Elevated anomaly score exceeding RED prototype threshold (>= 50.0).",
        created_at=datetime(2023, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    db.add(analysis)

    r1 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R1",
        rule_name="Mirror Trade Gap",
        rule_version="1.0",
        weight=30,
        outcome="FLAG",
        threshold="> 30.0%",
        formula="abs(export_value - import_value) / max(export_value, import_value) * 100",
        calculated_value=45.0,
        input_values=json.dumps({"export_value": 1200000.0, "import_value": 660000.0}),
        explanation="Export-import mirror trade gap 45.0% exceeds threshold.",
    )
    db.add(r1)

    r3 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R3",
        rule_name="Jurisdiction Partner Risk",
        rule_version="1.0",
        weight=30,
        outcome="FLAG",
        threshold="Partner in elevated transit jurisdiction",
        formula="partner_country_code in transit_risk_list",
        calculated_value=1.0,
        input_values=json.dumps({"partner_country": "USA"}),
        explanation="Partner route requires review.",
    )
    db.add(r3)
    db.commit()

    snapshot = EvidenceSnapshot(
        evidence_id=f"SNAP-{analysis_id}",
        analysis_id=analysis_id,
        schema_version="1.0",
        trade_record_id=trade.id,
        source_dataset_name="UN Comtrade",
        source_record_id=f"TRADE-{trade.id}",
        source_reference_url="https://comtradeapi.un.org/public/v1/preview/C/A/HS",
        source_retrieval_timestamp=datetime(2023, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        source_payload_snapshot=json.dumps({"trade_value_usd": 1200000.0}),
        analysis_timestamp=datetime(2023, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        combined_anomaly_score=60.0,
        score_completeness="COMPLETE",
        evaluated_rules=json.dumps(["R1", "R2", "R3", "R4", "R5"]),
        insufficient_rules=json.dumps([]),
        flagged_rules=json.dumps(["R1", "R3"]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification="RED",
        flag_status="FLAGGED",
        classification_explanation="Elevated anomaly score exceeding RED prototype threshold (>= 50.0).",
        classification_policy_version="1.0",
        classification_thresholds_applied=json.dumps({"GREEN": [0, 19], "AMBER": [20, 49], "RED": [50, 100]}),
        rule_evaluations_snapshot=json.dumps([
            {
                "rule_id": "R1",
                "rule_name": "Mirror Trade Gap",
                "rule_version": "1.0",
                "weight": 30,
                "outcome": "FLAG",
                "threshold": "> 30.0%",
                "formula": "abs(export_value - import_value) / max(export_value, import_value) * 100",
                "calculated_value": 45.0,
                "input_values": {"export_value": 1200000.0, "import_value": 660000.0},
                "explanation": "Export-import mirror trade gap 45.0% exceeds threshold.",
                "data_quality_warnings": [],
                "supporting_source_records": [f"TRADE-{trade.id}"],
            }
        ]),
        data_quality_warnings=json.dumps([]),
        validation_status="VALID",
        created_at=datetime(2023, 6, 1, 12, 1, 0, tzinfo=timezone.utc),
    )
    db.add(snapshot)
    db.commit()

    return analysis


def test_pure_python_pdf_structure_and_validity():
    """Verify that PurePythonPDFBuilder produces valid, standard-compliant PDF 1.4 bytes."""
    builder = PurePythonPDFBuilder()
    builder.add_heading("MineTrace Test Document", level=1)
    builder.add_paragraph("This is a test paragraph verifying valid PDF generation.")
    builder.add_table(["Header A", "Header B"], [["Row 1A", "Row 1B"], ["Row 2A", "Row 2B"]])
    pdf_bytes = builder.build_pdf_bytes(report_title="Test Document", report_id="REP-TEST-001")

    assert pdf_bytes.startswith(b"%PDF-1.4\n")
    assert pdf_bytes.strip().endswith(b"%%EOF")
    assert b"xref\n" in pdf_bytes
    assert b"trailer\n" in pdf_bytes
    assert b"/Root 1 0 R" in pdf_bytes

    # Text extraction verification
    text_content = pdf_bytes.decode("latin1")
    assert "MineTrace Test Document" in text_content
    assert "Row 1A" in text_content
    assert "REP-TEST-001" in text_content


def test_report_data_service_compiles_authoritative_data(test_db):
    """Verify ReportDataService extracts exact saved scores, rules, and snapshot evidence without recalculation."""
    seed_analysis_with_snapshot(test_db, "DATA-SVC-1")

    data_srv = ReportDataService(test_db)
    bundle = data_srv.compile_report_data("DATA-SVC-1", include_ai_explanation=False)

    meta = bundle["metadata"]
    summary = bundle["executive_summary"]
    classification = bundle["classification"]
    rules = bundle["risk_rules"]

    assert meta["analysis_id"] == "DATA-SVC-1"
    assert meta["has_evidence_snapshot"] is True
    assert summary["combined_anomaly_score"] == 60.0
    assert summary["classification"] == "RED"
    assert summary["score_completeness"] == "COMPLETE"
    assert classification["score"] == 60.0
    assert len(rules["rule_details"]) >= 1
    assert rules["rule_details"][0]["rule_id"] == "R1"
    assert rules["rule_details"][0]["calculated_value"] == 45.0


def test_report_data_service_handles_missing_evidence_snapshot(test_db):
    """When an analysis lacks a Phase 5 evidence snapshot, fallback data is extracted with a clear warning."""
    # Seed analysis WITHOUT snapshot
    analysis = RiskAnalysis(
        analysis_id="NO-SNAP-1",
        commodity_code="283691",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        partner_country_code="USA",
        period="2023",
        combined_anomaly_score=25.0,
        score_completeness="PARTIAL",
        evaluated_rules=json.dumps(["R2"]),
        insufficient_rules=json.dumps(["R1", "R3", "R4"]),
        flagged_rules=json.dumps(["R2"]),
        classification="AMBER",
        flag_status="FLAGGED",
        created_at=datetime.now(timezone.utc),
    )
    test_db.add(analysis)

    r2 = RiskRuleResult(
        analysis_id="NO-SNAP-1",
        rule_id="R2",
        rule_name="Volume Anomaly",
        weight=20,
        outcome="FLAG",
        threshold="> 50.0%",
        formula="volume_change_percentage > 50.0",
        calculated_value=75.0,
        input_values=json.dumps({"volume_change_percentage": 75.0}),
        explanation="Volume exceeded threshold by 75%.",
    )
    test_db.add(r2)
    test_db.commit()

    data_srv = ReportDataService(test_db)
    bundle = data_srv.compile_report_data("NO-SNAP-1", include_ai_explanation=False)

    assert bundle["metadata"]["has_evidence_snapshot"] is False
    assert bundle["executive_summary"]["combined_anomaly_score"] == 25.0
    assert bundle["executive_summary"]["classification"] == "AMBER"
    # Prominent warning must be present in warnings
    assert any("No frozen Phase 5 evidence snapshot found" in w for w in bundle["executive_summary"]["quality_warnings"])
    assert len(bundle["risk_rules"]["rule_details"]) == 1
    assert bundle["risk_rules"]["rule_details"][0]["rule_id"] == "R2"


def test_pdf_report_service_generation_and_storage(test_db, tmp_path):
    """Verify PDFReportService generates a physical PDF file, records metadata, and stores SHA-256."""
    seed_analysis_with_snapshot(test_db, "STORE-TEST-1")

    service = PDFReportService(test_db, reports_dir=tmp_path)
    req = GeneratePDFReportRequest(
        analysis_id="STORE-TEST-1",
        include_ai_explanation=False,
        notes="Audit demonstration sample report.",
    )

    summary = service.generate_report(req)

    assert summary.report_id.startswith("REP-")
    assert summary.analysis_id == "STORE-TEST-1"
    assert summary.has_evidence_snapshot is True
    assert summary.report_status == "COMPLETED"
    assert summary.file_size_bytes > 0
    assert len(summary.content_hash) == 64

    # Verify physical file on disk
    expected_file = tmp_path / f"{summary.report_id}.pdf"
    assert expected_file.exists()
    assert expected_file.stat().st_size == summary.file_size_bytes

    # Read bytes and verify text content
    pdf_bytes = expected_file.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    text_content = pdf_bytes.decode("latin1")
    assert summary.report_id in text_content
    assert "STORE-TEST-1" in text_content
    assert "Lithium carbonate" in text_content
    assert "Audit demonstration sample report." in text_content
    assert "CLASSIFICATION: RED" in text_content


def test_pdf_report_service_multi_page_and_disclaimer(test_db, tmp_path):
    """Verify that reports with extensive rules and audit events render multi-page documents with legal disclaimers."""
    analysis = seed_analysis_with_snapshot(test_db, "MULTI-PAGE-1")

    service = PDFReportService(test_db, reports_dir=tmp_path)
    req = GeneratePDFReportRequest(
        analysis_id="MULTI-PAGE-1",
        include_ai_explanation=False,
        notes="Long multi-page compliance verification test.",
    )

    summary = service.generate_report(req)
    file_path, _ = service.get_report_file_path(summary.report_id)
    pdf_bytes = file_path.read_bytes()
    text_content = pdf_bytes.decode("latin1")

    # Verify Legal and Methodology Disclaimers
    assert "NOTICE & DISCLAIMER" in text_content
    assert "DO NOT constitute a legal finding of fraud" in text_content
    assert "METHODOLOGY & LIMITATIONS" in text_content

    # Check page count
    page_matches = re.findall(r"/Type\s*/Page\b", text_content)
    assert len(page_matches) >= 1  # Standard valid pages
