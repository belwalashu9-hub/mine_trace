"""Integration tests for Phase 4 Risk Ranking API endpoints."""
from datetime import datetime, timezone
import json
import pytest

from app.database.models import RiskAnalysis


def seed_analysis(
    db,
    analysis_id: str,
    score: float,
    completeness: str = "COMPLETE",
    commodity_code: str = "283691",
    mineral_type: str = "Lithium carbonate",
    reporter: str = "CHL",
    partner: str = "USA",
    period: str = "2023",
    classification: str = "RED",
    flag_status: str = "FLAGGED",
):
    analysis = RiskAnalysis(
        analysis_id=analysis_id,
        trade_record_id=None,
        commodity_code=commodity_code,
        mineral_type=mineral_type,
        reporter_country_code=reporter,
        partner_country_code=partner,
        period=period,
        combined_anomaly_score=score,
        score_completeness=completeness,
        evaluated_rules=json.dumps(["R1", "R2", "R3", "R4", "R5"]),
        insufficient_rules=json.dumps(["R2"]) if completeness == "PARTIAL" else json.dumps([]),
        flagged_rules=json.dumps(["R1", "R3"]) if flag_status == "FLAGGED" else json.dumps([]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification=classification,
        flag_status=flag_status,
        classification_explanation="Test ranking API explanation",
        created_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    return analysis


@pytest.mark.asyncio
async def test_get_ranking_endpoint_basic(async_client, test_db):
    """GET /api/v1/ranking returns ordered ranking list."""
    seed_analysis(test_db, "REC-LOW", 20.0, classification="AMBER")
    seed_analysis(test_db, "REC-HIGH", 80.0, classification="RED")

    response = await async_client.get("/api/v1/ranking")
    assert response.status_code == 200
    data = response.json()

    assert data["policy_version"] == "1.0"
    assert "tie_breaker_policy" in data
    assert data["scope"] == "GLOBAL"
    assert data["total_eligible"] == 2
    assert len(data["rankings"]) == 2
    assert data["rankings"][0]["analysis_id"] == "REC-HIGH"
    assert data["rankings"][0]["rank"] == 1
    assert data["rankings"][1]["analysis_id"] == "REC-LOW"
    assert data["rankings"][1]["rank"] == 2


@pytest.mark.asyncio
async def test_get_ranking_with_filters(async_client, test_db):
    """GET /api/v1/ranking with query parameters filters results."""
    seed_analysis(test_db, "REC-RED", 85.0, classification="RED", commodity_code="283691")
    seed_analysis(test_db, "REC-AMBER", 45.0, classification="AMBER", commodity_code="283691")
    seed_analysis(test_db, "REC-COBALT", 90.0, classification="RED", commodity_code="260500")

    # Filter by classification
    resp_amber = await async_client.get("/api/v1/ranking?classification=AMBER")
    assert resp_amber.status_code == 200
    data_amber = resp_amber.json()
    assert data_amber["total_eligible"] == 1
    assert data_amber["scope"] == "FILTERED"
    assert data_amber["rankings"][0]["analysis_id"] == "REC-AMBER"

    # Filter by commodity and min_score
    resp_comm = await async_client.get("/api/v1/ranking?commodity_code=283691&min_score=50")
    assert resp_comm.status_code == 200
    data_comm = resp_comm.json()
    assert data_comm["total_eligible"] == 1
    assert data_comm["rankings"][0]["analysis_id"] == "REC-RED"


@pytest.mark.asyncio
async def test_get_incomplete_rankings_endpoint(async_client, test_db):
    """GET /api/v1/ranking/incomplete returns only incomplete records."""
    seed_analysis(test_db, "REC-COMPLETE", 75.0, completeness="COMPLETE")
    seed_analysis(test_db, "REC-PARTIAL", 35.0, completeness="PARTIAL")

    response = await async_client.get("/api/v1/ranking/incomplete")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 1
    assert len(data["records"]) == 1
    assert data["records"][0]["analysis_id"] == "REC-PARTIAL"
    assert "PARTIAL" in data["records"][0]["exclusion_reason"]


@pytest.mark.asyncio
async def test_get_ranking_summary_endpoint(async_client, test_db):
    """GET /api/v1/ranking/summary returns counts and score statistics."""
    seed_analysis(test_db, "REC-1", 80.0, completeness="COMPLETE", classification="RED")
    seed_analysis(test_db, "REC-2", 40.0, completeness="COMPLETE", classification="AMBER")
    seed_analysis(test_db, "REC-3", 10.0, completeness="PARTIAL", classification="INSUFFICIENT_DATA")

    response = await async_client.get("/api/v1/ranking/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["total_analyses"] == 3
    assert data["eligible_complete_count"] == 2
    assert data["partial_excluded_count"] == 1
    assert data["highest_score"] == 80.0
    assert data["lowest_score"] == 40.0
    assert data["average_score"] == 60.0


@pytest.mark.asyncio
async def test_get_analysis_rank_endpoint(async_client, test_db):
    """GET /api/v1/ranking/{analysis_id} returns rank context or 404."""
    seed_analysis(test_db, "REC-TOP", 95.0, completeness="COMPLETE")
    seed_analysis(test_db, "REC-2ND", 65.0, completeness="COMPLETE")

    # Found record
    resp_top = await async_client.get("/api/v1/ranking/REC-TOP")
    assert resp_top.status_code == 200
    data_top = resp_top.json()
    assert data_top["is_eligible"] is True
    assert data_top["rank"] == 1
    assert data_top["total_eligible"] == 2

    resp_2nd = await async_client.get("/api/v1/ranking/REC-2ND")
    assert resp_2nd.status_code == 200
    data_2nd = resp_2nd.json()
    assert data_2nd["rank"] == 2

    # Not found record
    resp_404 = await async_client.get("/api/v1/ranking/REC-NONEXISTENT")
    assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_snapshots_workflow(async_client, test_db):
    """POST /api/v1/ranking/snapshots and GET by ID."""
    seed_analysis(test_db, "REC-1", 80.0, commodity_code="283691")
    seed_analysis(test_db, "REC-2", 50.0, commodity_code="283691")

    # Create snapshot
    payload = {
        "name": "Audit 2026-Q1",
        "description": "Baseline supply chain risk ranking snapshot",
        "commodity_code": "283691",
    }
    create_resp = await async_client.post("/api/v1/ranking/snapshots", json=payload)
    assert create_resp.status_code == 201
    snap_data = create_resp.json()

    snap_id = snap_data["snapshot_id"]
    assert snap_data["name"] == "Audit 2026-Q1"
    assert snap_data["total_eligible_count"] == 2
    assert len(snap_data["items"]) == 2
    assert snap_data["items"][0]["rank"] == 1
    assert snap_data["items"][0]["analysis_id"] == "REC-1"

    # List snapshots
    list_resp = await async_client.get("/api/v1/ranking/snapshots")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1

    # Get snapshot by ID
    get_resp = await async_client.get(f"/api/v1/ranking/snapshots/{snap_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["snapshot_id"] == snap_id
    assert len(get_data["items"]) == 2

    # Non-existent snapshot ID returns 404
    resp_404 = await async_client.get("/api/v1/ranking/snapshots/non-existent-uuid")
    assert resp_404.status_code == 404
