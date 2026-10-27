"""FastAPI router for Phase 5 Operational Audit Trail."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.audit.service import AuditEventService
from app.schemas.audit import AuditEventResponse, AuditEventListResponse

router = APIRouter(prefix="/api/v1/audit", tags=["Audit Trail"])


@router.get(
    "/events",
    response_model=AuditEventListResponse,
    summary="List append-only audit trail events",
    description=(
        "Retrieves operational audit events with filtering by event_type, related_record_id, "
        "operation_status, and date ranges. Safe responses omit stack traces and credentials."
    ),
)
def list_audit_events(
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    event_type: Optional[str] = Query(default=None, description="Filter by event type (e.g. RISK_ANALYSIS_CREATED)."),
    related_record_id: Optional[str] = Query(default=None, description="Filter by related entity identifier."),
    operation_status: Optional[str] = Query(default=None, description="Filter by status (SUCCESS, FAILED, WARNING)."),
    start_date: Optional[datetime] = Query(default=None, description="Filter events after timestamp."),
    end_date: Optional[datetime] = Query(default=None, description="Filter events before timestamp."),
    db: Session = Depends(get_db),
):
    service = AuditEventService(db)
    return service.list_events(
        page=page,
        page_size=page_size,
        event_type=event_type,
        related_record_id=related_record_id,
        operation_status=operation_status,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/events/{event_id}",
    response_model=AuditEventResponse,
    summary="Retrieve details for a specific audit event",
    description="Fetches an individual audit event by its UUID.",
)
def get_audit_event(
    event_id: str,
    db: Session = Depends(get_db),
):
    service = AuditEventService(db)
    event = service.get_event(event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit event with ID '{event_id}' was not found.",
        )
    return event
