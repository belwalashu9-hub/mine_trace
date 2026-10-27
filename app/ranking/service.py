"""Ranking service implementing Phase 4 Risk Ranking Engine."""
import json
import math
import uuid
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc

from app.database.models import (
    RiskAnalysis,
    RankingSnapshot,
    RankingSnapshotItem,
)
from app.ranking.rules import (
    RANKING_POLICY_VERSION,
    TIE_BREAKER_POLICY,
    SCOPE_GLOBAL,
    SCOPE_FILTERED,
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    COMPLETENESS_UNAVAILABLE,
    EXCLUSION_PARTIAL,
    EXCLUSION_UNAVAILABLE,
    EXCLUSION_INVALID_SCORE,
    EXCLUSION_CORRUPT_ANALYSIS,
    RANKING_DISCLAIMER,
)
from app.schemas.ranking import (
    RankingEntry,
    RankingResponse,
    IncompleteRecordEntry,
    IncompleteRankingResponse,
    RankingSummaryResponse,
    RecordRankLookupResponse,
    SnapshotDetailResponse,
    SnapshotItemResponse,
    SnapshotListResponse,
    SnapshotListItem,
)


def parse_json_list(val: Any) -> List[str]:
    """Safely parses JSON-serialized list strings."""
    if not val:
        return []
    if isinstance(val, list):
        return [str(x) for x in val]
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return [str(parsed)]
    except Exception:
        return [str(val)]


