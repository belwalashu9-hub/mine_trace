"""Audit trail service providing append-only operational event logging and queries."""
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, and_

from app.database.models import AuditEvent
from app.evidence.rules import AUDIT_LOG_LIMITATIONS
from app.schemas.audit import AuditEventResponse, AuditEventListResponse


def sanitize_error_string(err: Optional[str], max_len: int = 500) -> Optional[str]:
    """Sanitizes error string to prevent stack trace leaks or sensitive data exposure."""
    if not err:
        return None
    cleaned = str(err).strip()
    # Strip typical stack trace headers if present
    if "Traceback (most recent call last):" in cleaned:
        cleaned = cleaned.split("Traceback (most recent call last):")[-1].strip()
    return cleaned[:max_len]


class AuditEventService:
    """Service managing append-only operational audit events."""

    def __init__(self, db: Session):
        self.db = db

    def record_event(
        self,
        event_type: str,
        related_record_id: Optional[str] = None,
        operation_status: str = "SUCCESS",
        metadata: Optional[Dict[str, Any]] = None,
        error_details: Optional[str] = None,
    ) -> AuditEvent:
        """Appends a new audit event record without altering existing history."""
        event_id = str(uuid.uuid4())
        safe_error = sanitize_error_string(error_details)
        meta_json = json.dumps(metadata) if metadata else None

        event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            related_record_id=str(related_record_id) if related_record_id is not None else None,
            operation_status=operation_status,
            event_metadata=meta_json,
            error_details=safe_error,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_event(self, event_id: str) -> Optional[AuditEventResponse]:
        """Retrieves a single audit event by its UUID."""
        event = (
            self.db.query(AuditEvent)
            .filter(AuditEvent.event_id == event_id.strip())
            .first()
        )
        if not event:
            return None

        meta = json.loads(event.event_metadata) if event.event_metadata else None
        return AuditEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            related_record_id=event.related_record_id,
            operation_status=event.operation_status,
            event_metadata=meta,
            error_details=event.error_details,
            created_at=event.created_at,
        )

    def list_events(
        self,
        page: int = 1,
        page_size: int = 20,
        event_type: Optional[str] = None,
        related_record_id: Optional[str] = None,
        operation_status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> AuditEventListResponse:
        """Queries audit events with multi-attribute filtering and pagination."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        conditions = []
        if event_type:
            conditions.append(AuditEvent.event_type == event_type.strip().upper())
        if related_record_id:
            conditions.append(AuditEvent.related_record_id == str(related_record_id).strip())
        if operation_status:
            conditions.append(AuditEvent.operation_status == operation_status.strip().upper())
        if start_date:
            conditions.append(AuditEvent.timestamp >= start_date)
        if end_date:
            conditions.append(AuditEvent.timestamp <= end_date)

        query = self.db.query(AuditEvent)
        if conditions:
            query = query.filter(and_(*conditions))

        total = query.count()
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        offset = (page - 1) * page_size

        events_db = (
            query.order_by(desc(AuditEvent.timestamp), desc(AuditEvent.id))
            .offset(offset)
            .limit(page_size)
            .all()
        )

        results = []
        for e in events_db:
            meta = json.loads(e.event_metadata) if e.event_metadata else None
            results.append(
                AuditEventResponse(
                    event_id=e.event_id,
                    event_type=e.event_type,
                    timestamp=e.timestamp,
                    related_record_id=e.related_record_id,
                    operation_status=e.operation_status,
                    event_metadata=meta,
                    error_details=e.error_details,
                    created_at=e.created_at,
                )
            )

        return AuditEventListResponse(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1 and total > 0,
            events=results,
            limitations=AUDIT_LOG_LIMITATIONS,
        )
