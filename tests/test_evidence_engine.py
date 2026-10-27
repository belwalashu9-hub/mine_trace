"""Unit tests for Phase 5 Evidence Generation and Validation Engine."""
from datetime import datetime, timezone, timedelta
import json
import pytest

from app.database.models import (
    RiskAnalysis,
    RiskRuleResult,
    NormalizedTradeRecord,
    RankingSnapshot,
    RankingSnapshotItem,
    EvidenceSnapshot,
)
from app.evidence.service import EvidenceService, EvidenceValidationService
from app.audit.service import AuditEventService
from app.evidence.rules import (
    EVIDENCE_SCHEMA_VERSION,
    STATUS_VALID,
    STATUS_INVALID,
    STATUS_WARNINGS,
    EVENT_EVIDENCE_SNAPSHOT_GENERATED,
    EVENT_EVIDENCE_VALIDATION_PASSED,
    EVENT_EVIDENCE_VALIDATION_FAILED,
    CHECK_ANALYSIS_EXISTS,
    CHECK_CALCULATIONS_MATCH,
    CHECK_SCORE_WEIGHTS_MATCH,
    CHECK_COMPLETENESS_CONSISTENT,
    CHECK_CLASSIFICATION_CONSISTENT,
)


def seed_trade_and_analysis(
    db,
    analysis_id: str = "ANALYSIS-001",
    score: float = 50.0,
    completeness: str = "COMPLETE",
    classification: str = "RED",
    flag_status: str = "FLAGGED",
):
    """Helper to seed a NormalizedTradeRecord, RiskAnalysis, and 5 RiskRuleResults."""
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
        trade_value_usd=1000000.0,
        net_weight_kg=50000.0,
        record_hash=f"hash-{analysis_id}",
        retrieval_timestamp=datetime.now(timezone.utc),
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)

    analysis = RiskAnalysis(
        analysis_id=analysis_id,
        trade_record_id=trade.id,
        commodity_code="283691",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        partner_country_code="USA",
        period="2023",
        combined_anomaly_score=score,
        score_completeness=completeness,
        evaluated_rules=json.dumps(["R1", "R2", "R3", "R4", "R5"]),
        insufficient_rules=json.dumps([]),
        flagged_rules=json.dumps(["R1", "R2"]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification=classification,
        flag_status=flag_status,
        classification_explanation="Test explanation",
        created_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()

    # Rule R1: Mirror Trade Gap (Flagged, weight 30)
    # Gap = abs(100000 - 60000) / 100000 * 100 = 40.0%
    r1 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R1",
        rule_name="Mirror Trade Gap",
        rule_version="1.0",
        weight=30,
        outcome="FLAG",
        threshold="greater than 30%",
        formula="abs(export_value - import_value) / max(export_value, import_value) * 100",
        calculated_value=40.0,
        input_values=json.dumps({"export_value": 100000.0, "import_value": 60000.0}),
        explanation="Export-import mirror gap 40.0% exceeds 30% threshold.",
    )
    db.add(r1)

    # Rule R2: Volume Spike (Flagged, weight 20)
    # Spike = (300 - 90) / 90 * 100 = 233.3333%
    r2 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R2",
        rule_name="Volume Spike",
        rule_version="1.0",
        weight=20,
        outcome="FLAG",
        threshold="greater than 200%",
        formula="(current_volume - previous_volume) / previous_volume * 100",
        calculated_value=233.3333,
        input_values=json.dumps({"current_volume": 300.0, "previous_volume": 90.0}),
        explanation="Volume increased 233.3% exceeding 200% threshold.",
    )
    db.add(r2)

    # Rule R3: Route Concentration (Not Flagged, weight 30)
    r3 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R3",
        rule_name="Route Concentration",
        rule_version="1.0",
        weight=30,
        outcome="NOT_FLAGGED",
        threshold="greater than 80%",
        formula="partner_import_volume / total_import_volume * 100",
        calculated_value=50.0,
        input_values=json.dumps({"partner_import_volume": 500.0, "total_import_volume": 1000.0}),
        explanation="Route concentration 50.0% is below 80% threshold.",
    )
    db.add(r3)

    # Rule R4: Unusual Unit Price (Not Flagged, weight 20)
    r4 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R4",
        rule_name="Unusual Unit Price",
        rule_version="1.0",
        weight=20,
        outcome="NOT_FLAGGED",
        threshold="unit price deviates by more than 60% from median",
        formula="abs(unit_price - median_price) / median_price * 100",
        calculated_value=15.0,
        input_values=json.dumps({"unit_price": 20.0, "median_price": 23.0}),
        explanation="Unit price deviation 15.0% is below 60% threshold.",
    )
    db.add(r4)

    # Rule R5: Sanctions Exposure (Screening, weight 0)
    r5 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R5",
        rule_name="Sanctions Screening",
        rule_version="1.0",
        weight=0,
        outcome="NO_IDENTIFIED_MATCH",
        threshold="exact or normalized match on OFAC SDN list",
        formula="exact_match or token_similarity > 0.85",
        calculated_value=0.0,
        input_values=json.dumps({"entity_name": None}),
        explanation="No identified matches on OFAC list.",
    )
    db.add(r5)

    db.commit()
    return trade, analysis


