"""Repository pattern data access layer for MineTrace database operations."""
import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_

from app.database.models import (
    DataSourceMetadata,
    IngestionRun,
    RawTradeRecord,
    NormalizedTradeRecord,
    OfacSanctionRecord,
    DataQualityIssue,
    RiskAnalysis,
    RiskRuleResult,
    GdeltArticle,
    GdeltArticleCategory,
    GdeltIngestionRun,
    utc_now,
)


class MineTraceRepository:
    """Encapsulates all database query and persistence methods."""

    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------
    # Metadata & Ingestion Runs
    # -------------------------------------------------------------
    def get_or_create_data_source(self, source_name: str, source_url: str, description: str = None) -> DataSourceMetadata:
        source = self.db.query(DataSourceMetadata).filter(DataSourceMetadata.source_name == source_name).first()
        if not source:
            source = DataSourceMetadata(
                source_name=source_name,
                source_url=source_url,
                description=description,
                last_status="NEVER_RUN",
                total_records_ingested=0,
            )
            self.db.add(source)
            self.db.commit()
            self.db.refresh(source)
        return source

    def update_data_source_status(
        self,
        source_name: str,
        status: str,
        successful: bool,
        records_added: int = 0,
    ) -> Optional[DataSourceMetadata]:
        source = self.db.query(DataSourceMetadata).filter(DataSourceMetadata.source_name == source_name).first()
        if source:
            source.last_status = status
            source.last_attempt_timestamp = utc_now()
            if successful:
                source.last_successful_retrieval = utc_now()
                source.total_records_ingested += records_added
            self.db.commit()
            self.db.refresh(source)
        return source

    def create_ingestion_run(
        self,
        source_name: str,
        run_type: str = "MANUAL",
        parameters: str = None,
    ) -> IngestionRun:
        run = IngestionRun(
            source_name=source_name,
            run_type=run_type,
            status="RUNNING",
            parameters=parameters,
            started_at=utc_now(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def finish_ingestion_run(
        self,
        run_id: int,
        status: str,
        raw_count: int,
        clean_count: int,
        error_count: int,
        warning_count: int,
        error_message: Optional[str] = None,
    ) -> IngestionRun:
        run = self.db.query(IngestionRun).filter(IngestionRun.id == run_id).first()
        if run:
            run.status = status
            run.completed_at = utc_now()
            run.raw_records_count = raw_count
            run.clean_records_count = clean_count
            run.error_count = error_count
            run.warning_count = warning_count
            run.error_message = error_message
            self.db.commit()
            self.db.refresh(run)
        return run

    def log_quality_issue(
        self,
        table_name: str,
        severity: str,
        issue_type: str,
        message: str,
        ingestion_run_id: Optional[int] = None,
        source_record_id: Optional[str] = None,
        column_name: Optional[str] = None,
        raw_value: Optional[str] = None,
    ) -> DataQualityIssue:
        issue = DataQualityIssue(
            ingestion_run_id=ingestion_run_id,
            source_record_id=source_record_id,
            table_name=table_name,
            severity=severity,
            issue_type=issue_type,
            column_name=column_name,
            raw_value=str(raw_value)[:255] if raw_value is not None else None,
            message=message,
        )
        self.db.add(issue)
        self.db.commit()
        return issue

    # -------------------------------------------------------------
    # Trade Records (Raw & Normalized)
    # -------------------------------------------------------------
    def save_raw_trade_record(
        self,
        raw_payload: str,
        retrieval_timestamp: datetime,
        ingestion_run_id: Optional[int] = None,
        source_record_id: Optional[str] = None,
        commodity_code: Optional[str] = None,
        period: Optional[str] = None,
        reporter_code: Optional[str] = None,
        partner_code: Optional[str] = None,
    ) -> RawTradeRecord:
        record = RawTradeRecord(
            ingestion_run_id=ingestion_run_id,
            source_record_id=source_record_id,
            commodity_code=commodity_code,
            period=period,
            reporter_code=reporter_code,
            partner_code=partner_code,
            raw_payload=raw_payload,
            retrieval_timestamp=retrieval_timestamp,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_normalized_record_by_hash(self, record_hash: str) -> Optional[NormalizedTradeRecord]:
        return self.db.query(NormalizedTradeRecord).filter(NormalizedTradeRecord.record_hash == record_hash).first()

    def save_normalized_trade_record(self, record_dict: Dict[str, Any]) -> Tuple[NormalizedTradeRecord, bool]:
        """Saves a normalized trade record. Returns (record, is_created)."""
        existing = self.get_normalized_record_by_hash(record_dict["record_hash"])
        if existing:
            return existing, False

        record = NormalizedTradeRecord(**record_dict)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record, True

    def list_trade_records(
        self,
        skip: int = 0,
        limit: int = 50,
        commodity_code: Optional[str] = None,
        reporter_country_code: Optional[str] = None,
        partner_country_code: Optional[str] = None,
        flow_type: Optional[str] = None,
        period_year: Optional[int] = None,
    ) -> Tuple[List[NormalizedTradeRecord], int]:
        """Lists trade records with filtering and pagination. Returns (records, total_count)."""
        query = self.db.query(NormalizedTradeRecord)
        
        conditions = []
        if commodity_code:
            conditions.append(NormalizedTradeRecord.commodity_code == commodity_code.strip())
        if reporter_country_code:
            conditions.append(NormalizedTradeRecord.reporter_country_code == reporter_country_code.strip().upper())
        if partner_country_code:
            conditions.append(NormalizedTradeRecord.partner_country_code == partner_country_code.strip().upper())
        if flow_type:
            conditions.append(NormalizedTradeRecord.flow_type == flow_type.strip().upper())
        if period_year:
            conditions.append(NormalizedTradeRecord.period_year == period_year)

        if conditions:
            query = query.filter(and_(*conditions))

        total = query.count()
        records = query.order_by(desc(NormalizedTradeRecord.period_year), NormalizedTradeRecord.id).offset(skip).limit(limit).all()
        return records, total

    def get_distinct_minerals(self) -> List[Dict[str, Any]]:
        """Returns distinct commodity codes and mineral types present in the database."""
        results = (
            self.db.query(
                NormalizedTradeRecord.commodity_code,
                NormalizedTradeRecord.commodity_description,
                NormalizedTradeRecord.mineral_type,
                func.count(NormalizedTradeRecord.id).label("record_count"),
            )
            .group_by(
                NormalizedTradeRecord.commodity_code,
                NormalizedTradeRecord.commodity_description,
                NormalizedTradeRecord.mineral_type,
            )
            .all()
        )
        return [
            {
                "commodity_code": r[0],
                "description": r[1],
                "mineral_type": r[2],
                "record_count": r[3],
            }
            for r in results
        ]

    # -------------------------------------------------------------
    # OFAC Sanctions Records
    # -------------------------------------------------------------
    def get_ofac_record_by_hash(self, record_hash: str) -> Optional[OfacSanctionRecord]:
        return self.db.query(OfacSanctionRecord).filter(OfacSanctionRecord.record_hash == record_hash).first()

    def save_ofac_sanction_record(self, record_dict: Dict[str, Any]) -> Tuple[OfacSanctionRecord, bool]:
        """Saves an OFAC sanction record. Returns (record, is_created)."""
        existing = self.get_ofac_record_by_hash(record_dict["record_hash"])
        if existing:
            return existing, False

        record = OfacSanctionRecord(**record_dict)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record, True

    def list_sanctions_records(
        self,
        skip: int = 0,
        limit: int = 50,
        country: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Tuple[List[OfacSanctionRecord], int]:
        query = self.db.query(OfacSanctionRecord)
        if country:
            query = query.filter(OfacSanctionRecord.country.ilike(f"%{country.strip()}%"))
        if entity_type:
            query = query.filter(OfacSanctionRecord.entity_type == entity_type.strip().lower())
            
        total = query.count()
        records = query.order_by(OfacSanctionRecord.primary_name).offset(skip).limit(limit).all()
        return records, total

    # -------------------------------------------------------------
    # System Status & Health
    # -------------------------------------------------------------
    def get_system_status(self) -> Dict[str, Any]:
        """Aggregates data freshness, counts, and metadata for status endpoint."""
        sources = self.db.query(DataSourceMetadata).all()
        total_trade_records = self.db.query(NormalizedTradeRecord).count()
        total_sanctions_records = self.db.query(OfacSanctionRecord).count()
        total_raw_records = self.db.query(RawTradeRecord).count()
        total_quality_issues = self.db.query(DataQualityIssue).count()
        
        last_trade_retrieval = (
            self.db.query(func.max(NormalizedTradeRecord.retrieval_timestamp)).scalar()
        )
        last_sanctions_retrieval = (
            self.db.query(func.max(OfacSanctionRecord.retrieval_timestamp)).scalar()
        )

        counts_data = {
            "normalized_trade_records": total_trade_records,
            "raw_trade_records": total_raw_records,
            "sanctions_records": total_sanctions_records,
            "data_quality_issues": total_quality_issues,
        }

        return {
            "sources": [
                {
                    "source_name": s.source_name,
                    "source_url": s.source_url,
                    "last_status": s.last_status,
                    "last_successful_retrieval": s.last_successful_retrieval,
                    "last_attempt_timestamp": s.last_attempt_timestamp,
                    "total_records_ingested": s.total_records_ingested,
                }
                for s in sources
            ],
            "counts": counts_data,
            "record_counts": counts_data,
            "last_successful_retrieval": {
                "trade": last_trade_retrieval,
                "sanctions": last_sanctions_retrieval,
            },
        }

    # -------------------------------------------------------------
    # Phase 2: Risk Analyses & Rule Audits
    # -------------------------------------------------------------
    def get_risk_analysis_by_id(self, analysis_id: str) -> Optional[RiskAnalysis]:
        """Retrieves a single complete risk analysis with child rule results."""
        return (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.analysis_id == analysis_id.strip())
            .first()
        )

    def list_risk_analyses(
        self,
        skip: int = 0,
        limit: int = 50,
        commodity_code: Optional[str] = None,
        score_completeness: Optional[str] = None,
        min_score: Optional[float] = None,
        sanctions_status: Optional[str] = None,
    ) -> Tuple[List[RiskAnalysis], int]:
        """Retrieves paginated historical risk analyses without recalculation."""
        query = self.db.query(RiskAnalysis)
        conditions = []

        if commodity_code:
            conditions.append(RiskAnalysis.commodity_code == commodity_code.strip())
        if score_completeness:
            conditions.append(RiskAnalysis.score_completeness == score_completeness.strip().upper())
        if min_score is not None:
            conditions.append(RiskAnalysis.combined_anomaly_score >= min_score)
        if sanctions_status:
            conditions.append(RiskAnalysis.sanctions_status == sanctions_status.strip().upper())

        if conditions:
            query = query.filter(and_(*conditions))

        total = query.count()
        records = query.order_by(desc(RiskAnalysis.created_at), desc(RiskAnalysis.id)).offset(skip).limit(limit).all()
        return records, total

    def get_risk_summary(self) -> Dict[str, Any]:
        """Aggregates summary statistics across stored risk analyses."""
        total = self.db.query(RiskAnalysis).count()
        complete_count = (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.score_completeness == "COMPLETE")
            .count()
        )
        partial_count = (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.score_completeness == "PARTIAL")
            .count()
        )
        unavailable_count = (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.score_completeness == "UNAVAILABLE")
            .count()
        )
        avg_score = (
            self.db.query(func.avg(RiskAnalysis.combined_anomaly_score))
            .filter(RiskAnalysis.score_completeness != "UNAVAILABLE")
            .scalar()
        )

        # Flagged rule breakdown
        flagged_r1 = self.db.query(RiskRuleResult).filter(and_(RiskRuleResult.rule_id == "R1", RiskRuleResult.outcome == "FLAG")).count()
        flagged_r2 = self.db.query(RiskRuleResult).filter(and_(RiskRuleResult.rule_id == "R2", RiskRuleResult.outcome == "FLAG")).count()
        flagged_r3 = self.db.query(RiskRuleResult).filter(and_(RiskRuleResult.rule_id == "R3", RiskRuleResult.outcome == "FLAG")).count()
        flagged_r4 = self.db.query(RiskRuleResult).filter(and_(RiskRuleResult.rule_id == "R4", RiskRuleResult.outcome == "FLAG")).count()

        # Sanctions status breakdown
        sanctions_match = self.db.query(RiskAnalysis).filter(RiskAnalysis.sanctions_status == "REVIEW_MATCH").count()
        sanctions_no_match = self.db.query(RiskAnalysis).filter(RiskAnalysis.sanctions_status == "NO_IDENTIFIED_MATCH").count()
        sanctions_unknown = self.db.query(RiskAnalysis).filter(RiskAnalysis.sanctions_status == "UNKNOWN").count()

        return {
            "total_analyses": total,
            "complete_scores_count": complete_count,
            "partial_scores_count": partial_count,
            "unavailable_scores_count": unavailable_count,
            "average_anomaly_score": round(float(avg_score), 2) if avg_score is not None else None,
            "flagged_rules_breakdown": {
                "R1": flagged_r1,
                "R2": flagged_r2,
                "R3": flagged_r3,
                "R4": flagged_r4,
            },
            "sanctions_status_breakdown": {
                "REVIEW_MATCH": sanctions_match,
                "NO_IDENTIFIED_MATCH": sanctions_no_match,
                "UNKNOWN": sanctions_unknown,
            },
        }

    # -------------------------------------------------------------
    # Model 2: GDELT Geopolitical Ingestion & Queries
    # -------------------------------------------------------------
    def create_gdelt_ingestion_run(
        self,
        run_type: str = "LIVE",
        query_category: Optional[str] = None,
        query_string: Optional[str] = None,
        lookback_window: Optional[str] = None,
    ) -> GdeltIngestionRun:
        run = GdeltIngestionRun(
            run_type=run_type,
            status="RUNNING",
            query_category=query_category,
            query_string=query_string,
            lookback_window=lookback_window,
            started_at=utc_now(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def finish_gdelt_ingestion_run(
        self,
        run_id: int,
        status: str,
        fetched_count: int,
        valid_count: int,
        inserted_count: int,
        updated_count: int,
        duplicate_count: int,
        failed_count: int,
        error_message: Optional[str] = None,
    ) -> Optional[GdeltIngestionRun]:
        run = self.db.query(GdeltIngestionRun).filter(GdeltIngestionRun.id == run_id).first()
        if run:
            run.status = status
            run.completed_at = utc_now()
            run.fetched_count = fetched_count
            run.valid_count = valid_count
            run.inserted_count = inserted_count
            run.updated_count = updated_count
            run.duplicate_count = duplicate_count
            run.failed_count = failed_count
            run.error_message = error_message
            self.db.commit()
            self.db.refresh(run)
        return run

    def get_gdelt_article_by_event_id(self, event_id: str) -> Optional[GdeltArticle]:
        return self.db.query(GdeltArticle).filter(GdeltArticle.event_id == event_id).first()

    def get_gdelt_article_by_canonical_url(self, canonical_url: str) -> Optional[GdeltArticle]:
        return self.db.query(GdeltArticle).filter(GdeltArticle.canonical_url == canonical_url).first()

    def save_or_update_gdelt_article(
        self,
        event_dict: Dict[str, Any],
        category: Optional[str] = None,
    ) -> Tuple[GdeltArticle, str]:
        """
        Idempotently persists or updates a normalized GDELT article.
        - If new: creates GdeltArticle with first_seen_at=utc_now(), last_seen_at=utc_now().
        - If duplicate (matching event_id or canonical_url): updates last_seen_at=utc_now(),
          backfills missing non-null fields without overwriting existing data with null,
          and links new query category if not already associated.
        Returns:
            Tuple of (GdeltArticle, action_taken) where action_taken is 'inserted' or 'duplicate'.
        """
        event_id = event_dict.get("event_id")
        canonical_url = event_dict.get("canonical_url") or event_dict.get("source_url")

        existing = None
        if event_id:
            existing = self.get_gdelt_article_by_event_id(event_id)
        if not existing and canonical_url:
            existing = self.get_gdelt_article_by_canonical_url(canonical_url)

        def _safe_dt(val: Any) -> Optional[datetime]:
            if isinstance(val, datetime):
                return val
            if not val or not isinstance(val, str) or not val.strip():
                return None
            s = val.strip()
            try:
                clean = s.replace("Z", "+00:00")
                return datetime.fromisoformat(clean)
            except Exception:
                pass
            for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            return None

        raw_meta = event_dict.get("raw_metadata")
        raw_meta_str = json.dumps(raw_meta) if isinstance(raw_meta, (dict, list)) else (raw_meta if isinstance(raw_meta, str) else None)

        now = utc_now()

        if not existing:
            article = GdeltArticle(
                event_id=event_id,
                title=event_dict.get("title"),
                source_url=event_dict.get("source_url", canonical_url or ""),
                canonical_url=canonical_url or event_dict.get("source_url", ""),
                source_domain=event_dict.get("source_domain"),
                source_country=event_dict.get("source_country"),
                affected_country=event_dict.get("affected_country"),
                mineral=event_dict.get("mineral"),
                event_type=event_dict.get("event_type"),
                event_date=_safe_dt(event_dict.get("event_date")),
                publication_date=_safe_dt(event_dict.get("publication_date")),
                gdelt_seen_date=_safe_dt(event_dict.get("gdelt_seen_date")),
                retrieved_at=_safe_dt(event_dict.get("retrieved_at")) or now,
                first_seen_at=now,
                last_seen_at=now,
                classification_status=event_dict.get("classification_status", "pending"),
                provider=event_dict.get("provider", "gdelt_doc_2"),
                language=event_dict.get("language") or (raw_meta.get("language") if isinstance(raw_meta, dict) else None),
                raw_metadata=raw_meta_str,
            )
            self.db.add(article)
            self.db.flush()

            if category:
                cat_assoc = GdeltArticleCategory(
                    article_id=article.id,
                    category=category,
                    created_at=now,
                )
                self.db.add(cat_assoc)

            return article, "inserted"
        else:
            # Duplicate / existing article: update last_seen_at, never overwrite non-null with null
            existing.last_seen_at = now

            if not existing.title and event_dict.get("title"):
                existing.title = event_dict.get("title")
            if not existing.source_domain and event_dict.get("source_domain"):
                existing.source_domain = event_dict.get("source_domain")
            if not existing.source_country and event_dict.get("source_country"):
                existing.source_country = event_dict.get("source_country")
            if not existing.language and event_dict.get("language"):
                existing.language = event_dict.get("language")
            if not existing.gdelt_seen_date and event_dict.get("gdelt_seen_date"):
                existing.gdelt_seen_date = _safe_dt(event_dict.get("gdelt_seen_date"))
            if not existing.raw_metadata and raw_meta_str:
                existing.raw_metadata = raw_meta_str

            # Check if category already linked
            if category:
                has_cat = (
                    self.db.query(GdeltArticleCategory)
                    .filter(
                        GdeltArticleCategory.article_id == existing.id,
                        GdeltArticleCategory.category == category,
                    )
                    .first()
                )
                if not has_cat:
                    cat_assoc = GdeltArticleCategory(
                        article_id=existing.id,
                        category=category,
                        created_at=now,
                    )
                    self.db.add(cat_assoc)

            return existing, "duplicate"

    def list_gdelt_articles(
        self,
        category: Optional[str] = None,
        classification_status: Optional[str] = None,
        provider: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[GdeltArticle]:
        q = self.db.query(GdeltArticle)
        if category:
            q = q.join(GdeltArticle.categories).filter(GdeltArticleCategory.category == category)
        if classification_status:
            q = q.filter(GdeltArticle.classification_status == classification_status)
        if provider:
            q = q.filter(GdeltArticle.provider == provider)
        if from_date:
            q = q.filter(GdeltArticle.first_seen_at >= from_date)
        if to_date:
            q = q.filter(GdeltArticle.first_seen_at <= to_date)
        return q.order_by(desc(GdeltArticle.id)).offset(offset).limit(limit).all()

    def count_gdelt_articles(
        self,
        category: Optional[str] = None,
        classification_status: Optional[str] = None,
        provider: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> int:
        q = self.db.query(func.count(func.distinct(GdeltArticle.id)))
        if category:
            q = q.join(GdeltArticle.categories).filter(GdeltArticleCategory.category == category)
        if classification_status:
            q = q.filter(GdeltArticle.classification_status == classification_status)
        if provider:
            q = q.filter(GdeltArticle.provider == provider)
        if from_date:
            q = q.filter(GdeltArticle.first_seen_at >= from_date)
        if to_date:
            q = q.filter(GdeltArticle.first_seen_at <= to_date)
        return q.scalar() or 0

    def get_latest_gdelt_ingestion_runs(self, limit: int = 10) -> List[GdeltIngestionRun]:
        return (
            self.db.query(GdeltIngestionRun)
            .order_by(desc(GdeltIngestionRun.id))
            .limit(limit)
            .all()
        )

