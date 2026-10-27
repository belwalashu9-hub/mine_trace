"""
Unit and Integration tests for Model 2 Phase 2:
GDELT News Ingestion, Deduplication & SQLite Persistence.

Covers all 16 required verification scenarios:
1.  Successful article insertion
2.  Multiple article insertion
3.  Duplicate article deduplication
4.  Repeated ingestion idempotency
5.  Multi-category association for single article
6.  Missing optional fields handling
7.  Invalid required fields handling
8.  Invalid date values handling
9.  Database transaction failure and rollback
10. Updating existing article metadata without overwriting with null
11. Preserving first-seen timestamps while updating last-seen timestamps
12. Ingestion history recording (gdelt_ingestion_runs)
13. Retrieval of pending articles and category queries
14. Empty API results handling
15. Provider outage / error handling
16. Existing Model 1 data preservation
"""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.database.models import (
    GdeltArticle,
    GdeltArticleCategory,
    GdeltIngestionRun,
    NormalizedTradeRecord,
    RawTradeRecord,
    RiskAnalysis,
    utc_now,
)
from app.geopolitical.gdelt_client import (
    GdeltClient,
    GdeltRateLimitError,
    GdeltTimeoutError,
    GdeltConnectionError,
    GdeltAPIError,
)
from app.geopolitical.ingestion_service import GDELTIngestionService
from app.geopolitical.retrieval_service import GDELTRetrievalService
from app.schemas.geopolitical import GeopoliticalCategory, CriticalMineral


SAMPLE_ARTICLE_1 = {
    "url": "https://example-mining-news.com/articles/2026/08/lithium-export-controls-announced?utm_source=feed",
    "title": "Government Imposes Strict Export Controls on Refined Lithium Carbonate",
    "seendate": "20260825T143000Z",
    "domain": "example-mining-news.com",
    "language": "English",
    "sourcecountry": "Chile",
}

SAMPLE_ARTICLE_2 = {
    "url": "https://global-minerals-daily.org/africa/cobalt-miners-strike-shuts-down-key-corridor",
    "title": "Union Walkout Shuts Down Operations at Major Katanga Cobalt Extraction Site",
    "seendate": "20260824T091500Z",
    "domain": "global-minerals-daily.org",
    "language": "English",
    "sourcecountry": "Democratic Republic of the Congo",
}

SAMPLE_ARTICLE_3 = {
    "url": "https://pacific-trade-dispatch.com/nickel-smelter-operations-halted-amid-power-outages",
    "title": "Nickel Smelting Halted Across Central Processing Hub Following Grid Failure",
    "seendate": "20260823T184500Z",
    "domain": "pacific-trade-dispatch.com",
    "language": "English",
    "sourcecountry": "Indonesia",
}


# =============================================================================
# Test 1: Successful Article Insertion
# =============================================================================
def test_successful_article_insertion(test_db):
    """Scenario 1: Insert a single valid normalized article into SQLite."""
    service = GDELTIngestionService(db=test_db)
    summary = service.ingest_articles(
        raw_articles=[SAMPLE_ARTICLE_1],
        run_type="FIXTURE",
        category="trade_restrictions",
    )

    assert summary.status == "COMPLETED"
    assert summary.fetched_count == 1
    assert summary.valid_count == 1
    assert summary.inserted_count == 1
    assert summary.duplicate_count == 0
    assert summary.failed_count == 0

    # Verify article row in database
    retrieval = GDELTRetrievalService(db=test_db)
    articles = retrieval.list_articles()
    assert len(articles) == 1

    art = articles[0]
    assert art.event_id.startswith("evt_")
    assert "lithium-export-controls-announced" in art.canonical_url
    assert "utm_source" not in art.canonical_url  # Canonicalized
    assert art.title == SAMPLE_ARTICLE_1["title"]
    assert art.source_domain == "example-mining-news.com"
    assert art.source_country == "Chile"
    assert art.classification_status == "pending"
    assert art.provider == "synthetic_fixture"
    assert art.first_seen_at is not None
    assert art.last_seen_at is not None
    assert art.gdelt_seen_date is not None

    # Strict Phase 2 boundaries: classification fields must remain NULL
    assert art.affected_country is None
    assert art.mineral is None
    assert art.event_type is None
    assert art.event_date is None


