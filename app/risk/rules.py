"""Risk rules definitions, metadata, formulas, and threshold configurations."""
from dataclasses import dataclass
from typing import Dict, Any, List

# Rule IDs
RULE_R1 = "R1"
RULE_R2 = "R2"
RULE_R3 = "R3"
RULE_R4 = "R4"
RULE_R5 = "R5"

# Outcomes
OUTCOME_FLAG = "FLAG"
OUTCOME_NOT_FLAGGED = "NOT_FLAGGED"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Sanctions Specific Outcomes (R5)
SANCTIONS_REVIEW_MATCH = "REVIEW_MATCH"
SANCTIONS_NO_IDENTIFIED_MATCH = "NO_IDENTIFIED_MATCH"
SANCTIONS_UNKNOWN = "UNKNOWN"

# Score Completeness Statuses
COMPLETENESS_COMPLETE = "COMPLETE"
COMPLETENESS_PARTIAL = "PARTIAL"
COMPLETENESS_UNAVAILABLE = "UNAVAILABLE"

# Rule Weights (Total = 100 for anomaly score; R5 is excluded from numeric score)
RULE_WEIGHTS = {
    RULE_R1: 30,
    RULE_R2: 20,
    RULE_R3: 30,
    RULE_R4: 20,
    RULE_R5: 0,
}

# Rule Thresholds
THRESHOLD_R1_PERCENT = 30.0   # Greater than 30%
THRESHOLD_R2_PERCENT = 200.0  # Greater than 200%
THRESHOLD_R3_PERCENT = 80.0   # Greater than 80%
THRESHOLD_R4_PERCENT = 60.0   # Greater than 60%

# Minimum sample size required to calculate median unit price
MIN_UNIT_PRICE_SAMPLE_SIZE = 3


@dataclass(frozen=True)
class RuleMetadata:
    rule_id: str
    name: str
    version: str
    weight: int
    formula: str
    threshold: str
    description: str


RULE_CATALOG: Dict[str, RuleMetadata] = {
    RULE_R1: RuleMetadata(
        rule_id=RULE_R1,
        name="Mirror Trade Gap",
        version="1.0",
        weight=30,
        formula="abs(export_value - import_value) / max(export_value, import_value) * 100",
        threshold="> 30.0%",
        description="Detects significant discrepancies between reported exports and corresponding partner imports.",
    ),
    RULE_R2: RuleMetadata(
        rule_id=RULE_R2,
        name="Volume Spike",
        version="1.0",
        weight=20,
        formula="(current_volume - previous_volume) / previous_volume * 100",
        threshold="> 200.0%",
        description="Detects rapid trade volume increases exceeding historical baseline.",
    ),
    RULE_R3: RuleMetadata(
        rule_id=RULE_R3,
        name="Route Concentration",
        version="1.0",
        weight=30,
        formula="partner_import_volume / total_comparable_import_volume * 100",
        threshold="> 80.0%",
        description="Identifies excessive critical mineral import dependence on a single trading partner.",
    ),
    RULE_R4: RuleMetadata(
        rule_id=RULE_R4,
        name="Unusual Unit Price",
        version="1.0",
        weight=20,
        formula="abs(unit_price - comparable_median_price) / comparable_median_price * 100",
        threshold="> 60.0%",
        description="Detects transaction unit prices (USD/kg) that deviate significantly from comparable commodity median.",
    ),
    RULE_R5: RuleMetadata(
        rule_id=RULE_R5,
        name="Sanctions Exposure Status",
        version="1.0",
        weight=0,
        formula="Exact or normalized string matching against official OFAC SDN names and aliases",
        threshold="Match against OFAC SDN List (Separate from numerical anomaly score)",
        description="Screens identified entities against local OFAC sanctions records; returns REVIEW_MATCH, NO_IDENTIFIED_MATCH, or UNKNOWN.",
    ),
}


def get_rule_catalog_list() -> List[Dict[str, Any]]:
    """Returns serialized catalog of all rules for API exposure."""
    return [
        {
            "rule_id": meta.rule_id,
            "name": meta.name,
            "version": meta.version,
            "weight": meta.weight,
            "formula": meta.formula,
            "threshold": meta.threshold,
            "description": meta.description,
        }
        for meta in RULE_CATALOG.values()
    ]
