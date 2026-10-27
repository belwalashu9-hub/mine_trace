"""Geopolitical news fetching and normalization service (Model 2 Phase 1)."""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.core.config import get_settings
from app.core.logging import logger
from app.schemas.geopolitical import (
    GeopoliticalCategory,
    CriticalMineral,
    NormalizedGeopoliticalEvent,
    GDELTFetchResponse,
)
from app.geopolitical.gdelt_client import (
    GdeltClient,
    GdeltError,
    GdeltRateLimitError,
    GdeltTimeoutError,
    GdeltConnectionError,
)
from app.geopolitical.queries import (
    build_category_query,
    build_critical_minerals_disruption_query,
    convert_hours_to_timespan,
)
from app.geopolitical.normalizer import normalize_gdelt_article

settings = get_settings()


class GeopoliticalService:
    """
    Service coordinating GDELT DOC 2.0 API data retrieval, category-targeted queries,
    and event normalization for critical mineral supply chain risk monitoring.
    """

    def __init__(self, client: Optional[GdeltClient] = None):
        self.client = client or GdeltClient()

    def fetch_geopolitical_events(
        self,
        category: Optional[GeopoliticalCategory] = None,
        mineral: Optional[CriticalMineral] = None,
        custom_query: Optional[str] = None,
        lookback_hours: Optional[int] = None,
        max_records: int = 75,
        enforce_pacing: bool = True,
        raise_on_error: bool = False,
    ) -> GDELTFetchResponse:
        """
        Retrieves and normalizes recent geopolitical events from GDELT.

        Parameters:
            category: GeopoliticalCategory enum (e.g. MINING_STRIKES, PORT_CLOSURES)
            mineral: CriticalMineral enum (e.g. LITHIUM, COBALT)
            custom_query: Raw custom GDELT query string (overrides category/mineral)
            lookback_hours: Window in hours (defaults to settings.gdelt_lookback_hours)
            max_records: Maximum articles to fetch (clamped 1-250)
            enforce_pacing: Enforce polite request delay between consecutive queries
            raise_on_error: If True, re-raises GdeltError; if False, returns safe response with warning

        Returns:
            GDELTFetchResponse containing normalized events and operation statistics.
        """
        hours = lookback_hours if lookback_hours is not None else settings.gdelt_lookback_hours
        timespan = convert_hours_to_timespan(hours)

        if custom_query and custom_query.strip():
            query_str = custom_query.strip()
        elif category:
            query_str = build_category_query(category=category, mineral=mineral)
        else:
            query_str = build_critical_minerals_disruption_query(mineral=mineral)

        retrieval_dt = datetime.now(timezone.utc)
        retrieval_iso = retrieval_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            f"GeopoliticalService: fetching news for query='{query_str[:60]}...' "
            f"timespan={timespan} max_records={max_records}"
        )

        try:
            raw_result = self.client.fetch_articles(
                query=query_str,
                timespan=timespan,
                max_records=max_records,
                enforce_pacing=enforce_pacing,
            )
            raw_articles = raw_result.get("articles", [])
        except (GdeltRateLimitError, GdeltTimeoutError, GdeltConnectionError, GdeltError) as exc:
            logger.error(f"GeopoliticalService: GDELT query failed gracefully: {exc}")
            if raise_on_error:
                raise
            return GDELTFetchResponse(
                query=query_str,
                timespan=timespan,
                total_retrieved=0,
                valid_articles_count=0,
                retrieved_at=retrieval_iso,
                provider="gdelt_doc_2",
                events=[],
                warning=f"GDELT retrieval warning: {exc}",
            )

        # Normalize articles and deduplicate by stable event_id
        normalized_events: List[NormalizedGeopoliticalEvent] = []
        seen_event_ids = set()

        for raw_item in raw_articles:
            event = normalize_gdelt_article(raw_item, retrieved_at=retrieval_dt)
            if event is not None and event.event_id not in seen_event_ids:
                seen_event_ids.add(event.event_id)
                normalized_events.append(event)

        logger.info(
            f"GeopoliticalService: normalized {len(normalized_events)} valid events "
            f"from {len(raw_articles)} raw GDELT records."
        )

        return GDELTFetchResponse(
            query=query_str,
            timespan=timespan,
            total_retrieved=len(raw_articles),
            valid_articles_count=len(normalized_events),
            retrieved_at=retrieval_iso,
            provider="gdelt_doc_2",
            events=normalized_events,
            warning=None,
        )

    def load_from_fixture(self, fixture_path: str) -> GDELTFetchResponse:
        """
        Loads and normalizes articles from a local synthetic JSON fixture.
        Provides deterministic, offline verification without network access.
        """
        retrieval_dt = datetime.now(timezone.utc)
        retrieval_iso = retrieval_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        raw_result = self.client.load_from_fixture(fixture_path)
        raw_articles = raw_result.get("articles", [])

        normalized_events: List[NormalizedGeopoliticalEvent] = []
        seen_event_ids = set()

        for raw_item in raw_articles:
            event = normalize_gdelt_article(raw_item, retrieved_at=retrieval_dt)
            if event is not None and event.event_id not in seen_event_ids:
                seen_event_ids.add(event.event_id)
                normalized_events.append(event)

        logger.info(
            f"GeopoliticalService: loaded {len(normalized_events)} valid events "
            f"from fixture '{fixture_path}' ({len(raw_articles)} raw records)."
        )

        return GDELTFetchResponse(
            query=f"fixture:{fixture_path}",
            timespan="offline",
            total_retrieved=len(raw_articles),
            valid_articles_count=len(normalized_events),
            retrieved_at=retrieval_iso,
            provider="gdelt_doc_2",
            events=normalized_events,
            warning=None,
        )
