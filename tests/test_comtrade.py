"""Tests for UN Comtrade data ingestion client and service."""
import pytest
from unittest.mock import patch, MagicMock
import httpx

from app.ingestion.comtrade_client import ComtradeClient, ComtradeAPIError
from app.ingestion.service import IngestionService
from app.database.repository import MineTraceRepository


def test_comtrade_fixture_loading(comtrade_fixture_path):
    """Verify loading and parsing clearly labeled UN Comtrade test fixtures."""
    client = ComtradeClient()
    result = client.load_from_fixture(comtrade_fixture_path)
    assert result["source"] == "UN_COMTRADE_FIXTURE"
    assert result["records_count"] == 6
    assert isinstance(result["data"], list)
    assert result["data"][0]["cmdCode"] == "283691"


def test_comtrade_timeout_handling():
    """Verify that httpx.TimeoutException raises a clean ComtradeAPIError with informative message."""
    client = ComtradeClient(timeout=0.001)
    
    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
        with pytest.raises(ComtradeAPIError) as exc_info:
            client.fetch_trade_data(commodity_codes=["283691"])
        assert "timed out" in str(exc_info.value).lower()


def test_comtrade_rate_limit_handling():
    """Verify that HTTP 429 raises rate-limit specific ComtradeAPIError."""
    client = ComtradeClient()
    
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Too Many Requests"
    
    with patch("httpx.Client.get", return_value=mock_resp):
        with pytest.raises(ComtradeAPIError) as exc_info:
            client.fetch_trade_data(commodity_codes=["283691"])
        assert "rate limit" in str(exc_info.value).lower()


def test_comtrade_malformed_json():
    """Verify handling of malformed or invalid JSON responses."""
    client = ComtradeClient()
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("Invalid JSON string")
    
    with patch("httpx.Client.get", return_value=mock_resp):
        with pytest.raises(ComtradeAPIError) as exc_info:
            client.fetch_trade_data(commodity_codes=["283691"])
        assert "malformed" in str(exc_info.value).lower()


def test_ingest_trade_data_service(test_db, comtrade_fixture_path):
    """Verify full ingestion service pipeline with fixture data."""
    service = IngestionService(test_db)
    repo = MineTraceRepository(test_db)

    res = service.ingest_trade_data(fixture_path=comtrade_fixture_path)
    assert res["status"] == "COMPLETED"
    assert res["raw_records_count"] == 6
    # 4 distinct valid records, 1 duplicate, 1 fatal invalid record
    assert res["clean_records_count"] == 4
    assert res["warning_count"] >= 1  # Duplicate logged as warning/info
    assert res["error_count"] >= 1    # Invalid record logged as error

    # Verify records in database
    records, total = repo.list_trade_records()
    assert total == 4

    # Verify critical mineral types resolved
    minerals = repo.get_distinct_minerals()
    mineral_types = {m["mineral_type"] for m in minerals}
    assert "Lithium" in mineral_types