# =============================================================================
# Test 2: Multiple Article Insertion
# =============================================================================
def test_multiple_article_insertion(test_db):
    """Scenario 2: Insert multiple articles from a batch."""
    service = GDELTIngestionService(db=test_db)
    summary = service.ingest_articles(
        raw_articles=[SAMPLE_ARTICLE_1, SAMPLE_ARTICLE_2, SAMPLE_ARTICLE_3],
        run_type="FIXTURE",
        category="mining_strikes",
    )

    assert summary.status == "COMPLETED"
    assert summary.fetched_count == 3
    assert summary.valid_count == 3
    assert summary.inserted_count == 3
    assert summary.duplicate_count == 0
    assert summary.failed_count == 0

    retrieval = GDELTRetrievalService(db=test_db)
    assert retrieval.count_articles() == 3


# =============================================================================
# Test 3: Duplicate Article Deduplication
# =============================================================================
def test_duplicate_article_deduplication(test_db):
    """Scenario 3: Same article ingested twice does not create a duplicate."""
    service = GDELTIngestionService(db=test_db)

    # First ingestion
    sum1 = service.ingest_articles([SAMPLE_ARTICLE_1], run_type="FIXTURE")
    assert sum1.inserted_count == 1
    assert sum1.duplicate_count == 0

    # Second ingestion of the identical article
    sum2 = service.ingest_articles([SAMPLE_ARTICLE_1], run_type="FIXTURE")
    assert sum2.inserted_count == 0
    assert sum2.duplicate_count == 1
    assert sum2.updated_count == 1

    # Database count remains strictly 1
    retrieval = GDELTRetrievalService(db=test_db)
    assert retrieval.count_articles() == 1


# =============================================================================
# Test 4: Repeated Ingestion Idempotency
# =============================================================================
def test_repeated_ingestion_idempotency(test_db, fixtures_dir):
    """Scenario 4: Repeated full dataset ingestion is completely idempotent."""
    fixture_file = str(fixtures_dir / "gdelt_sample.json")
    service = GDELTIngestionService(db=test_db)

    # Run 1
    run1 = service.ingest_from_fixture(fixture_path=fixture_file)
    initial_count = run1.inserted_count
    assert initial_count > 0

    # Run 2 with same fixture
    run2 = service.ingest_from_fixture(fixture_path=fixture_file)
    assert run2.inserted_count == 0
    assert run2.duplicate_count == initial_count

    retrieval = GDELTRetrievalService(db=test_db)
    assert retrieval.count_articles() == initial_count


# =============================================================================
# Test 5: Multi-Category Association for Single Article
# =============================================================================
def test_same_article_multiple_search_categories(test_db):
    """Scenario 5: An article matching multiple search categories associates all categories without duplicating the article."""
    service = GDELTIngestionService(db=test_db)

    # Ingest under 'mining_strikes'
    service.ingest_articles([SAMPLE_ARTICLE_1], category="mining_strikes")

    # Ingest same article under 'trade_restrictions'
    service.ingest_articles([SAMPLE_ARTICLE_1], category="trade_restrictions")

    # Ingest again under 'mining_strikes' (duplicate category should not create redundant row)
    service.ingest_articles([SAMPLE_ARTICLE_1], category="mining_strikes")

    retrieval = GDELTRetrievalService(db=test_db)
    articles = retrieval.list_articles()
    assert len(articles) == 1

    art_id = articles[0].id
    cats = retrieval.get_article_categories(art_id)
    assert len(cats) == 2
    assert "mining_strikes" in cats
    assert "trade_restrictions" in cats


