"""
Tests for Model 2 Phase 3: Geopolitical Event Classification & Entity Extraction.
"""
from datetime import datetime, timezone
import pytest

from app.database.models import (
    GdeltArticle,
    GeopoliticalEvent,
    EventArticleEvidence,
    EventClassificationHistory,
    NormalizedTradeRecord,
    utc_now,
)
from app.geopolitical.event_classifier import EventClassifier
from app.geopolitical.classification_service import EventClassificationService
from app.geopolitical.location_extractor import LocationExtractor
from app.geopolitical.mineral_detector import MineralDetector
from app.schemas.events import EventTypeEnum, VerificationStatusEnum


def test_event_type_classification():
    """Verify headline pattern matching maps to correct EventTypeEnum."""
    art1 = {"title": "Union Walkout Shuts Down Operations at Major Katanga Extraction Site"}
    res1 = EventClassifier.classify_article(art1)
    assert res1["event_type"] == EventTypeEnum.MINING_STRIKE.value

    art2 = {"title": "Port Berth Closure Delays Flake Graphite Shipments"}
    res2 = EventClassifier.classify_article(art2)
    assert res2["event_type"] == EventTypeEnum.PORT_CLOSURE.value

    art3 = {"title": "Government Imposes Strict Export Controls on Refined Lithium Carbonate"}
    res3 = EventClassifier.classify_article(art3)
    assert res3["event_type"] == EventTypeEnum.EXPORT_RESTRICTION.value

    art4 = {"title": "Treasury Imposes Secondary Sanctions on Illicit Critical Mineral Transshipment Ring"}
    res4 = EventClassifier.classify_article(art4)
    assert res4["event_type"] == EventTypeEnum.SANCTIONS_ANNOUNCEMENT.value

    art5 = {"title": "Cargo vessel struck by missile in southern Red Sea transit corridor"}
    res5 = EventClassifier.classify_article(art5)
    assert res5["event_type"] == EventTypeEnum.MARITIME_SECURITY_INCIDENT.value


def test_mineral_relevance_detection():
    """Verify direct vs indirect mineral relevance classification."""
    # Direct
    meta_direct = MineralDetector.detect_relevance(title="High-grade cobalt export quotas finalized")
    assert meta_direct["mineral"] == "cobalt"
    assert meta_direct["relevance_type"] == "DIRECT"

    # Indirect via recognized mining hub
    loc_meta = {"affected_infrastructure": "Kolwezi Mining District", "location_name": "Kolwezi"}
    meta_indirect = MineralDetector.detect_relevance(title="Road blockade outside Kolwezi slows transport", location_meta=loc_meta)
    assert meta_indirect["mineral"] == "cobalt"
    assert meta_indirect["relevance_type"] == "INDIRECT"

    # Irrelevant
    meta_none = MineralDetector.detect_relevance(title="Local football team wins championship")
    assert meta_none["mineral"] == "unknown"
    assert meta_none["relevance_type"] == "NONE"


def test_location_extraction_and_centroid_avoidance():
    """Verify country is detected but country centroids are NEVER assigned as coordinates."""
    # Case 1: Specific known infrastructure with verified coordinates
    loc1 = LocationExtractor.extract_location(title="Port of Durban container terminal halted amid power disruption")
    assert loc1["affected_country"] == "South Africa"
    assert loc1["has_coordinates"] is True
    assert loc1["latitude"] == pytest.approx(-29.8587, abs=0.01)
    assert loc1["longitude"] == pytest.approx(31.0218, abs=0.01)

    # Case 2: Country only mentioned -> MUST NOT invent centroid coordinates!
    loc2 = LocationExtractor.extract_location(title="Mining sector reforms proposed in Chile parliament")
    assert loc2["affected_country"] == "Chile"
    assert loc2["has_coordinates"] is False
    assert loc2["latitude"] is None
    assert loc2["longitude"] is None

    # Case 3: Source publisher country distinct from affected country
    loc3 = LocationExtractor.extract_location(
        title="Armed clashes disrupt transit along Mozambique border",
        source_country="United Kingdom",
    )
    assert loc3["affected_country"] == "Mozambique"  # Extracted from text, not publisher country


def test_different_headlines_not_automatically_corroborated(test_db):
    """Different reports in the same region are not automatically the same event."""
    now = utc_now()
    art1 = GdeltArticle(
        event_id="art_1_strike",
        title="Union Walkout Shuts Down Operations at Major Katanga Extraction Site",
        source_url="https://news-outlet-a.com/article1",
        canonical_url="https://news-outlet-a.com/article1",
        source_domain="news-outlet-a.com",
        source_country="United States",
        gdelt_seen_date=now,
        retrieved_at=now,
        classification_status="pending",
    )
    art2 = GdeltArticle(
        event_id="art_2_strike",
        title="Miners Strike Continues Across Katanga Cobalt Facilities",
        source_url="https://mining-monitor-b.org/strike-day-2",
        canonical_url="https://mining-monitor-b.org/strike-day-2",
        source_domain="mining-monitor-b.org",
        source_country="United Kingdom",
        gdelt_seen_date=now,
        retrieved_at=now,
        classification_status="pending",
    )
    test_db.add_all([art1, art2])
    test_db.commit()

    service = EventClassificationService(db=test_db)
    summary = service.process_pending_articles()

    assert summary.status == "COMPLETED"
    assert summary.articles_processed == 2
    assert summary.events_extracted == 2
    assert summary.events_clustered == 0

    # Verify single clustered event
    events = test_db.query(GeopoliticalEvent).all()
    assert len(events) == 2
    ev = events[0]
    assert ev.event_type == EventTypeEnum.MINING_STRIKE.value
    assert ev.source_article_count == 1
    assert ev.verification_status == VerificationStatusEnum.REPORTED.value

    # Verify both article evidence links are preserved
    evidence = test_db.query(EventArticleEvidence).all()
    assert len(evidence) == 2
    urls = [e.source_url for e in evidence]
    assert "https://news-outlet-a.com/article1" in urls
    assert "https://mining-monitor-b.org/strike-day-2" in urls

    # Verify articles marked as classified
    assert art1.classification_status == "classified"
    assert art2.classification_status == "classified"


def test_model1_data_preservation_during_event_classification(test_db):
    """Verify Model 1 data remains untouched during Phase 3 processing."""
    trade = NormalizedTradeRecord(
        record_hash="m1_trade_test_hash",
        commodity_code="284440",
        mineral_type="Cobalt",
        flow_type="IMPORT",
        reporter_country_code="USA",
        reporter_country_name="United States",
        partner_country_code="COD",
        partner_country_name="Democratic Republic of the Congo",
        period="2024",
        period_year=2024,
        trade_value_usd=100000.0,
        currency="USD",
        retrieval_timestamp=utc_now(),
    )
    test_db.add(trade)
    test_db.commit()

    # Run event classification
    service = EventClassificationService(db=test_db)
    service.process_pending_articles()

    # Verify Model 1 record preserved
    stored_trade = test_db.query(NormalizedTradeRecord).first()
    assert stored_trade is not None
    assert stored_trade.record_hash == "m1_trade_test_hash"
    assert stored_trade.trade_value_usd == 100000.0
