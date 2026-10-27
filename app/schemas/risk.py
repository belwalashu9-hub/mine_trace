"""Pydantic schemas for Phase 2 Risk Detection and Scoring."""
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class RuleMetadataResponse(BaseModel):
    rule_id: str
    name: str
    version: str
    weight: int
    formula: str
    threshold: str
    description: str


class RuleResultResponse(BaseModel):
    rule_id: str
    rule_name: str
    rule_version: str
    weight: int
    outcome: str
    threshold: str
    formula: str
    calculated_value: Optional[float] = None
    input_values: Dict[str, Any] = Field(default_factory=dict)
    explanation: str
    warnings: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RiskAnalysisResponse(BaseModel):
    analysis_id: str
    trade_record_id: Optional[int] = None
    commodity_code: str
    mineral_type: Optional[str] = None
    reporter_country_code: str
    partner_country_code: str
    period: str
    combined_anomaly_score: float
    score_completeness: str  # COMPLETE, PARTIAL, UNAVAILABLE
    evaluated_rules: List[str]
    insufficient_rules: List[str]
    flagged_rules: List[str]
    sanctions_status: str   # REVIEW_MATCH, NO_IDENTIFIED_MATCH, UNKNOWN
    sanctions_reference: Optional[str] = None
    classification: Optional[str] = None  # GREEN, AMBER, RED, INSUFFICIENT_DATA
    flag_status: Optional[str] = None     # FLAGGED, NOT_FLAGGED, INSUFFICIENT_DATA
    classification_explanation: Optional[str] = None
    created_at: datetime
    rule_results: List[RuleResultResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RiskAnalysisListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    analyses: List[RiskAnalysisResponse]


class RiskAnalysisRequest(BaseModel):
    """Parameters for triggering risk evaluation across local database records."""
    trade_record_id: Optional[int] = Field(
        default=None,
        description="Analyze a single specific trade record by ID.",
    )
    commodity_code: Optional[str] = Field(
        default=None,
        description="Filter records to analyze by HS code (e.g. '283691').",
    )
    reporter_country_code: Optional[str] = Field(
        default=None,
        description="Filter records by reporting country ISO code.",
    )
    period_year: Optional[int] = Field(
        default=None,
        description="Filter records by period year.",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of records to analyze in this run.",
    )
    entity_name: Optional[str] = Field(
        default=None,
        description="Optional company or entity name for R5 sanctions screening.",
    )


class RiskSummaryResponse(BaseModel):
    total_analyses: int
    complete_scores_count: int
    partial_scores_count: int
    unavailable_scores_count: int
    average_anomaly_score: Optional[float] = None
    flagged_rules_breakdown: Dict[str, int]
    sanctions_status_breakdown: Dict[str, int]
