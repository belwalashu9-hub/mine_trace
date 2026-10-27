"""Pydantic schemas for Phase 3 Risk Classification."""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict

from app.classification.rules import PROTOTYPE_DISCLAIMER


class ClassificationCategoryMetadata(BaseModel):
    category: str
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    description: str


class FlagStatusMetadata(BaseModel):
    status: str
    description: str


class ClassificationThresholdsResponse(BaseModel):
    version: str
    disclaimer: str
    categories: List[ClassificationCategoryMetadata]
    flag_statuses: List[FlagStatusMetadata]


class ClassifyRequest(BaseModel):
    analysis_id: Optional[str] = Field(default=None, description="Classify a specific analysis by its UUID.")
    commodity_code: Optional[str] = Field(default=None, description="Filter analyses to classify by commodity code.")
    only_unclassified: bool = Field(default=False, description="Classify only analyses that do not yet have a classification.")
    limit: int = Field(default=100, ge=1, le=500, description="Max number of records to classify.")


class ClassificationResultResponse(BaseModel):
    analysis_id: str
    commodity_code: str
    period: str
    reporter_country_code: str
    partner_country_code: str
    anomaly_score: Optional[float]
    score_completeness: Optional[str]
    classification: str  # GREEN, AMBER, RED, INSUFFICIENT_DATA
    flag_status: str     # FLAGGED, NOT_FLAGGED, INSUFFICIENT_DATA
    explanation: str
    warnings: List[str] = Field(default_factory=list)
    disclaimer: str = PROTOTYPE_DISCLAIMER

    model_config = ConfigDict(from_attributes=True)


class ClassifiedAnalysisListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    analyses: List[ClassificationResultResponse]


class ClassificationSummaryResponse(BaseModel):
    total_analyses: int
    classified_count: int
    unclassified_count: int
    classification_breakdown: Dict[str, int]
    flag_status_breakdown: Dict[str, int]
    disclaimer: str = PROTOTYPE_DISCLAIMER
