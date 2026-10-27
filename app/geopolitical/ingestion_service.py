"""
GDELT News Ingestion Service (Model 2 Phase 2).

Orchestrates article retrieval, normalization, SQLite persistence,
deduplication, category association, and ingestion audit logging.
"""
from datetime import datetime, timezone
import json
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import utc_now, GdeltArticle, GdeltArticleCategory, GdeltIngestionRun
from app.database.repository import MineTraceRepository
from app.geopolitical.gdelt_client import (
    GdeltClient,
    GdeltError,
    GdeltRateLimitError,
    GdeltTimeoutError,
    GdeltConnectionError,
    GdeltAPIError,
)
from app.geopolitical.queries import (
    build_category_query,
    build_critical_minerals_disruption_query,
    convert_hours_to_timespan,
)
from app.geopolitical.normalizer import normalize_gdelt_article
from app.geopolitical.service import GeopoliticalService
from app.schemas.geopolitical import (
    GeopoliticalCategory,
    CriticalMineral,
    NormalizedGeopoliticalEvent,
    GDELTIngestionSummary,
)

settings = get_settings()


class GDELTIngestionService:
    """
    Coordinates GDELT DOC 2.0 article ingestion into SQLite.
    Guarantees idempotency, preserves search categories across queries,
    tracks ingestion run metrics, and enforces transactional safety.
    """

    def __init__(
        self,
        db: Session,
        client: Optional[GdeltClient] = None,
        service: Optional[GeopoliticalService] = None,
    ):
        self.db = db
        self.repo = MineTraceRepository(db)
        self.service = service or GeopoliticalService(client=client)
        self.client = self.service.client

    def ingest_articles(
        self,
        raw_articles: List[Dict[str, Any]],
        run_type: str = "LIVE",
        category: Optional[str] = None,
        query_string: Optional[str] = None,
        lookback_window: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> GDELTIngestionSummary:
        """
        Processes and persists a list of raw GDELT article dicts within an isolated transaction.
        Handles normalization, deduplication, category mapping, and audit logging.
        """
        cat_str = category.value if isinstance(category, GeopoliticalCategory) else (str(category) if category else None)

        # 1. Create Ingestion Run record in RUNNING status
        run = self.repo.create_gdelt_ingestion_run(
            run_type=run_type,
            query_category=cat_str,
            query_string=query_string,
            lookback_window=lookback_window,
        )

        fetched_count = len(raw_articles)
        valid_count = 0
        failed_count = 0
        inserted_count = 0
        updated_count = 0
        duplicate_count = 0
        now_dt = utc_now()

        try:
            for raw_item in raw_articles:
                event = normalize_gdelt_article(raw_item, retrieved_at=now_dt)
                if event is None:
                    failed_count += 1
                    continue

                valid_count += 1
                event_dict = event.model_dump()
                if run_type == "FIXTURE": event_dict["provider"] = "synthetic_fixture"
                article, action = self.repo.save_or_update_gdelt_article(
                    event_dict=event_dict,
                    category=cat_str,
                )

                if action == "inserted":
                    inserted_count += 1
                elif action == "duplicate":
                    duplicate_count += 1
                    updated_count += 1

            self.db.commit()

            status = "COMPLETED"
            if failed_count > 0 and (inserted_count > 0 or duplicate_count > 0):
                status = "PARTIAL"
            elif failed_count > 0 and inserted_count == 0 and duplicate_count == 0 and fetched_count > 0:
                status = "FAILED"

            self.repo.finish_gdelt_ingestion_run(
                run_id=run.id,
                status=status,
                fetched_count=fetched_count,
                valid_count=valid_count,
                inserted_count=inserted_count,
                updated_count=updated_count,
                duplicate_count=duplicate_count,
                failed_count=failed_count,
            )

            logger.info(
                f"GDELTIngestionService: Run {run.id} finished with status={status} "
                f"(fetched={fetched_count}, valid={valid_count}, inserted={inserted_count}, "
                f"updated={updated_count}, duplicate={duplicate_count}, failed={failed_count})"
            )

            return GDELTIngestionSummary(
                run_id=run.id,
                status=status,
                provider="gdelt_doc_2",
                query_category=cat_str,
                lookback_window=lookback_window,
                fetched_count=fetched_count,
                valid_count=valid_count,
                inserted_count=inserted_count,
                updated_count=updated_count,
                duplicate_count=duplicate_count,
                failed_count=failed_count,
                error_message=None,
            )

        except Exception as exc:
            self.db.rollback()
            logger.error(f"GDELTIngestionService: Run {run.id} transaction failed: {exc}", exc_info=True)
            self.repo.finish_gdelt_ingestion_run(
                run_id=run.id,
                status="FAILED",
                fetched_count=fetched_count,
                valid_count=valid_count,
                inserted_count=0,
                updated_count=0,
                duplicate_count=0,
                failed_count=fetched_count,
                error_message=str(exc),
            )
            if raise_on_error:
                raise
            return GDELTIngestionSummary(
                run_id=run.id,
                status="FAILED",
                provider="gdelt_doc_2",
                query_category=cat_str,
                lookback_window=lookback_window,
                fetched_count=fetched_count,
                valid_count=valid_count,
                inserted_count=0,
                updated_count=0,
                duplicate_count=0,
                failed_count=fetched_count,
                error_message=str(exc),
            )

    def ingest_from_live(
        self,
        category: Optional[Union[GeopoliticalCategory, str]] = None,
        mineral: Optional[Union[CriticalMineral, str]] = None,
        custom_query: Optional[str] = None,
        lookback_hours: Optional[int] = None,
        max_records: int = 75,
        enforce_pacing: bool = True,
        raise_on_error: bool = False,
    ) -> GDELTIngestionSummary:
        """
        Executes a live query against GDELT DOC 2.0 API, parses responses,
        and persists them into the SQLite database.
        """
        hours = lookback_hours if lookback_hours is not None else settings.gdelt_lookback_hours
        timespan = convert_hours_to_timespan(hours)

        cat_enum = GeopoliticalCategory(category) if isinstance(category, str) and category in [c.value for c in GeopoliticalCategory] else (category if isinstance(category, GeopoliticalCategory) else None)
        mineral_enum = CriticalMineral(mineral) if isinstance(mineral, str) and mineral in [m.value for m in CriticalMineral] else (mineral if isinstance(mineral, CriticalMineral) else None)
        cat_str = cat_enum.value if cat_enum else (str(category) if category else None)

        if custom_query and custom_query.strip():
            query_str = custom_query.strip()
        elif cat_enum:
            query_str = build_category_query(category=cat_enum, mineral=mineral_enum)
        else:
            query_str = build_critical_minerals_disruption_query(mineral=mineral_enum)

        try:
            raw_result = self.client.fetch_articles(
                query=query_str,
                timespan=timespan,
                max_records=max_records,
                enforce_pacing=enforce_pacing,
            )
            raw_articles = raw_result.get("articles", [])
        except (GdeltRateLimitError, GdeltTimeoutError, GdeltConnectionError, GdeltAPIError, GdeltError, Exception) as exc:
            logger.error(f"GDELTIngestionService: Live fetch failed: {exc}")
            run = self.repo.create_gdelt_ingestion_run(
                run_type="LIVE",
                query_category=cat_str,
                query_string=query_str,
                lookback_window=timespan,
            )
            self.repo.finish_gdelt_ingestion_run(
                run_id=run.id,
                status="FAILED",
                fetched_count=0,
                valid_count=0,
                inserted_count=0,
                updated_count=0,
                duplicate_count=0,
                failed_count=0,
                error_message=str(exc),
            )
            if raise_on_error:
                raise
            return GDELTIngestionSummary(
                run_id=run.id,
                status="FAILED",
                provider="gdelt_doc_2",
                query_category=cat_str,
                lookback_window=timespan,
                fetched_count=0,
                valid_count=0,
                inserted_count=0,
                updated_count=0,
                duplicate_count=0,
                failed_count=0,
                error_message=str(exc),
            )

        return self.ingest_articles(
            raw_articles=raw_articles,
            run_type="LIVE",
            category=cat_str,
            query_string=query_str,
            lookback_window=timespan,
            raise_on_error=raise_on_error,
        )

    def ingest_from_fixture(
        self,
        fixture_path: str,
        category: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> GDELTIngestionSummary:
        """
        Ingests articles from a local synthetic JSON fixture file.
        Provides 100% deterministic, offline execution for unit testing and CI.
        """
        try:
            raw_result = self.client.load_from_fixture(fixture_path)
            raw_articles = raw_result.get("articles", [])
        except Exception as exc:
            logger.error(f"GDELTIngestionService: Failed to load fixture '{fixture_path}': {exc}")
            run = self.repo.create_gdelt_ingestion_run(
                run_type="FIXTURE",
                query_category=category,
                query_string=f"fixture:{fixture_path}",
                lookback_window="offline",
            )
            self.repo.finish_gdelt_ingestion_run(
                run_id=run.id,
                status="FAILED",
                fetched_count=0,
                valid_count=0,
                inserted_count=0,
                updated_count=0,
                duplicate_count=0,
                failed_count=0,
                error_message=str(exc),
            )
            if raise_on_error:
                raise
            return GDELTIngestionSummary(
                run_id=run.id,
                status="FAILED",
                provider="gdelt_doc_2",
                query_category=category,
                lookback_window="offline",
                fetched_count=0,
                valid_count=0,
                inserted_count=0,
                updated_count=0,
                duplicate_count=0,
                failed_count=0,
                error_message=str(exc),
            )

        return self.ingest_articles(
            raw_articles=raw_articles,
            run_type="FIXTURE",
            category=category,
            query_string=f"fixture:{fixture_path}",
            lookback_window="offline",
            raise_on_error=raise_on_error,
        )
