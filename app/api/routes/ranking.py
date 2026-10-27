"""FastAPI router for Phase 4 Risk Ranking Engine."""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.ranking.service import RankingService
from app.schemas.ranking import (
    RankingResponse,
    IncompleteRankingResponse,
    RankingSummaryResponse,
    RecordRankLookupResponse,
    CreateSnapshotRequest,
    SnapshotDetailResponse,
    SnapshotListResponse,
)

router = APIRouter(prefix="/api/v1/ranking", tags=["Risk Ranking Engine"])


@router.get(
    "",
    response_model=RankingResponse,
    summary="Retrieve ranked list of eligible risk analyses",
    description=(
        "Retrieves eligible risk analysis records ordered by descending anomaly score "
        "with deterministic tie-breaking (combined_anomaly_score DESC, created_at DESC, analysis_id ASC). "
        "Only records with COMPLETE score completeness are ranked."
    ),
)
def get_rankings(
    commodity_code: Optional[str] = Query(default=None, description="Filter by commodity HS code (e.g. 283691)."),
    mineral_type: Optional[str] = Query(default=None, description="Filter by mineral description (e.g. Lithium)."),
    reporter_country_code: Optional[str] = Query(default=None, description="Filter by reporting country ISO-3 code."),
    partner_country_code: Optional[str] = Query(default=None, description="Filter by partner country ISO-3 code."),
    period: Optional[str] = Query(default=None, description="Exact reporting period (e.g. 2023)."),
    period_start: Optional[str] = Query(default=None, description="Lower bound for reporting period."),
    period_end: Optional[str] = Query(default=None, description="Upper bound for reporting period."),
    classification: Optional[str] = Query(default=None, description="Filter by classification (GREEN, AMBER, RED)."),
    flag_status: Optional[str] = Query(default=None, description="Filter by anomaly status (FLAGGED, NOT_FLAGGED)."),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=100.0, description="Minimum anomaly score (0-100)."),
    max_score: Optional[float] = Query(default=None, ge=0.0, le=100.0, description="Maximum anomaly score (0-100)."),
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page (max 100)."),
    db: Session = Depends(get_db),
):
    service = RankingService(db)
    return service.get_primary_ranking(
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
        page=page,
        page_size=page_size,
    )


@router.get(
    "/incomplete",
    response_model=IncompleteRankingResponse,
    summary="Retrieve incomplete or excluded records",
    description=(
        "Retrieves trade analyses excluded from primary ranking due to PARTIAL, "
        "UNAVAILABLE completeness or invalid/missing scores, with explicit exclusion explanations."
    ),
)
def get_incomplete_rankings(
    commodity_code: Optional[str] = Query(default=None, description="Filter by commodity HS code."),
    reporter_country_code: Optional[str] = Query(default=None, description="Filter by reporting country."),
    partner_country_code: Optional[str] = Query(default=None, description="Filter by partner country."),
    period: Optional[str] = Query(default=None, description="Filter by period."),
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Page size."),
    db: Session = Depends(get_db),
):
    service = RankingService(db)
    return service.get_incomplete_records(
        commodity_code=commodity_code,
        reporter_country_code=reporter_country_code,
        partner_country_code=partner_country_code,
        period=period,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/summary",
    response_model=RankingSummaryResponse,
    summary="Retrieve ranking engine summary metrics",
    description="Returns aggregate counts, score distribution, and completeness breakdown across all analyses.",
)
def get_ranking_summary(db: Session = Depends(get_db)):
    service = RankingService(db)
    return service.get_ranking_summary()


@router.post(
    "/snapshots",
    response_model=SnapshotDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a point-in-time ranking snapshot",
    description="Captures an immutable snapshot of current ranking positions and metadata.",
)
def create_ranking_snapshot(
    payload: CreateSnapshotRequest,
    db: Session = Depends(get_db),
):
    service = RankingService(db)
    return service.create_ranking_snapshot(
        name=payload.name,
        description=payload.description,
        commodity_code=payload.commodity_code,
        mineral_type=payload.mineral_type,
        reporter_country_code=payload.reporter_country_code,
        partner_country_code=payload.partner_country_code,
        period=payload.period,
        classification=payload.classification,
        flag_status=payload.flag_status,
        min_score=payload.min_score,
        max_score=payload.max_score,
    )


@router.get(
    "/snapshots",
    response_model=SnapshotListResponse,
    summary="List persistent ranking snapshots",
    description="Returns an audit list of created point-in-time ranking snapshots.",
)
def list_ranking_snapshots(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    service = RankingService(db)
    return service.list_snapshots(limit=limit)


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=SnapshotDetailResponse,
    summary="Get snapshot details and ranked items",
    description="Retrieves a specific ranking snapshot and all its ranked entries.",
)
def get_ranking_snapshot(
    snapshot_id: str,
    db: Session = Depends(get_db),
):
    service = RankingService(db)
    snapshot = service.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ranking snapshot '{snapshot_id}' not found.",
        )
    return snapshot


@router.get(
    "/{analysis_id}",
    response_model=RecordRankLookupResponse,
    summary="Lookup rank position and eligibility of a specific analysis record",
    description=(
        "Returns the global 1-based rank and context for a specific analysis ID, "
        "or explains why it is excluded from primary ranking if incomplete."
    ),
)
def get_analysis_rank_lookup(
    analysis_id: str,
    db: Session = Depends(get_db),
):
    service = RankingService(db)
    result = service.get_record_rank(analysis_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk analysis with ID '{analysis_id}' was not found in the database.",
        )
    return result