# =============================================================================
# Test 6: Missing Optional Fields Handling
# =============================================================================
def test_missing_optional_fields(test_db):
    """Scenario 6: Ingest an article with minimal data (missing title, domain, country)."""
    minimal_article = {
        "url": "https://raw-alerts.net/news-dispatch/item-10294",
        # title, domain, language, sourcecountry, seendate all omitted
    }
    service = GDELTIngestionService(db=test_db)
    summary = service.ingest_articles([minimal_article])

    assert summary.status == "COMPLETED"
    assert summary.inserted_count == 1

    retrieval = GDELTRetrievalService(db=test_db)
    art = retrieval.get_article_by_canonical_url("https://raw-alerts.net/news-dispatch/item-10294")
    assert art is not None
    assert art.title is None
    assert art.source_domain == "raw-alerts.net"  # extracted from URL
    assert art.source_country is None
    assert art.gdelt_seen_date is None
    assert art.classification_status == "pending"


# =============================================================================
# Test 7: Invalid Required Fields Handling
# =============================================================================
def test_invalid_required_fields(test_db):
    """Scenario 7: Completely unnormalizable records fail gracefully without failing the entire batch."""
    invalid_record_1 = {}  # completely empty
    invalid_record_2 = "not a dictionary"
    invalid_record_3 = {"url": "", "title": ""}  # both missing

    service = GDELTIngestionService(db=test_db)
    summary = service.ingest_articles(
        [invalid_record_1, SAMPLE_ARTICLE_1, invalid_record_2, invalid_record_3]
    )

    assert summary.status == "PARTIAL"
    assert summary.fetched_count == 4
    assert summary.valid_count == 1
    assert summary.inserted_count == 1
    assert summary.failed_count == 3


# =============================================================================
# Test 8: Invalid Date Values Handling
# =============================================================================
def test_invalid_date_values(test_db):
    """Scenario 8: Articles with malformed dates are saved with None for date without crashing."""
    corrupt_date_article = {
        "url": "https://mining-monitor.com/corrupt-date-article",
        "title": "Mine Expansion Proceeding on Schedule",
        "seendate": "INVALID_SEENDATE_STRING_2026",
    }
    service = GDELTIngestionService(db=test_db)
    summary = service.ingest_articles([corrupt_date_article])

    assert summary.status == "COMPLETED"
    assert summary.inserted_count == 1

    retrieval = GDELTRetrievalService(db=test_db)
    art = retrieval.list_articles()[0]
    assert art.gdelt_seen_date is None
    assert art.first_seen_at is not None


# =============================================================================
# Test 9: Database Transaction Failure and Rollback
# =============================================================================
def test_database_transaction_rollback(test_db):
    """Scenario 9: Simulated DB error rolls back transaction and logs FAILED run."""
    service = GDELTIngestionService(db=test_db)

    # Patch save_or_update_gdelt_article to trigger an error
    with patch.object(
        service.repo, "save_or_update_gdelt_article", side_effect=RuntimeError("Simulated DB Write Error")
    ):
        summary = service.ingest_articles([SAMPLE_ARTICLE_1], raise_on_error=False)

    assert summary.status == "FAILED"
    assert "Simulated DB Write Error" in summary.error_message
    assert summary.inserted_count == 0

    # Verify no corrupted records in DB
    retrieval = GDELTRetrievalService(db=test_db)
    assert retrieval.count_articles() == 0

    # Verify run logged in gdelt_ingestion_runs as FAILED
    runs = retrieval.get_latest_ingestion_runs()
    assert len(runs) == 1
    assert runs[0].status == "FAILED"
    assert "Simulated DB Write Error" in runs[0].error_message


