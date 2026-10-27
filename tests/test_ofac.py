"""Tests for OFAC Sanctions data ingestion client and service."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import httpx

from app.ingestion.ofac_client import OfacClient, OfacAPIError
from app.ingestion.service import IngestionService
from app.database.repository import MineTraceRepository


def test_ofac_fixture_loading(ofac_fixture_path):
    """Verify loading and parsing official OFAC SDN test fixtures."""
    client = OfacClient()
    result = client.load_from_fixture(ofac_fixture_path)
    assert result["source"] == "OFAC_SDN_FIXTURE"
    assert result["records_count"] >= 4
    first_rec = result["data"][0]
    assert first_rec["Ent_num"] == "1001"
    assert "NORTHERN MINERALS" in first_rec["SDN_Name"]


def test_ofac_network_error_without_cache(tmp_path):
    """Verify that network error with no existing cache raises clear OfacAPIError."""
    client = OfacClient(cache_dir=tmp_path / "empty_cache")
    
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Network unreachable")):
        with pytest.raises(OfacAPIError) as exc_info:
            client.fetch_sdn_list()
        assert "unavailable and no local offline cache" in str(exc_info.value).lower()


def test_ofac_network_error_with_local_cache(tmp_path, ofac_fixture_path):
    """Verify offline fallback: if network is down, local cached file is safely returned."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "ofac_sdn_latest.csv"

    # Pre-populate cache with fixture content
    with open(ofac_fixture_path, "r", encoding="utf-8") as f:
        cache_file.write_text(f.read())

    client = OfacClient(cache_dir=cache_dir)
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Internet Down")):
        result = client.fetch_sdn_list()
        assert result["source"] == "OFAC_SDN_CACHED"
        assert result["is_cached"] is True
        assert result["records_count"] >= 4


def test_ingest_sanctions_service(test_db, ofac_fixture_path):
    """Verify end-to-end sanctions ingestion service pipeline."""
    service = IngestionService(test_db)
    repo = MineTraceRepository(test_db)

    res = service.ingest_sanctions_data(fixture_path=ofac_fixture_path)
    assert res["status"] == "COMPLETED"
    # Fixture has 3 distinct valid entries, 1 duplicate, 2 missing required fields
    assert res["clean_records_count"] == 3
    assert res["error_count"] >= 2

    records, total = repo.list_sanctions_records()
    assert total == 3
    names = [r.primary_name for r in records]
    assert "NORTHERN MINERALS TRADING LLC" in names
    assert "IVANOV, Sergey Viktorovich" in names


def test_ofac_json_fixture_loading(fixtures_dir):
    """Verify loading and parsing synthetic OFAC JSON test fixtures."""
    client = OfacClient()
    json_path = str(fixtures_dir / "ofac_sample.json")
    result = client.load_from_fixture(json_path)
    assert result["source"] == "OFAC_SDN_FIXTURE"
    assert result["records_count"] == 3
    first_rec = result["data"][0]
    assert first_rec["Ent_num"] == "9001"
    assert "SYNTHETIC MINERALS" in first_rec["SDN_Name"]

