"""
GDELT News Retrieval Service (Model 2 Phase 2).

Provides query interfaces for stored news articles, category associations,
and pending event queues for future Phase 3 classification.
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.database.models import GdeltArticle, GdeltArticleCategory, GdeltIngestionRun
from app.database.repository import MineTraceRepository


class GDELTRetrievalService:
    """
    Data retrieval service for accessing ingested GDELT geopolitical news records.
    Provides filtering by status, category, provider, and ingestion date range.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = MineTraceRepository(db)

    def get_article_by_event_id(self, event_id: str) -> Optional[GdeltArticle]:
        """Retrieves a single article by its deterministic stable event_id."""
        return self.repo.get_gdelt_article_by_event_id(event_id)

    def get_article_by_canonical_url(self, canonical_url: str) -> Optional[GdeltArticle]:
        """Retrieves a single article by its normalized canonical URL."""
        return self.repo.get_gdelt_article_by_canonical_url(canonical_url)

    def list_articles(
        self,
        category: Optional[str] = None,
        classification_status: Optional[str] = None,
        provider: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[GdeltArticle]:
        """
        Retrieves paginated list of GDELT articles matching criteria.
        Safe bounded query with pagination limits.
        """
        clamped_limit = max(1, min(limit, 250))
        return self.repo.list_gdelt_articles(
            category=category,
            classification_status=classification_status,
            provider=provider,
            from_date=from_date,
            to_date=to_date,
            limit=clamped_limit,
            offset=max(0, offset),
        )

    def count_articles(
        self,
        category: Optional[str] = None,
        classification_status: Optional[str] = None,
        provider: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> int:
        """Counts total distinct articles matching filter criteria."""
        return self.repo.count_gdelt_articles(
            category=category,
            classification_status=classification_status,
            provider=provider,
            from_date=from_date,
            to_date=to_date,
        )

    def get_pending_articles(
        self,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[GdeltArticle]:
        """
        Retrieves articles queued for Phase 3 event classification (classification_status='pending').
        """
        return self.list_articles(
            category=category,
            classification_status="pending",
            limit=limit,
            offset=offset,
        )

    def get_article_categories(self, article_id: int) -> List[str]:
        """Returns all query categories associated with an article."""
        records = (
            self.db.query(GdeltArticleCategory)
            .filter(GdeltArticleCategory.article_id == article_id)
            .all()
        )
        return [r.category for r in records]

    def get_latest_ingestion_runs(self, limit: int = 10) -> List[GdeltIngestionRun]:
        """Returns the most recent GDELT ingestion run audit records."""
        return self.repo.get_latest_gdelt_ingestion_runs(limit=limit)
