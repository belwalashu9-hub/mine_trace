"""Unit tests for Model 2 Phase 1: GDELT DOC 2.0 API Client, Queries, Normalizer, and Service."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
import pytest

from app.geopolitical.gdelt_client import (
    GdeltClient,
    PoliteRateLimiter,
    GdeltError,
    GdeltAPIError,
    GdeltRateLimitError,
    GdeltTimeoutError,
    GdeltConnectionError,
    GdeltParseError,
)
from app.geopolitical.queries import (
    CATEGORY_QUERIES,
    MINERAL_QUERIES,
    build_category_query,
    build_critical_minerals_disruption_query,
    convert_hours_to_timespan,
)
from app.geopolitical.normalizer import (
    canonicalize_url,
    generate_event_id,
    parse_gdelt_seendate,
    extract_source_domain,
    normalize_gdelt_article,
)
from app.geopolitical.service import GeopoliticalService
from app.schemas.geopolitical import GeopoliticalCategory, CriticalMineral


@pytest.fixture
def fast_rate_limiter():
    """Provides a zero-delay rate limiter for fast offline unit tests."""
    return PoliteRateLimiter(min_interval_seconds=0.0)


@pytest.fixture
def gdelt_client(fast_rate_limiter):
    """Provides test GdeltClient with 0 retries and zero rate-limiting delay."""
    return GdeltClient(
        base_url="https://api.gdeltproject.org/api/v2/doc/doc",
        timeout=5.0,
        max_retries=0,
        rate_limiter=fast_rate_limiter,
    )


@pytest.fixture
def gdelt_fixture_path(fixtures_dir) -> str:
    return str(fixtures_dir / "gdelt_sample.json")


# -------------------------------------------------------------
# 1. Successful API Response
# -------------------------------------------------------------
def test_gdelt_successful_response(gdelt_client):
    """Verify that a standard GDELT 200 JSON response is parsed into raw articles."""
    mock_payload = {
        "articles": [
            {
                "url": "https://example.com/mining-news",
                "title": "Lithium Producer Expands Extraction",
                "seendate": "20261027T100000Z",
                "domain": "example.com",
                "sourcecountry": "Chile",
            }
        ]
    }
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, json=mock_payload)
        res = gdelt_client.fetch_articles(query="lithium mining", timespan="24h", max_records=10)

    assert res["status_code"] == 200
    assert len(res["articles"]) == 1
    assert res["articles"][0]["title"] == "Lithium Producer Expands Extraction"


# -------------------------------------------------------------
# 2. Empty Results Handling
# -------------------------------------------------------------
def test_gdelt_empty_results(gdelt_client):
    """Verify that empty GDELT responses (empty list, empty body, or no-match text) return []."""
    # Case A: {"articles": []}
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, json={"articles": []})
        res = gdelt_client.fetch_articles(query="nonexistent term")
    assert res["articles"] == []

    # Case B: Empty text body
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, text="")
        res = gdelt_client.fetch_articles(query="nonexistent term")
    assert res["articles"] == []

    # Case C: GDELT plain text 'no matches' message
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, text="Your search yielded no matches.")
        res = gdelt_client.fetch_articles(query="nonexistent term")
    assert res["articles"] == []


# -------------------------------------------------------------
# 3. Timeout Handling
# -------------------------------------------------------------
def test_gdelt_timeout_handling(gdelt_client):
    """Verify that request timeout triggers GdeltTimeoutError."""
    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
        with pytest.raises(GdeltTimeoutError) as exc_info:
            gdelt_client.fetch_articles(query="cobalt war")
        assert "timed out" in str(exc_info.value).lower()


# -------------------------------------------------------------
# 4. HTTP 429 Rate Limiting
# -------------------------------------------------------------
def test_gdelt_rate_limiting_429(fast_rate_limiter):
    """Verify that HTTP 429 or rate-limit notice raises GdeltRateLimitError."""
    client = GdeltClient(max_retries=1, rate_limiter=fast_rate_limiter)
    rate_limit_text = "Please limit requests to one every 5 seconds or contact support."

    with patch("time.sleep"):  # Mock backoff sleep for test speed
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value = httpx.Response(429, text=rate_limit_text)
            with pytest.raises(GdeltRateLimitError) as exc_info:
                client.fetch_articles(query="nickel strike")
            assert exc_info.value.status_code == 429


# -------------------------------------------------------------
# 5. HTTP 5xx Server Errors
# -------------------------------------------------------------
def test_gdelt_server_error_500(fast_rate_limiter):
    """Verify that HTTP 500 or 503 raises GdeltAPIError with status code."""
    client = GdeltClient(max_retries=0, rate_limiter=fast_rate_limiter)
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(503, text="Service Unavailable")
        with pytest.raises(GdeltAPIError) as exc_info:
            client.fetch_articles(query="graphite port")
        assert exc_info.value.status_code == 503


# -------------------------------------------------------------
# 6. Invalid JSON Handling
# -------------------------------------------------------------
def test_gdelt_invalid_json(gdelt_client):
    """Verify that unparseable HTML/corrupt text raises GdeltParseError."""
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, text="<html><body>Internal Gateway Error</body></html>")
        with pytest.raises(GdeltParseError) as exc_info:
            gdelt_client.fetch_articles(query="lithium")
        assert "failed to parse gdelt json" in str(exc_info.value).lower()


# -------------------------------------------------------------
# 7. Missing Article Fields Handling
# -------------------------------------------------------------
def test_normalizer_missing_fields():
    """Verify that articles with missing non-essential fields are handled gracefully."""
    # Completely empty record should be rejected
    assert normalize_gdelt_article({}) is None

    # Minimal record with only headline and URL
    raw = {"url": "https://news.org/minerals", "title": "Headline Only"}
    event = normalize_gdelt_article(raw)
    assert event is not None
    assert event.title == "Headline Only"
    assert event.source_domain == "news.org"
    assert event.source_country is None
    assert event.affected_country is None
    assert event.mineral is None
    assert event.event_type is None
    assert event.event_date is None
    assert event.publication_date is None
    assert event.gdelt_seen_date is None
    assert event.classification_status == "pending"
    assert event.provider == "gdelt_doc_2"


# -------------------------------------------------------------
# 8. Network Connection Failure
# -------------------------------------------------------------
def test_gdelt_network_connection_failure(gdelt_client):
    """Verify that DNS / network connection failure raises GdeltConnectionError."""
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("DNS resolution failed")):
        with pytest.raises(GdeltConnectionError) as exc_info:
            gdelt_client.fetch_articles(query="lithium")
        assert "failed to connect" in str(exc_info.value).lower()


# -------------------------------------------------------------
# 9. Stable Article Identifier Generation
# -------------------------------------------------------------
def test_stable_event_id_generation():
    """
    Verify that identical URLs with tracking query parameters produce identical event_id,
    and different URLs produce distinct event_ids.
    """
    url_base = "https://example.com/mining/lithium-strike"
    url_with_tracking = "https://example.com/mining/lithium-strike?utm_source=twitter&ref=feed#sec1"
    url_uppercase = "HTTPS://WWW.EXAMPLE.COM/mining/lithium-strike/"

    id_base = generate_event_id(canonicalize_url(url_base))
    id_tracking = generate_event_id(canonicalize_url(url_with_tracking))
    id_upper = generate_event_id(canonicalize_url(url_uppercase))

    assert id_base == id_tracking, "Tracking query parameters must not alter canonical event_id"
    assert id_base == id_upper, "Scheme/domain casing and www prefix must not alter canonical event_id"

    id_different = generate_event_id(canonicalize_url("https://example.com/mining/cobalt-export-ban"))
    assert id_base != id_different, "Distinct articles must have distinct event_ids"
    assert id_base.startswith("evt_"), "Event ID must use the evt_ prefix"


# -------------------------------------------------------------
# 10. Date Normalization
# -------------------------------------------------------------
def test_date_normalization():
    """Verify parsing of GDELT seendate formats into standard ISO-8601 UTC."""
    # Format 1: YYYYMMDDTHHMMSSZ
    assert parse_gdelt_seendate("20260825T143000Z") == "2026-08-25T14:30:00Z"

    # Format 2: YYYYMMDDHHMMSS
    assert parse_gdelt_seendate("20260821160000") == "2026-08-21T16:00:00Z"

    # Format 3: Already valid ISO string
    assert parse_gdelt_seendate("2026-10-27T12:00:00Z") == "2026-10-27T12:00:00Z"

    # Format 4: Invalid date strings
    assert parse_gdelt_seendate("INVALID_DATE") is None
    assert parse_gdelt_seendate("") is None
    assert parse_gdelt_seendate(None) is None


# -------------------------------------------------------------
# 11. Category Query Builder Tests
# -------------------------------------------------------------
def test_all_9_category_queries():
    """Verify that all 9 geopolitical categories build valid GDELT queries."""
    for cat in GeopoliticalCategory:
        query = build_category_query(category=cat, mineral=CriticalMineral.LITHIUM)
        assert "lithium" in query
        assert len(query) > 20

    # Composite disruption query
    comp_query = build_critical_minerals_disruption_query()
    assert "cobalt" in comp_query
    assert "lithium" in comp_query
    assert "nickel" in comp_query
    assert "graphite" in comp_query


def test_convert_hours_to_timespan():
    """Verify lookback hours conversion to GDELT timespan shorthand."""
    assert convert_hours_to_timespan(12) == "12h"
    assert convert_hours_to_timespan(24) == "1d"
    assert convert_hours_to_timespan(48) == "2d"
    assert convert_hours_to_timespan(168) == "1w"


# -------------------------------------------------------------
# 12. GeopoliticalService and Fixture Loading
# -------------------------------------------------------------
def test_service_fixture_loading(gdelt_fixture_path):
    """Verify that GeopoliticalService loads and normalizes the synthetic test fixture."""
    service = GeopoliticalService()
    resp = service.load_from_fixture(gdelt_fixture_path)

    assert resp.total_retrieved == 7
    assert resp.valid_articles_count == 7
    assert resp.provider == "gdelt_doc_2"
    assert resp.warning is None

    # Check first normalized event
    ev0 = resp.events[0]
    assert ev0.event_id.startswith("evt_")
    assert "Lithium Carbonate" in ev0.title
    assert "example-mining-news.com" in ev0.source_domain
    assert ev0.source_country == "Chile"
    assert ev0.affected_country is None  # Preserved as null in Phase 1
    assert ev0.mineral is None           # Preserved as null in Phase 1
    assert ev0.event_type is None        # Preserved as null in Phase 1
    assert ev0.event_date is None        # Preserved as null in Phase 1
    assert ev0.gdelt_seen_date == "2026-08-25T14:30:00Z"
    assert ev0.classification_status == "pending"


def test_service_graceful_error_handling(fast_rate_limiter):
    """Verify that GeopoliticalService returns a safe response without crashing on API error."""
    client = GdeltClient(max_retries=0, rate_limiter=fast_rate_limiter)
    service = GeopoliticalService(client=client)

    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Network Down")):
        resp = service.fetch_geopolitical_events(
            category=GeopoliticalCategory.MINING_STRIKES,
            raise_on_error=False,
        )

    assert resp.total_retrieved == 0
    assert resp.valid_articles_count == 0
    assert resp.events == []
    assert resp.warning is not None
    assert "failed to connect" in resp.warning.lower()
