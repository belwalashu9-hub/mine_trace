"""Pydantic schemas for Phase 5 Audit Trail."""
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict

from app.evidence.rules import AUDIT_LOG_LIMITATIONS


class AuditEventResponse(BaseModel):
    """An individual append-only audit event record."""
    event_id: str
    event_type: str
    timestamp: datetime
    related_record_id: Optional[str] = None
    operation_status: str
    event_metadata: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditEventListResponse(BaseModel):
    """Paginated list of audit events."""
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool
    events: List[AuditEventResponse] = Field(default_factory=list)
    limitations: str = AUDIT_LOG_LIMITATIONS
