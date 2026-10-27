"""Integration tests for Phase 3 Risk Classification API endpoints."""
import pytest


@pytest.mark.asyncio
async def test_get_classification_thresholds_endpoint(async_client):
    """Verify GET /api/v1/classification/thresholds returns prototype rules & disclaimer."""
    response = await async_client.get("/api/v1/classification/thresholds")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "disclaimer" in data
    assert len(data["categories"]) == 4
    cat_names = [c["category"] for c in data["categories"]]
    assert "GREEN" in cat_names
    assert "AMBER" in cat_names
    assert "RED" in cat_names
    assert "INSUFFICIENT_DATA" in cat_names


@pytest.mark.asyncio
async def test_classify_and_list_results(async_client, comtrade_fixture_path):
    """Verify POST /api/v1/classification/classify and GET /api/v1/classification/results."""
    # Seed trade data and run risk analysis
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})
    analyses = (await async_client.post("/api/v1/risk/analyze", json={})).json()
    assert len(analyses) > 0
    first_analysis_id = analyses[0]["analysis_id"]

    # Trigger classification endpoint
    classify_resp = await async_client.post("/api/v1/classification/classify", json={})
    assert classify_resp.status_code == 200
    classified_items = classify_resp.json()
    assert len(classified_items) >= len(analyses)
    assert all("classification" in item for item in classified_items)
    assert all("flag_status" in item for item in classified_items)

    # Classify specific ID
    single_resp = await async_client.post(
        "/api/v1/classification/classify",
        json={"analysis_id": first_analysis_id},
    )
    assert single_resp.status_code == 200
    assert len(single_resp.json()) == 1

    # Classify 404
    not_found = await async_client.post(
        "/api/v1/classification/classify",
        json={"analysis_id": "non-existent-uuid"},
    )
    assert not_found.status_code == 404

    # List results with pagination & filter
    list_resp = await async_client.get("/api/v1/classification/results?limit=10")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= len(classified_items)
    assert len(list_data["analyses"]) > 0

    # Get single classified result
    detail_resp = await async_client.get(f"/api/v1/classification/results/{first_analysis_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["analysis_id"] == first_analysis_id
    assert detail["classification"] in ("GREEN", "AMBER", "RED", "INSUFFICIENT_DATA")


@pytest.mark.asyncio
async def test_classification_summary_endpoint(async_client, comtrade_fixture_path):
    """Verify GET /api/v1/classification/summary returns aggregated counts."""
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})
    await async_client.post("/api/v1/risk/analyze", json={})
    await async_client.post("/api/v1/classification/classify", json={})

    summary_resp = await async_client.get("/api/v1/classification/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total_analyses"] >= 1
    assert "classification_breakdown" in summary
    assert "flag_status_breakdown" in summary
    assert "disclaimer" in summary