# =============================================================================
# Test 10: Updating Existing Article Metadata Without Overwriting with Null
# =============================================================================
def test_updating_existing_article_metadata(test_db):
    """Scenario 10: Existing article data is not overwritten with null values upon re-ingestion."""
    service = GDELTIngestionService(db=test_db)

    # Initial ingest with full details
    service.ingest_articles([SAMPLE_ARTICLE_1])

    retrieval = GDELTRetrievalService(db=test_db)
    art_before = retrieval.list_articles()[0]
    orig_title = art_before.title
    orig_domain = art_before.source_domain
    orig_country = art_before.source_country

    # Re-ingest same article with null/omitted fields
    re_ingest_sparse = {
        "url": SAMPLE_ARTICLE_1["url"],
        "title": None,
        "domain": None,
        "sourcecountry": None,
    }
    service.ingest_articles([re_ingest_sparse])

    art_after = retrieval.list_articles()[0]
    assert art_after.title == orig_title
    assert art_after.source_domain == orig_domain
    assert art_after.source_country == orig_country


# =============================================================================
# Test 11: Preserving First-Seen Timestamps While Updating Last-Seen Timestamps
# =============================================================================
def test_preserving_first_seen_timestamps(test_db):
    """Scenario 11: first_seen_at remains unchanged while last_seen_at updates on subsequent encounters."""
    service = GDELTIngestionService(db=test_db)

    # Ingest at T0
    service.ingest_articles([SAMPLE_ARTICLE_1])

    retrieval = GDELTRetrievalService(db=test_db)
    art1 = retrieval.list_articles()[0]
    initial_first_seen = art1.first_seen_at

    # Manually backdate first_seen_at to simulate time passage
    art1.first_seen_at = datetime.now(timezone.utc) - timedelta(days=2)
    art1.last_seen_at = art1.first_seen_at
    test_db.commit()

    saved_first_seen = art1.first_seen_at

    # Re-ingest at T1
    service.ingest_articles([SAMPLE_ARTICLE_1])

    art2 = retrieval.list_articles()[0]
    assert art2.first_seen_at == saved_first_seen
    assert art2.last_seen_at > saved_first_seen


# =============================================================================
# Test 12: Ingestion History Recording
# =============================================================================
def test_ingestion_history_recording(test_db):
    """Scenario 12: Every ingestion run writes detailed execution telemetry to gdelt_ingestion_runs."""
    service = GDELTIngestionService(db=test_db)

    sum1 = service.ingest_articles(
        [SAMPLE_ARTICLE_1, SAMPLE_ARTICLE_2],
        run_type="FIXTURE",
        category="mining_strikes",
        lookback_window="24h",
    )

    retrieval = GDELTRetrievalService(db=test_db)
    runs = retrieval.get_latest_ingestion_runs()
    assert len(runs) >= 1

    r = runs[0]
    assert r.id == sum1.run_id
    assert r.run_type == "FIXTURE"
    assert r.status == "COMPLETED"
    assert r.query_category == "mining_strikes"
    assert r.lookback_window == "24h"
    assert r.fetched_count == 2
    assert r.valid_count == 2
    assert r.inserted_count == 2
    assert r.duplicate_count == 0
    assert r.failed_count == 0
    assert r.started_at is not None
    assert r.completed_at is not None
    assert r.error_message is None


# =============================================================================
# Test 13: Retrieval of Pending Articles and Category Queries
# =============================================================================
def test_retrieval_of_pending_articles(test_db):
    """Scenario 13: GDELTRetrievalService filters by pending classification, categories, and pagination."""
    service = GDELTIngestionService(db=test_db)
    service.ingest_articles([SAMPLE_ARTICLE_1], category="trade_restrictions")
    service.ingest_articles([SAMPLE_ARTICLE_2], category="mining_strikes")

    retrieval = GDELTRetrievalService(db=test_db)

    # 1. Pending articles queue
    pending = retrieval.get_pending_articles()
    assert len(pending) == 2
    assert all(a.classification_status == "pending" for a in pending)

    # 2. Filter by category
    strikes = retrieval.list_articles(category="mining_strikes")
    assert len(strikes) == 1
    assert strikes[0].title == SAMPLE_ARTICLE_2["title"]

    restrictions = retrieval.list_articles(category="trade_restrictions")
    assert len(restrictions) == 1
    assert restrictions[0].title == SAMPLE_ARTICLE_1["title"]

    # 3. Pagination
    paged = retrieval.list_articles(limit=1, offset=0)
    assert len(paged) == 1


