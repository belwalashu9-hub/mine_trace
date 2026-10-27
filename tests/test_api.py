"""Tests for FastAPI endpoints."""
import pytest


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    """Verify /health returns 200 and healthy status."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["database_connected"] is True
    assert "version" in data


@pytest.mark.asyncio
async def test_data_status_endpoint(async_client):
    """Verify /api/v1/data/status returns 200 and system metadata."""
    response = await async_client.get("/api/v1/data/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OPERATIONAL"
    assert "record_counts" in data
    assert "last_retrievals" in data


@pytest.mark.asyncio
async def test_trade_ingestion_endpoint(async_client, comtrade_fixture_path):
    """Verify POST /api/v1/ingestion/trade triggers ingestion using fixture."""
    response = await async_client.post(
        "/api/v1/ingestion/trade",
        json={"fixture_path": comtrade_fixture_path},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["clean_records_count"] == 4
    assert data["run_id"] is not None


@pytest.mark.asyncio
async def test_trade_records_and_minerals_endpoints(async_client, comtrade_fixture_path):
    """Verify GET /api/v1/trade-records and GET /api/v1/minerals."""
    # First ingest fixture
    await async_client.post("/api/v1/ingestion/trade", json={"fixture_path": comtrade_fixture_path})

    # Test listing all
    resp = await async_client.get("/api/v1/trade-records?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert len(data["records"]) == 4

    # Test filter by commodity_code
    resp_filter = await async_client.get("/api/v1/trade-records?commodity_code=283691")
    assert resp_filter.status_code == 200
    data_filter = resp_filter.json()
    assert data_filter["total"] == 1
    assert data_filter["records"][0]["commodity_code"] == "283691"
    assert data_filter["records"][0]["reporter_country_code"] == "USA"

    # Test minerals endpoint
    resp_minerals = await async_client.get("/api/v1/minerals")
    assert resp_minerals.status_code == 200
    minerals = resp_minerals.json()
    assert len(minerals) >= 1
    codes = [m["commodity_code"] for m in minerals]
    assert "283691" in codes


@pytest.mark.asyncio
async def test_sanctions_ingestion_endpoint(async_client, ofac_fixture_path):
    """Verify POST /api/v1/ingestion/sanctions triggers OFAC ingestion."""
    response = await async_client.post(
        "/api/v1/ingestion/sanctions",
        json={"fixture_path": ofac_fixture_path},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["clean_records_count"] == 3


@pytest.mark.asyncio
async def test_pagination_and_query_validation(async_client):
    """Verify Pydantic query parameter validation."""
    # Invalid limit (less than 1)
    response = await async_client.get("/api/v1/trade-records?limit=0")
    assert response.status_code == 422
