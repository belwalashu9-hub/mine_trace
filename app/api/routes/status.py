"""Data status and freshness API routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.connection import get_db
from app.database.repository import MineTraceRepository
from app.schemas.status import SystemStatusResponse, SourceStatus

router = APIRouter(prefix="/api/v1/data", tags=["Data Freshness"])
settings = get_settings()


@router.get("/status", response_model=SystemStatusResponse)
def get_data_status(db: Session = Depends(get_db)):
    """
    Returns data freshness, last successful retrieval timestamps,
    and record counts for offline analysis and auditing.
    """
    repo = MineTraceRepository(db)
    status_dict = repo.get_system_status()

    sources = [
        SourceStatus(
            source_name=s["source_name"],
            source_url=s["source_url"],
            last_status=s["last_status"],
            last_successful_retrieval=s["last_successful_retrieval"],
            last_attempt_timestamp=s["last_attempt_timestamp"],
            total_records_ingested=s["total_records_ingested"],
        )
        for s in status_dict["sources"]
    ]

    return SystemStatusResponse(
        status="OPERATIONAL",
        database_location=str(settings.database_url),
        sources=sources,
        record_counts=status_dict["counts"],
        last_retrievals=status_dict["last_successful_retrieval"],
    )
