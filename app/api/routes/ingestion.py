"""Data ingestion triggers API routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.ingestion.service import IngestionService
from app.schemas.ingestion import (
    TradeIngestionRequest,
    SanctionsIngestionRequest,
    IngestionResponse,
)

router = APIRouter(prefix="/api/v1/ingestion", tags=["Data Ingestion"])


@router.post("/trade", response_model=IngestionResponse, status_code=status.HTTP_200_OK)
def trigger_trade_ingestion(
    payload: TradeIngestionRequest = TradeIngestionRequest(),
    db: Session = Depends(get_db),
):
    """
    Triggers UN Comtrade data ingestion.
    Validates, deduplicates, and stores raw and normalized records into the local database.
    Does NOT trigger automatically on dashboard open.
    """
    service = IngestionService(db)
    try:
        result = service.ingest_trade_data(
            commodity_codes=payload.commodity_codes,
            periods=payload.periods,
            fixture_path=payload.fixture_path,
        )
        return IngestionResponse(**result)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Trade data ingestion failed: {str(exc)}",
        )


@router.post("/sanctions", response_model=IngestionResponse, status_code=status.HTTP_200_OK)
def trigger_sanctions_ingestion(
    payload: SanctionsIngestionRequest = SanctionsIngestionRequest(),
    db: Session = Depends(get_db),
):
    """
    Triggers official OFAC Sanctions data ingestion.
    Parses official structured data and retains previous records on failure.
    """
    service = IngestionService(db)
    try:
        result = service.ingest_sanctions_data(
            fixture_path=payload.fixture_path,
            source_url=payload.source_url,
        )
        return IngestionResponse(**result)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OFAC sanctions ingestion failed: {str(exc)}",
        )
