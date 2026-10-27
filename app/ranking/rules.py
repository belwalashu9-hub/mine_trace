"""Ranking policy definitions, tie-breaker documentation, and constants for Phase 4."""

RANKING_POLICY_VERSION = "1.0"

# Scope constants
SCOPE_GLOBAL = "GLOBAL"
SCOPE_FILTERED = "FILTERED"

# Tie-breaker policy definition
TIE_BREAKER_PRIMARY = "combined_anomaly_score DESC"
TIE_BREAKER_SECONDARY = "created_at DESC"
TIE_BREAKER_TERTIARY = "analysis_id ASC"

TIE_BREAKER_POLICY = (
    f"1. {TIE_BREAKER_PRIMARY} (highest risk score ranked first); "
    f"2. {TIE_BREAKER_SECONDARY} (more recently evaluated record takes precedence); "
    f"3. {TIE_BREAKER_TERTIARY} (deterministic lexicographical UUID ordering)."
)

# Completeness constants
COMPLETENESS_COMPLETE = "COMPLETE"
COMPLETENESS_PARTIAL = "PARTIAL"
COMPLETENESS_UNAVAILABLE = "UNAVAILABLE"

# Exclusion reasons
EXCLUSION_PARTIAL = (
    "Excluded from primary ranking: Risk analysis completeness is PARTIAL because "
    "one or more required scoring rules had insufficient data."
)
EXCLUSION_UNAVAILABLE = (
    "Excluded from primary ranking: Risk analysis completeness is UNAVAILABLE because "
    "no scoring rules could be evaluated."
)
EXCLUSION_INVALID_SCORE = (
    "Excluded from primary ranking: Anomaly score is missing, corrupt, or outside "
    "valid bounds [0, 100]."
)
EXCLUSION_CORRUPT_ANALYSIS = (
    "Excluded from primary ranking: Analysis record is corrupt or lacks required metadata."
)

RANKING_DISCLAIMER = (
    "Rankings are deterministic indicators based on heuristic anomaly scoring rules (Phase 2) "
    "and prototype classification thresholds (Phase 3). Rankings serve as an operational triage "
    "and prioritization tool and do not constitute verified findings of wrongdoing or regulatory violations."
)
