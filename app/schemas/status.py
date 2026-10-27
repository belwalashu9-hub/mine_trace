"""Pydantic schemas for health and system status endpoints."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database_connected: bool
    timestamp: datetime


class SourceStatus(BaseModel):
    source_name: str
    source_url: str
    last_status: str
    last_successful_retrieval: Optional[datetime] = None
    last_attempt_timestamp: Optional[datetime] = None
    total_records_ingested: int


class SystemStatusResponse(BaseModel):
    status: str
    database_location: str
    sources: List[SourceStatus]
    record_counts: Dict[str, int]
    last_retrievals: Dict[str, Optional[datetime]]


class ComponentHealth(BaseModel):
    status: str  # READY, DEGRADED, OFFLINE, UNAVAILABLE
    message: Optional[str] = None


class ReadinessResponse(BaseModel):
    status: str  # READY, DEGRADED, UNAVAILABLE
    version: str
    environment: str
    timestamp: datetime
    offline_mode: bool
    components: Dict[str, ComponentHealth]
    data_counts: Dict[str, int]
