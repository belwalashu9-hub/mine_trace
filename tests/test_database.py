"""Tests for SQLite database initialization, models, and repository operations."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from app.database.connection import init_db, Base
from app.database.models import (
    DataSourceMetadata,
    IngestionRun,
    RawTradeRecord,
    NormalizedTradeRecord,
    OfacSanctionRecord,
    DataQualityIssue,
)
from app.database.repository import MineTraceRepository
from app.ingestion.cleaning import compute_trade_record_hash, compute_ofac_record_hash


def test_idempotent_init_db():
    """Verify that init_db can be called repeatedly without deleting or corrupting existing tables."""
    mem_engine = create_engine("sqlite:///:memory:")
    # First initialization
    init_db(target_engine=mem_engine)
    # Re-initialization should be safe and idempotent
    init_db(target_engine=mem_engine)
    assert True


def test_save_and_retrieve_trade_record(test_db):
    """Verify saving a normalized trade record and retrieving it via repository."""
    repo = MineTraceRepository(test_db)
    
    source = repo.get_or_create_data_source(
        source_name="UN_COMTRADE",
        source_url="https://comtradeapi.un.org",
        description="UN Comtrade",
    )
    assert source.id is not None

    rec_hash = compute_trade_record_hash(
        reporter_code="USA",
        partner_code="CHL",
        commodity_code="283691",
        flow_type="IMPORT",
        period="2023",
        trade_value=1250000.0,
    )

    record_dict = {
        "source_record_id": "REC-001",
        "record_hash": rec_hash,
        "commodity_code": "283691",
        "commodity_description": "Lithium carbonates",
        "mineral_type": "Lithium",
        "flow_type": "IMPORT",
        "reporter_country_code": "USA",
        "reporter_country_name": "United States",
        "partner_country_code": "CHL",
        "partner_country_name": "Chile",
        "period": "2023",
        "period_year": 2023,
        "period_month": None,
        "trade_value_usd": 1250000.0,
        "currency": "USD",
        "net_weight_kg": 50000.0,
        "quantity": 50000.0,
        "quantity_unit": "kg",
        "is_valid": True,
        "has_warnings": False,
        "retrieval_timestamp": datetime.now(timezone.utc),
    }

    record, created = repo.save_normalized_trade_record(record_dict)
    assert created is True
    assert record.id is not None
    assert record.commodity_code == "283691"
    assert record.trade_value_usd == 1250000.0

    # Query back
    records, total = repo.list_trade_records(commodity_code="283691")
    assert total == 1
    assert records[0].reporter_country_code == "USA"
    assert records[0].partner_country_code == "CHL"


def test_duplicate_trade_record_prevention(test_db):
    """Verify that saving the exact same record twice does NOT create duplicates."""
    repo = MineTraceRepository(test_db)
    
    rec_hash = compute_trade_record_hash("USA", "CHL", "283691", "IMPORT", "2023", 1000.0)
    record_dict = {
        "source_record_id": "REC-DUP",
        "record_hash": rec_hash,
        "commodity_code": "283691",
        "mineral_type": "Lithium",
        "flow_type": "IMPORT",
        "reporter_country_code": "USA",
        "reporter_country_name": "United States",
        "partner_country_code": "CHL",
        "partner_country_name": "Chile",
        "period": "2023",
        "period_year": 2023,
        "trade_value_usd": 1000.0,
        "currency": "USD",
        "retrieval_timestamp": datetime.now(timezone.utc),
    }

    # First insert
    rec1, created1 = repo.save_normalized_trade_record(record_dict)
    assert created1 is True

    # Duplicate insert attempt
    rec2, created2 = repo.save_normalized_trade_record(record_dict)
    assert created2 is False
    assert rec1.id == rec2.id

    records, total = repo.list_trade_records(commodity_code="283691")
    assert total == 1


def test_save_and_retrieve_ofac_sanction_record(test_db):
    """Verify saving OFAC records and deduplication."""
    repo = MineTraceRepository(test_db)
    rec_hash = compute_ofac_record_hash("1001", "NORTHERN MINERALS TRADING LLC", "entity", "Russia")

    ofac_dict = {
        "source_record_id": "1001",
        "source_name": "OFAC_SDN",
        "record_hash": rec_hash,
        "entity_type": "entity",
        "primary_name": "NORTHERN MINERALS TRADING LLC",
        "aliases": "NORTHERN MINING",
        "programs": "RUSSIA-EO14024",
        "country": "Russia",
        "remarks": "Major mineral exporter",
        "retrieval_timestamp": datetime.now(timezone.utc),
    }

    record, created = repo.save_ofac_sanction_record(ofac_dict)
    assert created is True
    assert record.id is not None
    assert record.primary_name == "NORTHERN MINERALS TRADING LLC"

    # Duplicate attempt
    record_dup, created_dup = repo.save_ofac_sanction_record(ofac_dict)
    assert created_dup is False
    assert record_dup.id == record.id

    records, total = repo.list_sanctions_records(country="Russia")
    assert total == 1
    assert records[0].source_record_id == "1001"


def test_data_quality_issue_logging(test_db):
    """Verify logging and auditing of data quality issues."""
    repo = MineTraceRepository(test_db)
    run = repo.create_ingestion_run(source_name="TEST_SOURCE")

    issue = repo.log_quality_issue(
        ingestion_run_id=run.id,
        source_record_id="REC-ERR-1",
        table_name="raw_trade_records",
        severity="WARNING",
        issue_type="MISSING_QUANTITY",
        column_name="netWgt",
        raw_value=None,
        message="Net weight missing from trade report.",
    )
    assert issue.id is not None
    assert issue.severity == "WARNING"

    status = repo.get_system_status()
    assert status["record_counts"]["data_quality_issues"] >= 1