def test_evidence_snapshot_creation_and_fields(test_db):
    """Snapshot freezes analysis state, source payload, and rule-by-rule evaluations."""
    trade, analysis = seed_trade_and_analysis(test_db, "SNAP-001", score=50.0, classification="RED")

    service = EvidenceService(test_db)
    snap = service.create_or_get_snapshot(analysis)

    assert snap is not None
    assert snap.evidence_id is not None
    assert snap.analysis_id == "SNAP-001"
    assert snap.schema_version == EVIDENCE_SCHEMA_VERSION
    assert snap.combined_anomaly_score == 50.0
    assert snap.score_completeness == "COMPLETE"
    assert snap.classification == "RED"
    assert snap.source_record_id is not None

    # Verify source payload snapshot was preserved
    payload = json.loads(snap.source_payload_snapshot)
    assert payload["trade_value_usd"] == 1000000.0
    assert payload["commodity_code"] == "283691"

    # Verify rule evaluations snapshot was captured
    rules = json.loads(snap.rule_evaluations_snapshot)
    assert len(rules) == 5
    assert rules[0]["rule_id"] == "R1"
    assert rules[0]["calculated_value"] == 40.0
    assert rules[1]["rule_id"] == "R2"
    assert rules[1]["calculated_value"] == 233.3333


def test_historical_evidence_preservation_after_source_modification(test_db):
    """Modifying the underlying trade record must not change the saved historical evidence snapshot."""
    trade, analysis = seed_trade_and_analysis(test_db, "SNAP-IMMUTABLE", score=50.0)

    service = EvidenceService(test_db)
    snap = service.create_or_get_snapshot(analysis)
    original_trade_val = json.loads(snap.source_payload_snapshot)["trade_value_usd"]
    assert original_trade_val == 1000000.0

    # Modify the source NormalizedTradeRecord
    trade.trade_value_usd = 9999999.0
    trade.commodity_code = "999999"
    test_db.commit()

    # Retrieve evidence again
    resp = service.get_snapshot_response("SNAP-IMMUTABLE")
    assert resp is not None
    # Frozen snapshot must still reflect the historical 1,000,000 value!
    assert resp.source_traceability.source_payload_snapshot["trade_value_usd"] == 1000000.0
    assert resp.source_traceability.source_payload_snapshot["commodity_code"] == "283691"


def test_evidence_validation_success_on_consistent_analysis(test_db):
    """A consistent analysis passes all verification checks."""
    _, analysis = seed_trade_and_analysis(test_db, "SNAP-VALID", score=50.0, classification="RED")

    val_service = EvidenceValidationService(test_db)
    result = val_service.validate_analysis_evidence("SNAP-VALID")

    assert result is not None
    assert result.analysis_id == "SNAP-VALID"
    assert result.validation_status == STATUS_VALID
    assert len(result.validation_errors) == 0

    # Verify check items
    check_names = {c.check_name: c.passed for c in result.checks_performed}
    assert check_names[CHECK_ANALYSIS_EXISTS] is True
    assert check_names[CHECK_CALCULATIONS_MATCH] is True
    assert check_names[CHECK_SCORE_WEIGHTS_MATCH] is True
    assert check_names[CHECK_COMPLETENESS_CONSISTENT] is True
    assert check_names[CHECK_CLASSIFICATION_CONSISTENT] is True


