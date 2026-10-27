"""Pydantic schemas for Phase 4 Risk Ranking Engine."""
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict

from app.ranking.rules import (
    RANKING_POLICY_VERSION,
    TIE_BREAKER_POLICY,
    RANKING_DISCLAIMER,
)


class RankingEntry(BaseModel):
    """An individual ranked risk analysis record."""
    rank: int = Field(description="1-based ordinal rank within the query scope.")
    analysis_id: str
    trade_record_id: Optional[int] = None
    commodity_code: str
    mineral_type: Optional[str] = None
    reporter_country_code: str
    partner_country_code: str
    period: str
    anomaly_score: float
    score_completeness: str
    classification: Optional[str] = None
    flag_status: Optional[str] = None
    sanctions_status: str = "UNKNOWN"
    evaluated_rules: List[str] = Field(default_factory=list)
    flagged_rules: List[str] = Field(default_factory=list)
    insufficient_rules: List[str] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RankingResponse(BaseModel):
    """Primary ranking API response."""
    policy_version: str = RANKING_POLICY_VERSION
    tie_breaker_policy: str = TIE_BREAKER_POLICY
    scope: str = Field(description="'GLOBAL' if no domain filters applied, else 'FILTERED'.")
    page: int
    page_size: int
    total_eligible: int
    total_pages: int
    has_next: bool
    has_prev: bool
    active_filters: Dict[str, Any] = Field(default_factory=dict)
    rankings: List[RankingEntry] = Field(default_factory=list)
    disclaimer: str = RANKING_DISCLAIMER


class IncompleteRecordEntry(BaseModel):
    """A record excluded from the primary ranking due to incomplete or corrupt scoring."""
    analysis_id: str
    trade_record_id: Optional[int] = None
    commodity_code: str
    mineral_type: Optional[str] = None
    reporter_country_code: str
    partner_country_code: str
    period: str
    anomaly_score: Optional[float] = None
    score_completeness: str
    classification: Optional[str] = None
    insufficient_rules: List[str] = Field(default_factory=list)
    evaluated_rules: List[str] = Field(default_factory=list)
    exclusion_reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncompleteRankingResponse(BaseModel):
    """Response containing records excluded from the primary ranking."""
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool
    records: List[IncompleteRecordEntry] = Field(default_factory=list)
    disclaimer: str = RANKING_DISCLAIMER


class RankingSummaryResponse(BaseModel):
    """Aggregate statistical summary across all analyses in the system."""
    total_analyses: int
    eligible_complete_count: int
    partial_excluded_count: int
    unavailable_excluded_count: int
    invalid_score_count: int
    highest_score: Optional[float] = None
    lowest_score: Optional[float] = None
    average_score: Optional[float] = None
    classification_breakdown: Dict[str, int] = Field(default_factory=dict)
    flag_status_breakdown: Dict[str, int] = Field(default_factory=dict)
    disclaimer: str = RANKING_DISCLAIMER


class RecordRankLookupResponse(BaseModel):
    """Detailed rank position and contextual status for a specific analysis record."""
    analysis_id: str
    is_eligible: bool
    rank: Optional[int] = None
    total_eligible: int
    anomaly_score: Optional[float] = None
    score_completeness: str
    classification: Optional[str] = None
    flag_status: Optional[str] = None
    exclusion_reason: Optional[str] = None
    commodity_code: str
    mineral_type: Optional[str] = None
    period: str
    reporter_country_code: str
    partner_country_code: str
    created_at: datetime
    tie_breaker_policy: str = TIE_BREAKER_POLICY
    disclaimer: str = RANKING_DISCLAIMER


class CreateSnapshotRequest(BaseModel):
    """Request payload to create a persistent point-in-time ranking snapshot."""
    name: Optional[str] = Field(default=None, description="Optional label for the snapshot.")
    description: Optional[str] = Field(default=None, description="Optional description.")
    commodity_code: Optional[str] = None
    mineral_type: Optional[str] = None
    reporter_country_code: Optional[str] = None
    partner_country_code: Optional[str] = None
    period: Optional[str] = None
    classification: Optional[str] = None
    flag_status: Optional[str] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None


class SnapshotItemResponse(BaseModel):
    """Ranked item within a snapshot."""
    rank: int
    analysis_id: str
    anomaly_score: float
    classification: Optional[str] = None
    flag_status: Optional[str] = None
    commodity_code: str
    mineral_type: Optional[str] = None
    reporter_country_code: str
    partner_country_code: str
    period: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SnapshotDetailResponse(BaseModel):
    """Snapshot detail response including ranked items."""
    snapshot_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    policy_version: str
    filters_applied: Optional[Dict[str, Any]] = None
    total_eligible_count: int
    excluded_count: int
    exclusion_reasons: Optional[Dict[str, int]] = None
    created_at: datetime
    items: List[SnapshotItemResponse] = Field(default_factory=list)


class SnapshotListItem(BaseModel):
    """Summary item for listing snapshots."""
    snapshot_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    policy_version: str
    total_eligible_count: int
    excluded_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SnapshotListResponse(BaseModel):
    """List of persisted ranking snapshots."""
    total: int
    snapshots: List[SnapshotListItem] = Field(default_factory=list)
