"""Pydantic schemas for Model 2: Geopolitical Risk Monitoring (GDELT DOC 2.0)."""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl


class GeopoliticalCategory(str, Enum):
    """The 9 monitored geopolitical event categories for mineral supply chain risk."""
    ARMED_CONFLICT = "armed_conflict"
    POLITICAL_INSTABILITY = "political_instability"
    MINING_STRIKES = "mining_strikes"
    PRODUCTION_DISRUPTIONS = "production_disruptions"
    TRADE_RESTRICTIONS = "trade_restrictions"
    PORT_CLOSURES = "port_closures"
    TRANSPORT_DISRUPTIONS = "transport_disruptions"
    SANCTIONS_ANNOUNCEMENTS = "sanctions_announcements"
    NATURAL_DISASTERS = "natural_disasters"


class CriticalMineral(str, Enum):
    """Monitored critical mineral commodities."""
    COBALT = "cobalt"
    LITHIUM = "lithium"
    NICKEL = "nickel"
    NATURAL_GRAPHITE = "natural_graphite"


class GDELTArticleRaw(BaseModel):
    """Raw article metadata as returned by GDELT DOC 2.0 API."""
    url: Optional[str] = None
    url_mobile: Optional[str] = None
    title: Optional[str] = None
    seendate: Optional[str] = None
    socialimage: Optional[str] = None
    domain: Optional[str] = None
    language: Optional[str] = None
    sourcecountry: Optional[str] = None


class NormalizedGeopoliticalEvent(BaseModel):
    """
    Normalized internal representation of a geopolitical news event.
    Conforms to the MineTrace Model 2 event schema.
    """
    event_id: str = Field(description="Deterministic stable hash identifier derived from canonical URL")
    title: Optional[str] = Field(default=None, description="Article headline")
    source_url: str = Field(description="Canonical source URL")
    source_domain: Optional[str] = Field(default=None, description="Publishing news domain")
    source_country: Optional[str] = Field(default=None, description="Publishing source country from GDELT")
    affected_country: Optional[str] = Field(default=None, description="Country where event occurred (null in Phase 1)")
    mineral: Optional[str] = Field(default=None, description="Detected mineral keyword (null in Phase 1)")
    event_type: Optional[str] = Field(default=None, description="Classified event type (null until Phase 3)")
    event_date: Optional[str] = Field(default=None, description="Confirmed event date (null in Phase 1)")
    publication_date: Optional[str] = Field(default=None, description="Article publication date if reliably present")
    gdelt_seen_date: Optional[str] = Field(default=None, description="ISO-8601 timestamp when GDELT indexed the article")
    retrieved_at: str = Field(description="ISO-8601 timestamp when retrieved by MineTrace")
    classification_status: str = Field(default="pending", description="Event classification lifecycle status")
    provider: str = Field(default="gdelt_doc_2", description="Data provider identifier")
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Preserved source metadata for evidence audits")


class GDELTFetchResponse(BaseModel):
    """Summary of a GDELT fetch operation."""
    query: str
    timespan: str
    total_retrieved: int
    valid_articles_count: int
    retrieved_at: str
    provider: str = "gdelt_doc_2"
    events: List[NormalizedGeopoliticalEvent]
    warning: Optional[str] = None


class GDELTIngestionSummary(BaseModel):
    """Execution summary and metrics for a GDELT news ingestion run."""
    run_id: int
    status: str
    provider: str = "gdelt_doc_2"
    query_category: Optional[str] = None
    lookback_window: Optional[str] = None
    fetched_count: int = 0
    valid_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0
    error_message: Optional[str] = None

