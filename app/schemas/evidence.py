"""Pydantic schemas for Phase 5 Evidence Generation and Validation."""
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict

from app.evidence.rules import EVIDENCE_DISCLAIMER, CALCULATION_TOLERANCE


class RuleEvidenceItem(BaseModel):
    """Detailed frozen snapshot of a single rule calculation and inputs."""
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


class SourceTraceability(BaseModel):
    """Traceability metadata linking analysis to the underlying trade flow."""
    trade_record_id: Optional[int] = None
    source_dataset_name: str
    source_record_id: Optional[str] = None
    source_reference_url: Optional[str] = None
    source_retrieval_timestamp: Optional[datetime] = None
    source_payload_snapshot: Dict[str, Any] = Field(default_factory=dict)


class ScoreEvidence(BaseModel):
    """Aggregated anomaly score outputs and sufficiency status."""
    combined_anomaly_score: float
    score_completeness: str
    evaluated_rules: List[str] = Field(default_factory=list)
    insufficient_rules: List[str] = Field(default_factory=list)
    flagged_rules: List[str] = Field(default_factory=list)
    sanctions_status: str
    sanctions_reference: Optional[str] = None


class ClassificationEvidence(BaseModel):
    """Phase 3 classification metadata and thresholds applied."""
    classification: Optional[str] = None
    flag_status: Optional[str] = None
    explanation: Optional[str] = None
    policy_version: str = "1.0"
    thresholds_applied: Optional[Dict[str, Any]] = None


class RankingEvidence(BaseModel):
    """Phase 4 ranking position and eligibility context at analysis time."""
    snapshot_id: Optional[str] = None
    rank: Optional[int] = None
    total_eligible: Optional[int] = None
    is_eligible: Optional[bool] = None
    exclusion_reason: Optional[str] = None
    ranking_policy_version: Optional[str] = None


class EvidenceSnapshotResponse(BaseModel):
    """Full versioned evidence snapshot object for an individual risk analysis."""
    evidence_id: str
    analysis_id: str
    schema_version: str = "1.0"
    created_at: datetime
    analysis_timestamp: datetime
    source_traceability: SourceTraceability
    score: ScoreEvidence
    classification: ClassificationEvidence
    ranking: Optional[RankingEvidence] = None
    rules: List[RuleEvidenceItem] = Field(default_factory=list)
    data_quality_warnings: List[str] = Field(default_factory=list)
    validation_status: str
    last_validated_at: Optional[datetime] = None
    disclaimer: str = EVIDENCE_DISCLAIMER

    model_config = ConfigDict(from_attributes=True)


class ValidationCheckResult(BaseModel):
    """Individual rule or consistency verification check."""
    check_name: str
    passed: bool
    message: str
    details: Optional[Dict[str, Any]] = None


class EvidenceValidationResponse(BaseModel):
    """Complete validation assessment result for an evidence snapshot."""
    analysis_id: str
    evidence_id: Optional[str] = None
    validation_status: str  # VALID, INVALID, WARNINGS
    validation_timestamp: datetime
    checks_performed: List[ValidationCheckResult] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unavailable_checks: List[str] = Field(default_factory=list)
    tolerance_used: float = CALCULATION_TOLERANCE
