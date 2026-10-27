"""
Pydantic schemas for Model 2 Phase 3: Geopolitical Event Classification & Entity Extraction.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class EventTypeEnum(str, Enum):
    ARMED_CONFLICT = "ARMED_CONFLICT"
    WAR = "WAR"
    POLITICAL_INSTABILITY = "POLITICAL_INSTABILITY"
    MINING_STRIKE = "MINING_STRIKE"
    MINE_SHUTDOWN = "MINE_SHUTDOWN"
    EXPORT_RESTRICTION = "EXPORT_RESTRICTION"
    PORT_CLOSURE = "PORT_CLOSURE"
    MARITIME_SECURITY_INCIDENT = "MARITIME_SECURITY_INCIDENT"
    TRANSPORT_DISRUPTION = "TRANSPORT_DISRUPTION"
    SANCTIONS_ANNOUNCEMENT = "SANCTIONS_ANNOUNCEMENT"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class VerificationStatusEnum(str, Enum):
    REPORTED = "REPORTED"
    CORROBORATED = "CORROBORATED"
    OFFICIALLY_CONFIRMED = "OFFICIALLY_CONFIRMED"
    DISPUTED = "DISPUTED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class MineralRelevanceEnum(str, Enum):
    COBALT = "cobalt"
    LITHIUM = "lithium"
    NICKEL = "nickel"
    NATURAL_GRAPHITE = "natural_graphite"
    ALL_CRITICAL_MINERALS = "all_critical_minerals"
    UNKNOWN = "unknown"
    NONE = "none"


class RelevanceTypeEnum(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"


class EventArticleEvidenceSchema(BaseModel):
    id: Optional[int] = None
    article_id: Optional[int] = None
    source_url: str
    article_title: Optional[str] = None
    relevance_reason: Optional[str] = None
    created_at: Optional[datetime] = None


class GeopoliticalEventRead(BaseModel):
    id: int
    event_id: str
    event_type: str
    title: str
    summary: Optional[str] = None
    affected_country: Optional[str] = None
    region: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    has_coordinates: bool = False
    event_date: Optional[datetime] = None
    publication_date: Optional[datetime] = None
    mineral_relevance: str
    relevance_type: str
    affected_infrastructure: Optional[str] = None
    extraction_confidence: float
    verification_status: str
    source_article_count: int
    status: str
    created_at: datetime
    updated_at: datetime
    article_evidence: List[EventArticleEvidenceSchema] = []

    model_config = ConfigDict(from_attributes=True)


class EventClassificationSummary(BaseModel):
    run_id: str
    status: str
    articles_processed: int
    events_extracted: int
    events_clustered: int
    method: str
    error_message: Optional[str] = None