def test_evidence_validation_detects_score_weight_inconsistency(test_db):
    """Validation fails and preserves original evidence when score doesn't match flagged weights."""
    # Seed analysis where flagged rules are R1 (30) + R2 (20) = 50, but score is set to 80 (corrupt)
    _, analysis = seed_trade_and_analysis(test_db, "SNAP-TAMPERED-SCORE", score=80.0, classification="RED")

    val_service = EvidenceValidationService(test_db)
    result = val_service.validate_analysis_evidence("SNAP-TAMPERED-SCORE")

    assert result is not None
    assert result.validation_status == STATUS_INVALID
    assert len(result.validation_errors) >= 1
    assert any("does not match expected weighted sum" in err for err in result.validation_errors)

    # Verify original evidence was NOT deleted or silently overwritten
    evidence = (
        test_db.query(EvidenceSnapshot)
        .filter(EvidenceSnapshot.analysis_id == "SNAP-TAMPERED-SCORE")
        .first()
    )
    assert evidence is not None
    assert evidence.combined_anomaly_score == 80.0  # Preserved!
    assert evidence.validation_status == STATUS_INVALID


def test_evidence_validation_detects_calculation_formula_mismatch(test_db):
    """Validation detects when a calculated_value diverges from formula inputs beyond tolerance."""
    _, analysis = seed_trade_and_analysis(test_db, "SNAP-CALC-FAIL", score=50.0)

    # Tamper with Rule R1 calculated value in the rule result
    r1 = (
        test_db.query(RiskRuleResult)
        .filter(RiskRuleResult.analysis_id == "SNAP-CALC-FAIL", RiskRuleResult.rule_id == "R1")
        .first()
    )
    r1.calculated_value = 99.99  # Formula inputs 100k vs 60k evaluate to 40.0%
    test_db.commit()

    # Re-create snapshot with the tampered rule result
    test_db.query(EvidenceSnapshot).filter(EvidenceSnapshot.analysis_id == "SNAP-CALC-FAIL").delete()
    test_db.commit()

    val_service = EvidenceValidationService(test_db)
    result = val_service.validate_analysis_evidence("SNAP-CALC-FAIL")

    assert result.validation_status == STATUS_INVALID
    assert any("R1 gap mismatch" in err for err in result.validation_errors)


def test_evidence_validation_detects_classification_guardrail_violation(test_db):
    """Validation catches when an incomplete analysis is given a GREEN or RED classification instead of INSUFFICIENT_DATA."""
    # Score is 10.0, completeness is PARTIAL, but classification was incorrectly saved as GREEN
    _, analysis = seed_trade_and_analysis(
        test_db,
        "SNAP-GUARDRAIL-FAIL",
        score=10.0,
        completeness="PARTIAL",
        classification="GREEN",
    )

    val_service = EvidenceValidationService(test_db)
    result = val_service.validate_analysis_evidence("SNAP-GUARDRAIL-FAIL")

    assert result.validation_status == STATUS_INVALID
    assert any("violates data sufficiency guardrail" in err for err in result.validation_errors)


def test_audit_event_logging_and_retrieval(test_db):
    """AuditEventService correctly records and filters append-only events."""
    audit = AuditEventService(test_db)

    e1 = audit.record_event(
        event_type="TRADE_INGESTION_COMPLETED",
        related_record_id="RUN-100",
        operation_status="SUCCESS",
        metadata={"clean_count": 10},
    )
    e2 = audit.record_event(
        event_type="EVIDENCE_VALIDATION_FAILED",
        related_record_id="ANALYSIS-999",
        operation_status="FAILED",
        error_details="Calculation mismatch in Rule R2",
    )

    assert e1.event_id is not None
    assert e2.event_id is not None

    # Get single event
    fetched = audit.get_event(e1.event_id)
    assert fetched is not None
    assert fetched.event_type == "TRADE_INGESTION_COMPLETED"
    assert fetched.event_metadata["clean_count"] == 10

    # Filter events
    list_res = audit.list_events(event_type="TRADE_INGESTION_COMPLETED")
    assert list_res.total == 1
    assert list_res.events[0].event_id == e1.event_id

    list_failed = audit.list_events(operation_status="FAILED")
    assert list_failed.total == 1
    assert list_failed.events[0].event_id == e2.event_id


def test_evidence_for_non_existent_analysis_returns_none(test_db):
    """EvidenceService and ValidationService safely handle non-existent analysis IDs."""
    service = EvidenceService(test_db)
    val_service = EvidenceValidationService(test_db)

    assert service.get_snapshot_response("NON-EXISTENT-ID") is None
    assert val_service.validate_analysis_evidence("NON-EXISTENT-ID") is None
