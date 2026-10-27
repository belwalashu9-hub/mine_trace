"""Constants, definitions, and rule specifications for Phase 5 Evidence & Audit."""

EVIDENCE_SCHEMA_VERSION = "1.0"
CALCULATION_TOLERANCE = 1e-4

# Operational Audit Event Types
EVENT_TRADE_INGESTION_COMPLETED = "TRADE_INGESTION_COMPLETED"
EVENT_TRADE_INGESTION_FAILED = "TRADE_INGESTION_FAILED"
EVENT_SANCTIONS_INGESTION_COMPLETED = "SANCTIONS_INGESTION_COMPLETED"
EVENT_SANCTIONS_INGESTION_FAILED = "SANCTIONS_INGESTION_FAILED"
EVENT_RISK_ANALYSIS_CREATED = "RISK_ANALYSIS_CREATED"
EVENT_CLASSIFICATION_CREATED = "CLASSIFICATION_CREATED"
EVENT_RANKING_SNAPSHOT_CREATED = "RANKING_SNAPSHOT_CREATED"
EVENT_EVIDENCE_SNAPSHOT_GENERATED = "EVIDENCE_SNAPSHOT_GENERATED"
EVENT_EVIDENCE_VALIDATION_PASSED = "EVIDENCE_VALIDATION_PASSED"
EVENT_EVIDENCE_VALIDATION_FAILED = "EVIDENCE_VALIDATION_FAILED"

ALL_EVENT_TYPES = [
    EVENT_TRADE_INGESTION_COMPLETED,
    EVENT_TRADE_INGESTION_FAILED,
    EVENT_SANCTIONS_INGESTION_COMPLETED,
    EVENT_SANCTIONS_INGESTION_FAILED,
    EVENT_RISK_ANALYSIS_CREATED,
    EVENT_CLASSIFICATION_CREATED,
    EVENT_RANKING_SNAPSHOT_CREATED,
    EVENT_EVIDENCE_SNAPSHOT_GENERATED,
    EVENT_EVIDENCE_VALIDATION_PASSED,
    EVENT_EVIDENCE_VALIDATION_FAILED,
]

# Validation Check Keys
CHECK_ANALYSIS_EXISTS = "analysis_exists"
CHECK_RULE_IDS_VALID = "rule_ids_and_versions_valid"
CHECK_THRESHOLDS_MATCH = "thresholds_match_policy"
CHECK_CALCULATIONS_MATCH = "rule_calculations_consistency"
CHECK_SCORE_WEIGHTS_MATCH = "combined_score_consistency"
CHECK_COMPLETENESS_CONSISTENT = "completeness_status_consistency"
CHECK_CLASSIFICATION_CONSISTENT = "classification_reference_consistency"
CHECK_RANKING_REFERENCE = "ranking_reference_consistency"
CHECK_SOURCE_INTEGRITY = "source_integrity"

# Validation Status Outcomes
STATUS_VALID = "VALID"
STATUS_INVALID = "INVALID"
STATUS_WARNINGS = "WARNINGS"
STATUS_UNVALIDATED = "UNVALIDATED"

# Audit and Evidence Disclaimers
AUDIT_LOG_LIMITATIONS = (
    "Audit events are recorded as append-only application-level database entries. "
    "They provide operational traceability and process accountability within the local application, "
    "but do not constitute cryptographically signed, immutable blockchain or WORM storage."
)

EVIDENCE_DISCLAIMER = (
    "Evidence snapshots capture the frozen historical input parameters, rule calculations, "
    "and classification thresholds at the time of assessment. Evidence retrieval does not "
    "recalculate scores, preserving full backward reproducibility even if live trade records are updated."
)
