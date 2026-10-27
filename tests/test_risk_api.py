"""Integration tests for Phase 2 Risk API endpoints."""
import pytest


@pytest.mark.asyncio
async def test_get_risk_rules_catalog(async_client):
    """Verify GET /api/v1/risk/rules returns all 5 rule specifications."""
    response = await async_client.get("/api/v1/risk/rules")
    assert response.status_code == 200
    rules = response.json()
    assert len(rules) == 5
    rule_ids = [r["rule_id"] for r in rules]
    assert rule_ids == ["R1", "R2", "R3", "R4", "R5"]
    assert rules[0]["weight"] == 30
    assert rules[1]["weight"] == 20
    assert rules[2]["weight"] == 30
    assert rules[3]["weight"] == 20
    assert rules[4]["weight"] == 0  # R5 is non-numeric sanctions screening


@pytest.mark.asyncio
async def test_run_risk_analysis_endpoint(async_client, comtrade_fixture_path, ofac_fixture_path):
    """Verify POST /api/v1/risk/analyze runs risk engine and returns complete results."""
    # Seed trade data and OFAC data
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})
    await async_client.post("/api/v1/ingestion/sanctions", json={"fixture_path": ofac_fixture_path})

    # Trigger analysis on all records
    resp = await async_client.post(
        "/api/v1/risk/analyze",
        json={"commodity_code": "283691", "entity_name": "Northern Minerals Trading Ltd."},
    )
    assert resp.status_code == 200
    analyses = resp.json()
    assert len(analyses) >= 1
    first = analyses[0]
    assert "analysis_id" in first
    assert "combined_anomaly_score" in first
    assert first["score_completeness"] in ("COMPLETE", "PARTIAL", "UNAVAILABLE")
    assert len(first["rule_results"]) == 5
    # R5 should be REVIEW_MATCH because entity name matched OFAC fixture
    assert first["sanctions_status"] == "REVIEW_MATCH"


@pytest.mark.asyncio
async def test_list_and_get_analysis_detail(async_client, comtrade_fixture_path):
    """Verify GET /api/v1/risk/results and GET /api/v1/risk/results/{analysis_id}."""
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})
    analysis_resp = await async_client.post("/api/v1/risk/analyze", json={})
    assert analysis_resp.status_code == 200
    created = analysis_resp.json()
    assert len(created) > 0
    target_id = created[0]["analysis_id"]

    # List results
    list_resp = await async_client.get("/api/v1/risk/results?limit=10")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= len(created)
    assert any(a["analysis_id"] == target_id for a in list_data["analyses"])

    # Get single result
    detail_resp = await async_client.get(f"/api/v1/risk/results/{target_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["analysis_id"] == target_id
    assert len(detail["rule_results"]) == 5

    # 404 on invalid ID
    not_found_resp = await async_client.get("/api/v1/risk/results/non-existent-uuid")
    assert not_found_resp.status_code == 404


@pytest.mark.asyncio
async def test_risk_summary_endpoint(async_client, comtrade_fixture_path):
    """Verify GET /api/v1/risk/summary returns aggregate statistics."""
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})
    await async_client.post("/api/v1/risk/analyze", json={})

    summary_resp = await async_client.get("/api/v1/risk/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total_analyses"] >= 1
    assert "flagged_rules_breakdown" in summary
    assert "sanctions_status_breakdown" in summary
    assert "R1" in summary["flagged_rules_breakdown"]


@pytest.mark.asyncio
async def test_audit_preservation_subsequent_runs(async_client, comtrade_fixture_path):
    """Verify that running analysis again does NOT delete or overwrite prior historical runs."""
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})
    
    # Run 1
    run1 = (await async_client.post("/api/v1/risk/analyze", json={})).json()
    count_run1 = len(run1)

    # Run 2
    run2 = (await async_client.post("/api/v1/risk/analyze", json={})).json()
    count_run2 = len(run2)

    list_resp = (await async_client.get("/api/v1/risk/results")).json()
    assert list_resp["total"] == count_run1 + count_run2
