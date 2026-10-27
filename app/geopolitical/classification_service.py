"""
Event Classification and Clustering Service (Model 2 Phase 3).
Converts pending GDELT articles in SQLite into structured GeopoliticalEvent entities.
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database.models import (
    GdeltArticle,
    GeopoliticalEvent,
    EventArticleEvidence,
    EventClassificationHistory,
    utc_now,
)
from app.geopolitical.event_classifier import EventClassifier
from app.schemas.events import EventClassificationSummary, VerificationStatusEnum


class EventClassificationService:
    """
    Coordinates batch classification of pending GDELT articles into clustered GeopoliticalEvents.
    """

    def __init__(self, db: Session):
        self.db = db

    def process_pending_articles(self, limit: int = 100, include_synthetic: bool = False) -> EventClassificationSummary:
        """
        Fetches pending GDELT articles, classifies event types and locations,
        clusters duplicates into master GeopoliticalEvents, and links article evidence.
        """
        run_id = f"cls_{uuid.uuid4().hex[:12]}"

        # 1. Retrieve pending articles
        pending_articles = (
            self.db.query(GdeltArticle)
            .filter(GdeltArticle.classification_status == "pending")
            .filter(True if include_synthetic else GdeltArticle.provider != "synthetic_fixture")
            .limit(limit)
            .all()
        )

        articles_processed = len(pending_articles)
        events_extracted = 0
        events_clustered = 0

        if not pending_articles:
            history = EventClassificationHistory(
                run_id=run_id,
                articles_processed=0,
                events_extracted=0,
                events_clustered=0,
                method="DETERMINISTIC_RULES",
                status="COMPLETED",
            )
            self.db.add(history)
            self.db.commit()
            return EventClassificationSummary(
                run_id=run_id,
                status="COMPLETED",
                articles_processed=0,
                events_extracted=0,
                events_clustered=0,
                method="DETERMINISTIC_RULES",
                error_message=None,
            )

        try:
            for article in pending_articles:
                if not article.source_url or not article.title:
                    article.classification_status = "insufficient_metadata"
                    continue
                art_dict = {
                    "title": article.title,
                    "source_url": article.source_url,
                    "url": article.source_url,
                    "source_domain": article.source_domain,
                    "source_country": article.source_country,
                    "gdelt_seen_date": article.gdelt_seen_date,
                }

                classified = EventClassifier.classify_article(art_dict)
                if classified["event_type"] == "UNKNOWN":
                    article.classification_status = "irrelevant"
                    continue
                target_event_id = classified["event_id"]

                # Check if an event with this cluster event_id already exists
                existing_event = (
                    self.db.query(GeopoliticalEvent)
                    .filter(GeopoliticalEvent.event_id == target_event_id)
                    .first()
                )

                if existing_event:
                    # Cluster into existing event
                    existing_event.source_article_count += 1
                    existing_event.updated_at = utc_now()

                    # Upgrade verification to CORROBORATED if multiple supporting articles
                    # Syndicated or duplicate headlines are not independent corroboration.

                    # Link new article evidence
                    evidence = EventArticleEvidence(
                        event_id=existing_event.id,
                        article_id=article.id,
                        source_url=article.source_url,
                        article_title=article.title,
                        relevance_reason=f"Corroborating report for {existing_event.event_type}",
                    )
                    self.db.add(evidence)
                    events_clustered += 1
                else:
                    # Create new master GeopoliticalEvent
                    new_event = GeopoliticalEvent(
                        event_id=target_event_id,
                        event_type=classified["event_type"],
                        title=classified["title"],
                        summary=classified["summary"],
                        affected_country=classified["affected_country"],
                        region=classified["region"],
                        location_name=classified["location_name"],
                        latitude=classified["latitude"],
                        longitude=classified["longitude"],
                        has_coordinates=classified["has_coordinates"],
                        event_date=classified["event_date"],
                        publication_date=classified["publication_date"],
                        mineral_relevance=classified["mineral_relevance"],
                        relevance_type=classified["relevance_type"],
                        affected_infrastructure=classified["affected_infrastructure"],
                        extraction_confidence=classified["extraction_confidence"],
                        verification_status=classified["verification_status"],
                        source_article_count=1,
                        status="ACTIVE",
                    )
                    self.db.add(new_event)
                    self.db.flush()  # get new_event.id

                    # Link initial article evidence
                    evidence = EventArticleEvidence(
                        event_id=new_event.id,
                        article_id=article.id,
                        source_url=article.source_url,
                        article_title=article.title,
                        relevance_reason=f"Primary source reporting {new_event.event_type}",
                    )
                    self.db.add(evidence)
                    events_extracted += 1

                # Mark article as classified in SQLite
                article.classification_status = "classified"
                article.updated_at = utc_now()

            # Record history
            history = EventClassificationHistory(
                run_id=run_id,
                articles_processed=articles_processed,
                events_extracted=events_extracted,
                events_clustered=events_clustered,
                method="DETERMINISTIC_RULES",
                status="COMPLETED",
            )
            self.db.add(history)
            self.db.commit()

            logger.info(
                f"EventClassificationService: Processed {articles_processed} articles -> "
                f"{events_extracted} new events extracted, {events_clustered} clustered."
            )

            return EventClassificationSummary(
                run_id=run_id,
                status="COMPLETED",
                articles_processed=articles_processed,
                events_extracted=events_extracted,
                events_clustered=events_clustered,
                method="DETERMINISTIC_RULES",
            )

        except Exception as exc:
            self.db.rollback()
            logger.error(f"EventClassificationService: Batch classification failed: {exc}", exc_info=True)
            history = EventClassificationHistory(
                run_id=run_id,
                articles_processed=articles_processed,
                events_extracted=0,
                events_clustered=0,
                method="DETERMINISTIC_RULES",
                status="FAILED",
                error_message=str(exc),
            )
            self.db.add(history)
            self.db.commit()

            return EventClassificationSummary(
                run_id=run_id,
                status="FAILED",
                articles_processed=articles_processed,
                events_extracted=0,
                events_clustered=0,
                method="DETERMINISTIC_RULES",
                error_message=str(exc),
            )