class RankingService:
    """Service providing deterministic risk ranking, filtering, tie-breaking, and snapshotting."""

    def __init__(self, db: Session):
        self.db = db

    def _build_filter_conditions(
        self,
        commodity_code: Optional[str] = None,
        mineral_type: Optional[str] = None,
        reporter_country_code: Optional[str] = None,
        partner_country_code: Optional[str] = None,
        period: Optional[str] = None,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
        classification: Optional[str] = None,
        flag_status: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """Constructs SQLAlchemy WHERE clauses and records active filters for response metadata."""
        conditions = []
        active_filters = {}

        if commodity_code:
            code = commodity_code.strip()
            conditions.append(RiskAnalysis.commodity_code == code)
            active_filters["commodity_code"] = code

        if mineral_type:
            mineral = mineral_type.strip()
            conditions.append(RiskAnalysis.mineral_type.ilike(f"%{mineral}%"))
            active_filters["mineral_type"] = mineral

        if reporter_country_code:
            reporter = reporter_country_code.strip().upper()
            conditions.append(RiskAnalysis.reporter_country_code == reporter)
            active_filters["reporter_country_code"] = reporter

        if partner_country_code:
            partner = partner_country_code.strip().upper()
            conditions.append(RiskAnalysis.partner_country_code == partner)
            active_filters["partner_country_code"] = partner

        if period:
            p = period.strip()
            conditions.append(RiskAnalysis.period == p)
            active_filters["period"] = p

        if period_start:
            ps = period_start.strip()
            conditions.append(RiskAnalysis.period >= ps)
            active_filters["period_start"] = ps

        if period_end:
            pe = period_end.strip()
            conditions.append(RiskAnalysis.period <= pe)
            active_filters["period_end"] = pe

        if classification:
            cls_upper = classification.strip().upper()
            conditions.append(RiskAnalysis.classification == cls_upper)
            active_filters["classification"] = cls_upper

        if flag_status:
            flg_upper = flag_status.strip().upper()
            conditions.append(RiskAnalysis.flag_status == flg_upper)
            active_filters["flag_status"] = flg_upper

        if min_score is not None:
            conditions.append(RiskAnalysis.combined_anomaly_score >= min_score)
            active_filters["min_score"] = min_score

        if max_score is not None:
            conditions.append(RiskAnalysis.combined_anomaly_score <= max_score)
            active_filters["max_score"] = max_score

        return conditions, active_filters

    def get_primary_ranking(
        self,
        commodity_code: Optional[str] = None,
        mineral_type: Optional[str] = None,
        reporter_country_code: Optional[str] = None,
        partner_country_code: Optional[str] = None,
        period: Optional[str] = None,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
        classification: Optional[str] = None,
        flag_status: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RankingResponse:
        """Retrieves ranked COMPLETE risk analyses ordered by score DESC, created_at DESC, analysis_id ASC."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        # Eligibility baseline: completeness must be COMPLETE and score between 0 and 100
        base_conditions = [
            RiskAnalysis.score_completeness == COMPLETENESS_COMPLETE,
            RiskAnalysis.combined_anomaly_score >= 0.0,
            RiskAnalysis.combined_anomaly_score <= 100.0,
        ]

        # Domain filters
        domain_conditions, active_filters = self._build_filter_conditions(
            commodity_code=commodity_code,
            mineral_type=mineral_type,
            reporter_country_code=reporter_country_code,
            partner_country_code=partner_country_code,
            period=period,
            period_start=period_start,
            period_end=period_end,
            classification=classification,
            flag_status=flag_status,
            min_score=min_score,
            max_score=max_score,
        )

        all_conditions = base_conditions + domain_conditions
        scope = SCOPE_FILTERED if active_filters else SCOPE_GLOBAL

        # Count total eligible records matching query
        total_eligible = self.db.query(func.count(RiskAnalysis.id)).filter(and_(*all_conditions)).scalar() or 0
        total_pages = math.ceil(total_eligible / page_size) if total_eligible > 0 else 0

        # Query with deterministic tie-breaking policy:
        # 1. combined_anomaly_score DESC
        # 2. created_at DESC
        # 3. analysis_id ASC
        offset = (page - 1) * page_size
        analyses = (
            self.db.query(RiskAnalysis)
            .filter(and_(*all_conditions))
            .order_by(
                desc(RiskAnalysis.combined_anomaly_score),
                desc(RiskAnalysis.created_at),
                asc(RiskAnalysis.analysis_id),
            )
            .offset(offset)
            .limit(page_size)
            .all()
        )

        rankings: List[RankingEntry] = []
        for idx, item in enumerate(analyses):
            rank = offset + idx + 1
            rankings.append(
                RankingEntry(
                    rank=rank,
                    analysis_id=item.analysis_id,
                    trade_record_id=item.trade_record_id,
                    commodity_code=item.commodity_code,
                    mineral_type=item.mineral_type,
                    reporter_country_code=item.reporter_country_code,
                    partner_country_code=item.partner_country_code,
                    period=item.period,
                    anomaly_score=float(item.combined_anomaly_score),
                    score_completeness=item.score_completeness,
                    classification=item.classification,
                    flag_status=item.flag_status,
                    sanctions_status=item.sanctions_status,
                    evaluated_rules=parse_json_list(item.evaluated_rules),
                    flagged_rules=parse_json_list(item.flagged_rules),
                    insufficient_rules=parse_json_list(item.insufficient_rules),
                    created_at=item.created_at,
                )
            )

        return RankingResponse(
            policy_version=RANKING_POLICY_VERSION,
            tie_breaker_policy=TIE_BREAKER_POLICY,
            scope=scope,
            page=page,
            page_size=page_size,
            total_eligible=total_eligible,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1 and total_eligible > 0,
            active_filters=active_filters,
            rankings=rankings,
            disclaimer=RANKING_DISCLAIMER,
        )

    def get_incomplete_records(
        self,
        commodity_code: Optional[str] = None,
        reporter_country_code: Optional[str] = None,
        partner_country_code: Optional[str] = None,
        period: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> IncompleteRankingResponse:
        """Retrieves analyses excluded from primary ranking (PARTIAL, UNAVAILABLE, or invalid scores)."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        # Incomplete / excluded condition:
        # Completeness != COMPLETE OR score < 0 OR score > 100 OR score IS NULL
        exclusion_condition = or_(
            RiskAnalysis.score_completeness != COMPLETENESS_COMPLETE,
            RiskAnalysis.combined_anomaly_score < 0.0,
            RiskAnalysis.combined_anomaly_score > 100.0,
            RiskAnalysis.combined_anomaly_score.is_(None),
        )

        domain_conditions, _ = self._build_filter_conditions(
            commodity_code=commodity_code,
            reporter_country_code=reporter_country_code,
            partner_country_code=partner_country_code,
            period=period,
        )

        all_conditions = [exclusion_condition] + domain_conditions

        total = self.db.query(func.count(RiskAnalysis.id)).filter(and_(*all_conditions)).scalar() or 0
        total_pages = math.ceil(total / page_size) if total > 0 else 0

        offset = (page - 1) * page_size
        records_query = (
            self.db.query(RiskAnalysis)
            .filter(and_(*all_conditions))
            .order_by(desc(RiskAnalysis.created_at), asc(RiskAnalysis.analysis_id))
            .offset(offset)
            .limit(page_size)
            .all()
        )

        results: List[IncompleteRecordEntry] = []
        for r in records_query:
            if r.score_completeness == COMPLETENESS_PARTIAL:
                reason = EXCLUSION_PARTIAL
            elif r.score_completeness == COMPLETENESS_UNAVAILABLE:
                reason = EXCLUSION_UNAVAILABLE
            elif r.combined_anomaly_score is None or r.combined_anomaly_score < 0 or r.combined_anomaly_score > 100:
                reason = EXCLUSION_INVALID_SCORE
            else:
                reason = EXCLUSION_CORRUPT_ANALYSIS

            results.append(
                IncompleteRecordEntry(
                    analysis_id=r.analysis_id,
                    trade_record_id=r.trade_record_id,
                    commodity_code=r.commodity_code,
                    mineral_type=r.mineral_type,
                    reporter_country_code=r.reporter_country_code,
                    partner_country_code=r.partner_country_code,
                    period=r.period,
                    anomaly_score=float(r.combined_anomaly_score) if r.combined_anomaly_score is not None else None,
                    score_completeness=r.score_completeness or "UNKNOWN",
                    classification=r.classification,
                    insufficient_rules=parse_json_list(r.insufficient_rules),
                    evaluated_rules=parse_json_list(r.evaluated_rules),
                    exclusion_reason=reason,
                    created_at=r.created_at,
                )
            )

        return IncompleteRankingResponse(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1 and total > 0,
            records=results,
            disclaimer=RANKING_DISCLAIMER,
        )

    def get_record_rank(self, analysis_id: str) -> Optional[RecordRankLookupResponse]:
        """Looks up the rank and eligibility context for a specific analysis ID."""
        analysis = (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.analysis_id == analysis_id.strip())
            .first()
        )
        if not analysis:
            return None

        # Check total complete eligible count
        complete_eligible_filter = and_(
            RiskAnalysis.score_completeness == COMPLETENESS_COMPLETE,
            RiskAnalysis.combined_anomaly_score >= 0.0,
            RiskAnalysis.combined_anomaly_score <= 100.0,
        )
        total_eligible = self.db.query(func.count(RiskAnalysis.id)).filter(complete_eligible_filter).scalar() or 0

        # Check if this record is eligible
        is_eligible = (
            analysis.score_completeness == COMPLETENESS_COMPLETE
            and analysis.combined_anomaly_score is not None
            and 0.0 <= analysis.combined_anomaly_score <= 100.0
        )

        rank = None
        exclusion_reason = None

        if not is_eligible:
            if analysis.score_completeness == COMPLETENESS_PARTIAL:
                exclusion_reason = EXCLUSION_PARTIAL
            elif analysis.score_completeness == COMPLETENESS_UNAVAILABLE:
                exclusion_reason = EXCLUSION_UNAVAILABLE
            elif (
                analysis.combined_anomaly_score is None
                or analysis.combined_anomaly_score < 0
                or analysis.combined_anomaly_score > 100
            ):
                exclusion_reason = EXCLUSION_INVALID_SCORE
            else:
                exclusion_reason = EXCLUSION_CORRUPT_ANALYSIS
        else:
            # Deterministic rank computation:
            # Count records strictly preceding this one under the tie-breaking policy:
            # (score > this.score) OR
            # (score == this.score AND created_at > this.created_at) OR
            # (score == this.score AND created_at == this.created_at AND analysis_id < this.analysis_id)
            preceding_count = (
                self.db.query(func.count(RiskAnalysis.id))
                .filter(
                    complete_eligible_filter,
                    or_(
                        RiskAnalysis.combined_anomaly_score > analysis.combined_anomaly_score,
                        and_(
                            RiskAnalysis.combined_anomaly_score == analysis.combined_anomaly_score,
                            RiskAnalysis.created_at > analysis.created_at,
                        ),
                        and_(
                            RiskAnalysis.combined_anomaly_score == analysis.combined_anomaly_score,
                            RiskAnalysis.created_at == analysis.created_at,
                            RiskAnalysis.analysis_id < analysis.analysis_id,
                        ),
                    ),
                )
                .scalar()
                or 0
            )
            rank = preceding_count + 1

        return RecordRankLookupResponse(
            analysis_id=analysis.analysis_id,
            is_eligible=is_eligible,
            rank=rank,
            total_eligible=total_eligible,
            anomaly_score=float(analysis.combined_anomaly_score) if analysis.combined_anomaly_score is not None else None,
            score_completeness=analysis.score_completeness,
            classification=analysis.classification,
            flag_status=analysis.flag_status,
            exclusion_reason=exclusion_reason,
            commodity_code=analysis.commodity_code,
            mineral_type=analysis.mineral_type,
            period=analysis.period,
            reporter_country_code=analysis.reporter_country_code,
            partner_country_code=analysis.partner_country_code,
            created_at=analysis.created_at,
            tie_breaker_policy=TIE_BREAKER_POLICY,
            disclaimer=RANKING_DISCLAIMER,
        )

    def get_ranking_summary(self) -> RankingSummaryResponse:
        """Computes system-wide ranking and completeness aggregate metrics."""
        total_analyses = self.db.query(func.count(RiskAnalysis.id)).scalar() or 0

        complete_filter = and_(
            RiskAnalysis.score_completeness == COMPLETENESS_COMPLETE,
            RiskAnalysis.combined_anomaly_score >= 0.0,
            RiskAnalysis.combined_anomaly_score <= 100.0,
        )
        eligible_complete_count = self.db.query(func.count(RiskAnalysis.id)).filter(complete_filter).scalar() or 0

        partial_excluded_count = (
            self.db.query(func.count(RiskAnalysis.id))
            .filter(RiskAnalysis.score_completeness == COMPLETENESS_PARTIAL)
            .scalar()
            or 0
        )

        unavailable_excluded_count = (
            self.db.query(func.count(RiskAnalysis.id))
            .filter(RiskAnalysis.score_completeness == COMPLETENESS_UNAVAILABLE)
            .scalar()
            or 0
        )

        invalid_score_count = (
            self.db.query(func.count(RiskAnalysis.id))
            .filter(
                or_(
                    RiskAnalysis.combined_anomaly_score < 0.0,
                    RiskAnalysis.combined_anomaly_score > 100.0,
                    RiskAnalysis.combined_anomaly_score.is_(None),
                )
            )
            .scalar()
            or 0
        )

        # Score stats on eligible records
        stats = (
            self.db.query(
                func.max(RiskAnalysis.combined_anomaly_score),
                func.min(RiskAnalysis.combined_anomaly_score),
                func.avg(RiskAnalysis.combined_anomaly_score),
            )
            .filter(complete_filter)
            .first()
        )

        highest_score = round(float(stats[0]), 2) if stats and stats[0] is not None else None
        lowest_score = round(float(stats[1]), 2) if stats and stats[1] is not None else None
        average_score = round(float(stats[2]), 2) if stats and stats[2] is not None else None

        # Classification breakdown across ALL analyses
        cls_rows = (
            self.db.query(RiskAnalysis.classification, func.count(RiskAnalysis.id))
            .group_by(RiskAnalysis.classification)
            .all()
        )
        classification_breakdown = {
            (r[0] or "UNCLASSIFIED"): r[1] for r in cls_rows
        }

        # Flag status breakdown across ALL analyses
        flg_rows = (
            self.db.query(RiskAnalysis.flag_status, func.count(RiskAnalysis.id))
            .group_by(RiskAnalysis.flag_status)
            .all()
        )
        flag_status_breakdown = {
            (r[0] or "UNKNOWN"): r[1] for r in flg_rows
        }

        return RankingSummaryResponse(
            total_analyses=total_analyses,
            eligible_complete_count=eligible_complete_count,
            partial_excluded_count=partial_excluded_count,
            unavailable_excluded_count=unavailable_excluded_count,
            invalid_score_count=invalid_score_count,
            highest_score=highest_score,
            lowest_score=lowest_score,
            average_score=average_score,
            classification_breakdown=classification_breakdown,
            flag_status_breakdown=flag_status_breakdown,
            disclaimer=RANKING_DISCLAIMER,
        )

    def create_ranking_snapshot(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        commodity_code: Optional[str] = None,
        mineral_type: Optional[str] = None,
        reporter_country_code: Optional[str] = None,
        partner_country_code: Optional[str] = None,
        period: Optional[str] = None,
        classification: Optional[str] = None,
        flag_status: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
    ) -> SnapshotDetailResponse:
        """Creates an immutable point-in-time snapshot of the current ranking."""
        snapshot_id = str(uuid.uuid4())

        # Baseline complete condition
        base_conditions = [
            RiskAnalysis.score_completeness == COMPLETENESS_COMPLETE,
            RiskAnalysis.combined_anomaly_score >= 0.0,
            RiskAnalysis.combined_anomaly_score <= 100.0,
        ]

        domain_conditions, active_filters = self._build_filter_conditions(
            commodity_code=commodity_code,
            mineral_type=mineral_type,
            reporter_country_code=reporter_country_code,
            partner_country_code=partner_country_code,
            period=period,
            classification=classification,
            flag_status=flag_status,
            min_score=min_score,
            max_score=max_score,
        )

        all_conditions = base_conditions + domain_conditions

        # Fetch all matching eligible records ordered by tie-breaker
        eligible_records = (
            self.db.query(RiskAnalysis)
            .filter(and_(*all_conditions))
            .order_by(
                desc(RiskAnalysis.combined_anomaly_score),
                desc(RiskAnalysis.created_at),
                asc(RiskAnalysis.analysis_id),
            )
            .all()
        )

        total_eligible = len(eligible_records)

        # Count excluded records in the current database
        partial_count = (
            self.db.query(func.count(RiskAnalysis.id))
            .filter(RiskAnalysis.score_completeness == COMPLETENESS_PARTIAL)
            .scalar()
            or 0
        )
        unavailable_count = (
            self.db.query(func.count(RiskAnalysis.id))
            .filter(RiskAnalysis.score_completeness == COMPLETENESS_UNAVAILABLE)
            .scalar()
            or 0
        )
        invalid_count = (
            self.db.query(func.count(RiskAnalysis.id))
            .filter(
                or_(
                    RiskAnalysis.combined_anomaly_score < 0.0,
                    RiskAnalysis.combined_anomaly_score > 100.0,
                    RiskAnalysis.combined_anomaly_score.is_(None),
                )
            )
            .scalar()
            or 0
        )

        exclusion_reasons = {
            "PARTIAL": partial_count,
            "UNAVAILABLE": unavailable_count,
            "INVALID_SCORE": invalid_count,
        }
        total_excluded = partial_count + unavailable_count + invalid_count

        snapshot = RankingSnapshot(
            snapshot_id=snapshot_id,
            name=name or f"Snapshot {snapshot_id[:8]}",
            description=description,
            policy_version=RANKING_POLICY_VERSION,
            filters_applied=json.dumps(active_filters) if active_filters else None,
            total_eligible_count=total_eligible,
            excluded_count=total_excluded,
            exclusion_reasons=json.dumps(exclusion_reasons),
        )
        self.db.add(snapshot)
        self.db.flush()

        # Add ranked snapshot items
        items_response: List[SnapshotItemResponse] = []
        for idx, rec in enumerate(eligible_records):
            rank = idx + 1
            item = RankingSnapshotItem(
                snapshot_id=snapshot_id,
                rank=rank,
                analysis_id=rec.analysis_id,
                anomaly_score=float(rec.combined_anomaly_score),
                classification=rec.classification,
                flag_status=rec.flag_status,
                commodity_code=rec.commodity_code,
                mineral_type=rec.mineral_type,
                reporter_country_code=rec.reporter_country_code,
                partner_country_code=rec.partner_country_code,
                period=rec.period,
            )
            self.db.add(item)
            items_response.append(
                SnapshotItemResponse(
                    rank=rank,
                    analysis_id=rec.analysis_id,
                    anomaly_score=float(rec.combined_anomaly_score),
                    classification=rec.classification,
                    flag_status=rec.flag_status,
                    commodity_code=rec.commodity_code,
                    mineral_type=rec.mineral_type,
                    reporter_country_code=rec.reporter_country_code,
                    partner_country_code=rec.partner_country_code,
                    period=rec.period,
                    created_at=rec.created_at,
                )
            )

        self.db.commit()
        self.db.refresh(snapshot)

        # Phase 5: Log audit event for ranking snapshot
        try:
            from app.audit.service import AuditEventService
            from app.evidence.rules import EVENT_RANKING_SNAPSHOT_CREATED
            AuditEventService(self.db).record_event(
                event_type=EVENT_RANKING_SNAPSHOT_CREATED,
                related_record_id=snapshot.snapshot_id,
                operation_status="SUCCESS",
                metadata={
                    "total_eligible_count": snapshot.total_eligible_count,
                    "excluded_count": snapshot.excluded_count,
                    "policy_version": snapshot.policy_version,
                },
            )
        except Exception:
            pass

        return SnapshotDetailResponse(
            snapshot_id=snapshot.snapshot_id,
            name=snapshot.name,
            description=snapshot.description,
            policy_version=snapshot.policy_version,
            filters_applied=json.loads(snapshot.filters_applied) if snapshot.filters_applied else None,
            total_eligible_count=snapshot.total_eligible_count,
            excluded_count=snapshot.excluded_count,
            exclusion_reasons=exclusion_reasons,
            created_at=snapshot.created_at,
            items=items_response,
        )

    def get_snapshot(self, snapshot_id: str) -> Optional[SnapshotDetailResponse]:
        """Retrieves a persistent ranking snapshot by its UUID."""
        snapshot = (
            self.db.query(RankingSnapshot)
            .filter(RankingSnapshot.snapshot_id == snapshot_id.strip())
            .first()
        )
        if not snapshot:
            return None

        items = (
            self.db.query(RankingSnapshotItem)
            .filter(RankingSnapshotItem.snapshot_id == snapshot.snapshot_id)
            .order_by(asc(RankingSnapshotItem.rank))
            .all()
        )

        items_resp = [
            SnapshotItemResponse(
                rank=i.rank,
                analysis_id=i.analysis_id,
                anomaly_score=float(i.anomaly_score),
                classification=i.classification,
                flag_status=i.flag_status,
                commodity_code=i.commodity_code,
                mineral_type=i.mineral_type,
                reporter_country_code=i.reporter_country_code,
                partner_country_code=i.partner_country_code,
                period=i.period,
                created_at=i.created_at,
            )
            for i in items
        ]

        filters = json.loads(snapshot.filters_applied) if snapshot.filters_applied else None
        reasons = json.loads(snapshot.exclusion_reasons) if snapshot.exclusion_reasons else None

        return SnapshotDetailResponse(
            snapshot_id=snapshot.snapshot_id,
            name=snapshot.name,
            description=snapshot.description,
            policy_version=snapshot.policy_version,
            filters_applied=filters,
            total_eligible_count=snapshot.total_eligible_count,
            excluded_count=snapshot.excluded_count,
            exclusion_reasons=reasons,
            created_at=snapshot.created_at,
            items=items_resp,
        )

    def list_snapshots(self, limit: int = 50) -> SnapshotListResponse:
        """Lists existing persistent ranking snapshots."""
        query = (
            self.db.query(RankingSnapshot)
            .order_by(desc(RankingSnapshot.created_at))
            .limit(limit)
            .all()
        )

        snapshots = [
            SnapshotListItem(
                snapshot_id=s.snapshot_id,
                name=s.name,
                description=s.description,
                policy_version=s.policy_version,
                total_eligible_count=s.total_eligible_count,
                excluded_count=s.excluded_count,
                created_at=s.created_at,
            )
            for s in query
        ]

        return SnapshotListResponse(total=len(snapshots), snapshots=snapshots)
