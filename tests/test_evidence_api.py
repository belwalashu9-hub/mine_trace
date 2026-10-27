"""Integration tests for Phase 5 Evidence & Audit Trail API routes."""
from datetime import datetime, timezone
import json
import pytest

from app.database.models import RiskAnalysis, RiskRuleResult, NormalizedTradeRecord


def seed_analysis_with_rules(
    db,
    analysis_id: str,
    score: float = 30.0,
    completeness: str = "COMPLETE",
    classification: str = "AMBER",
    flag_status: str = "FLAGGED",
):
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
        trade_value_usd=500000.0,
        net_weight_kg=25000.0,
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
        flagged_rules=json.dumps(["R1"]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification=classification,
        flag_status=flag_status,
        classification_explanation="Test API explanation",
        created_at=datetime.now(timezone.utc),
    )
    db.add(analysis)

    r1 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R1",
        rule_name="Mirror Trade Gap",
        rule_version="1.0",
        weight=30,
        outcome="FLAG",
        threshold="greater than 30%",
        formula="abs(export_value - import_value) / max(export_value, import_value) * 100",
        calculated_value=50.0,
        input_values=json.dumps({"export_value": 100000.0, "import_value": 50000.0}),
        explanation="Mirror trade gap 50.0% is flagged.",
    )
    db.add(r1)

    r2 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R2",
        rule_name="Volume Spike",
        rule_version="1.0",
        weight=20,
        outcome="NOT_FLAGGED",
        threshold="greater than 200%",
        formula="(current_volume - previous_volume) / previous_volume * 100",
        calculated_value=20.0,
        input_values=json.dumps({"current_volume": 120.0, "previous_volume": 100.0}),
        explanation="Volume change 20% is not flagged.",
    )
    db.add(r2)

    r3 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R3",
        rule_name="Route Concentration",
        rule_version="1.0",
        weight=30,
        outcome="NOT_FLAGGED",
        threshold="greater than 80%",
        formula="partner_import_volume / total_import_volume * 100",
        calculated_value=40.0,
        input_values=json.dumps({"partner_import_volume": 400.0, "total_import_volume": 1000.0}),
        explanation="Route concentration 40% is not flagged.",
    )
    db.add(r3)

    r4 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R4",
        rule_name="Unusual Unit Price",
        rule_version="1.0",
        weight=20,
        outcome="NOT_FLAGGED",
        threshold="greater than 60%",
        formula="abs(unit_price - median_price) / median_price * 100",
        calculated_value=10.0,
        input_values=json.dumps({"unit_price": 20.0, "median_price": 22.0}),
        explanation="Unit price deviation 10% is not flagged.",
    )
    db.add(r4)

    r5 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R5",
        rule_name="Sanctions Screening",
        rule_version="1.0",
        weight=0,
        outcome="NO_IDENTIFIED_MATCH",
        threshold="OFAC SDN match",
        formula="exact_match or token_similarity > 0.85",
        calculated_value=0.0,
        input_values=json.dumps({"entity_name": None}),
        explanation="No identified match.",
    )
    db.add(r5)

    db.commit()
    return analysis


@pytest.mark.asyncio
async def test_get_evidence_endpoint_success(async_client, test_db):
    """GET /api/v1/evidence/{analysis_id} returns full versioned evidence snapshot."""
    seed_analysis_with_rules(test_db, "EVID-API-001", score=30.0, classification="AMBER")

    resp = await async_client.get("/api/v1/evidence/EVID-API-001")
    assert resp.status_code == 200
    data = resp.json()

    assert data["evidence_id"] is not None
    assert data["analysis_id"] == "EVID-API-001"
    assert data["schema_version"] == "1.0"
    assert data["score"]["combined_anomaly_score"] == 30.0
    assert data["score"]["score_completeness"] == "COMPLETE"
    assert data["classification"]["classification"] == "AMBER"
    assert data["source_traceability"]["source_dataset_name"] == "UN Comtrade (Normalized)"
    assert len(data["rules"]) == 5
    assert data["rules"][0]["rule_id"] == "R1"
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_get_evidence_endpoint_not_found(async_client):
    """GET /api/v1/evidence/{analysis_id} returns 404 for unknown analysis ID."""
    resp = await async_client.get("/api/v1/evidence/NON-EXISTENT-ANALYSIS")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_validate_evidence_endpoint(async_client, test_db):
    """GET /api/v1/evidence/{analysis_id}/validate executes validation checks."""
    seed_analysis_with_rules(test_db, "EVID-VAL-001", score=30.0, classification="AMBER")

    resp = await async_client.get("/api/v1/evidence/EVID-VAL-001/validate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["analysis_id"] == "EVID-VAL-001"
    assert data["validation_status"] in ["VALID", "WARNINGS"]
    assert len(data["checks_performed"]) > 0
    assert "tolerance_used" in data


@pytest.mark.asyncio
async def test_audit_events_api_workflow(async_client, test_db):
    """Audit events listing, filtering, and detail endpoints."""
    # Seed analysis (which triggers evidence generation and audit events)
    seed_analysis_with_rules(test_db, "AUDIT-FLOW-001", score=30.0)

    # Validate analysis (which logs validation audit event)
    await async_client.get("/api/v1/evidence/AUDIT-FLOW-001/validate")

    # List audit events
    list_resp = await async_client.get("/api/v1/audit/events")
    assert list_resp.status_code == 200
    events_data = list_resp.json()

    assert events_data["total"] >= 1
    assert len(events_data["events"]) >= 1
    first_event = events_data["events"][0]
    event_id = first_event["event_id"]

    # Filter audit events by related_record_id
    filtered_resp = await async_client.get("/api/v1/audit/events?related_record_id=AUDIT-FLOW-001")
    assert filtered_resp.status_code == 200
    filtered_data = filtered_resp.json()
    assert filtered_data["total"] >= 1

    # Get single audit event by ID
    single_resp = await async_client.get(f"/api/v1/audit/events/{event_id}")
    assert single_resp.status_code == 200
    single_data = single_resp.json()
    assert single_data["event_id"] == event_id

    # 404 for non-existent audit event
    not_found_resp = await async_client.get("/api/v1/audit/events/non-existent-event-id")
    assert not_found_resp.status_code == 404