# =============================================================================
# Test 14: Empty API Results Handling
# =============================================================================
def test_empty_api_results(test_db):
    """Scenario 14: An empty response from GDELT completes cleanly with 0 inserts and COMPLETED status."""
    mock_client = MagicMock(spec=GdeltClient)
    mock_client.fetch_articles.return_value = {"articles": []}

    service = GDELTIngestionService(db=test_db, client=mock_client)
    summary = service.ingest_from_live(category=GeopoliticalCategory.PORT_CLOSURES)

    assert summary.status == "COMPLETED"
    assert summary.fetched_count == 0
    assert summary.inserted_count == 0
    assert summary.duplicate_count == 0
    assert summary.failed_count == 0
    assert summary.error_message is None


# =============================================================================
# Test 15: Provider Outage / Error Handling
# =============================================================================
def test_provider_outage_error_handling(test_db):
    """Scenario 15: Network errors or rate limit errors record FAILED run without throwing unhandled exceptions."""
    mock_client = MagicMock(spec=GdeltClient)
    mock_client.fetch_articles.side_effect = GdeltRateLimitError("GDELT HTTP 429: Too Many Requests")

    service = GDELTIngestionService(db=test_db, client=mock_client)
    summary = service.ingest_from_live(category=GeopoliticalCategory.ARMED_CONFLICT, raise_on_error=False)

    assert summary.status == "FAILED"
    assert "429" in summary.error_message

    retrieval = GDELTRetrievalService(db=test_db)
    runs = retrieval.get_latest_ingestion_runs()
    assert len(runs) == 1
    assert runs[0].status == "FAILED"
    assert "429" in runs[0].error_message


# =============================================================================
# Test 16: Existing Model 1 Data Preservation
# =============================================================================
def test_existing_model1_data_preservation(test_db):
    """Scenario 16: Model 1 trade and risk analysis tables remain completely intact and unaffected."""
    # 1. Populate a Model 1 NormalizedTradeRecord
    trade_record = NormalizedTradeRecord(
        record_hash="test_trade_hash_12345",
        commodity_code="284440",
        mineral_type="Cobalt",
        flow_type="IMPORT",
        reporter_country_code="USA",
        reporter_country_name="United States",
        partner_country_code="COD",
        partner_country_name="Democratic Republic of the Congo",
        period="2024",
        period_year=2024,
        trade_value_usd=500000.0,
        currency="USD",
        retrieval_timestamp=utc_now(),
    )
    test_db.add(trade_record)

    # 2. Populate a Model 1 RiskAnalysis
    risk_analysis = RiskAnalysis(
        analysis_id="analysis_m1_test_999",
        commodity_code="284440",
        reporter_country_code="USA",
        partner_country_code="COD",
        period="2024",
        combined_anomaly_score=68.5,
        score_completeness="COMPLETE",
        evaluated_rules='["R1","R2","R3","R4","R5"]',
        insufficient_rules="[]",
        flagged_rules='["R1"]',
    )
    test_db.add(risk_analysis)
    test_db.commit()

    # 3. Perform Model 2 GDELT Ingestion
    service = GDELTIngestionService(db=test_db)
    service.ingest_articles([SAMPLE_ARTICLE_1, SAMPLE_ARTICLE_2], category="mining_strikes")

    # 4. Verify Model 1 tables were NOT altered or corrupted
    trade_count = test_db.query(NormalizedTradeRecord).count()
    risk_count = test_db.query(RiskAnalysis).count()

    assert trade_count == 1
    assert risk_count == 1

    stored_trade = test_db.query(NormalizedTradeRecord).first()
    assert stored_trade.record_hash == "test_trade_hash_12345"
    assert stored_trade.trade_value_usd == 500000.0

    stored_risk = test_db.query(RiskAnalysis).first()
    assert stored_risk.analysis_id == "analysis_m1_test_999"
    assert stored_risk.combined_anomaly_score == 68.5
