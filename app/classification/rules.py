"""Classification constants, prototype thresholds, and metadata for Phase 3."""
from typing import Dict, Any

# Classification Categories
CLASS_GREEN = "GREEN"
CLASS_AMBER = "AMBER"
CLASS_RED = "RED"
CLASS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Flag Statuses (separate from color classification)
FLAG_STATUS_FLAGGED = "FLAGGED"
FLAG_STATUS_NOT_FLAGGED = "NOT_FLAGGED"
FLAG_STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Prototype Threshold Boundaries
# 0 - 19 => GREEN
# 20 - 49 => AMBER
# 50 - 100 => RED
GREEN_SCORE_MAX = 19.0
AMBER_SCORE_MIN = 20.0
AMBER_SCORE_MAX = 49.0
RED_SCORE_MIN = 50.0
RED_SCORE_MAX = 100.0

PROTOTYPE_DISCLAIMER = (
    "These are prototype thresholds configured for investigative risk triage and supply-chain "
    "provenance monitoring. They have not been statistically validated as probabilities of fraud, "
    "sanctions evasion, or legal wrongdoing. Missing data is never interpreted as a low-risk result."
)

CLASSIFICATION_THRESHOLDS_METADATA: Dict[str, Any] = {
    "version": "1.0-prototype",
    "disclaimer": PROTOTYPE_DISCLAIMER,
    "categories": [
        {
            "category": CLASS_GREEN,
            "min_score": 0.0,
            "max_score": GREEN_SCORE_MAX,
            "description": "Low anomaly divergence across evaluated rules (0–19). Requires complete data sufficiency.",
        },
        {
            "category": CLASS_AMBER,
            "min_score": AMBER_SCORE_MIN,
            "max_score": AMBER_SCORE_MAX,
            "description": "Moderate anomaly divergence triggering one primary risk flag (20–49).",
        },
        {
            "category": CLASS_RED,
            "min_score": RED_SCORE_MIN,
            "max_score": RED_SCORE_MAX,
            "description": "Substantial anomaly divergence triggering multiple risk flags (50–100).",
        },
        {
            "category": CLASS_INSUFFICIENT_DATA,
            "description": (
                "Data sufficiency requirements not met (score completeness is PARTIAL or UNAVAILABLE, "
                "or score is missing/out-of-bounds). Never assigned GREEN simply because data is missing."
            ),
        },
    ],
    "flag_statuses": [
        {
            "status": FLAG_STATUS_FLAGGED,
            "description": "One or more evaluated scoring rules returned FLAG.",
        },
        {
            "status": FLAG_STATUS_NOT_FLAGGED,
            "description": "Zero evaluated scoring rules returned FLAG.",
        },
    ],
}
