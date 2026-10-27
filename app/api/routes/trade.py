"""Trade records and critical mineral queries API routes."""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.repository import MineTraceRepository
from app.schemas.trade import (
    TradeRecordListResponse,
    MineralSummary,
    TradeRecordResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Trade Records"])


@router.get("/trade-records", response_model=TradeRecordListResponse)
def list_trade_records(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=500, description="Page size limit"),
    commodity_code: Optional[str] = Query(None, description="Filter by HS commodity code (e.g. 283691)"),
    reporter_country_code: Optional[str] = Query(None, description="Filter by reporting country code (e.g. CHL, AUS)"),
    partner_country_code: Optional[str] = Query(None, description="Filter by partner country code (e.g. CHN, USA)"),
    flow_type: Optional[str] = Query(None, description="Filter by trade flow ('IMPORT' or 'EXPORT')"),
    period_year: Optional[int] = Query(None, description="Filter by year (e.g. 2023)"),
    db: Session = Depends(get_db),
):
    """
    Retrieves paginated, normalized trade records from the local SQLite database.
    Operates offline-first without triggering remote API downloads.
    """
    repo = MineTraceRepository(db)
    records, total = repo.list_trade_records(
        skip=skip,
        limit=limit,
        commodity_code=commodity_code,
        reporter_country_code=reporter_country_code,
        partner_country_code=partner_country_code,
        flow_type=flow_type,
        period_year=period_year,
    )

    return TradeRecordListResponse(
        total=total,
        skip=skip,
        limit=limit,
        records=records,
    )


@router.get("/minerals", response_model=List[MineralSummary])
def get_minerals(db: Session = Depends(get_db)):
    """
    Retrieves the list of distinct critical minerals and commodity classifications
    currently stored in the database.
    """
    repo = MineTraceRepository(db)
    minerals = repo.get_distinct_minerals()
    return minerals
