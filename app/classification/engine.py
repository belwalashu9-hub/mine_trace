"""Pure deterministic risk classification engine for Phase 3."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from app.classification.rules import (
    CLASS_GREEN,
    CLASS_AMBER,
    CLASS_RED,
    CLASS_INSUFFICIENT_DATA,
    FLAG_STATUS_FLAGGED,
    FLAG_STATUS_NOT_FLAGGED,
    FLAG_STATUS_INSUFFICIENT_DATA,
    GREEN_SCORE_MAX,
    AMBER_SCORE_MIN,
    AMBER_SCORE_MAX,
    RED_SCORE_MIN,
    RED_SCORE_MAX,
    PROTOTYPE_DISCLAIMER,
)


@dataclass
class ClassificationResult:
    """Outcome of risk classification evaluation."""
    classification: str           # GREEN, AMBER, RED, INSUFFICIENT_DATA
    flag_status: str              # FLAGGED, NOT_FLAGGED, INSUFFICIENT_DATA
    anomaly_score: Optional[float]
    score_completeness: Optional[str]
    explanation: str
    warnings: List[str] = field(default_factory=list)
    disclaimer: str = PROTOTYPE_DISCLAIMER


def classify_risk_score(
    score: Optional[float],
    completeness: Optional[str],
    flagged_rules: Optional[List[str]] = None,
    evaluated_rules: Optional[List[str]] = None,
    insufficient_rules: Optional[List[str]] = None,
) -> ClassificationResult:
    """
    Classifies a numerical anomaly score into GREEN, AMBER, RED, or INSUFFICIENT_DATA.
    
    Guarantees:
      - Deterministic and reproducible.
      - Never interprets missing or partial evidence as low risk or GREEN.
      - Strictly enforces boundary conditions:
          0 <= score <= 19   => GREEN (only if completeness == COMPLETE)
          20 <= score <= 49  => AMBER
          50 <= score <= 100 => RED
      - Rejects scores < 0 or > 100.
      - Keeps rule-based anomaly flag status (FLAGGED vs NOT_FLAGGED) separate from color tier.
    """
    flags = flagged_rules or []
    evaluated = evaluated_rules or []
    insufficient = insufficient_rules or []
    warnings: List[str] = []

    # Determine separate flag status
    if len(flags) > 0:
        flag_status = FLAG_STATUS_FLAGGED
    elif len(evaluated) > 0:
        flag_status = FLAG_STATUS_NOT_FLAGGED
    else:
        flag_status = FLAG_STATUS_INSUFFICIENT_DATA

    # Guardrail 1: Score must be valid float
    if score is None:
        warnings.append("Anomaly score is missing.")
        return ClassificationResult(
            classification=CLASS_INSUFFICIENT_DATA,
            flag_status=flag_status,
            anomaly_score=None,
            score_completeness=completeness,
            explanation="INSUFFICIENT_DATA: Numerical anomaly score is missing. A conclusive classification cannot be assigned.",
            warnings=warnings,
        )

    # Guardrail 2: Score boundary validation [0, 100]
    if score < 0.0 or score > 100.0:
        warnings.append(f"Anomaly score {score} is outside valid boundary [0, 100].")
        return ClassificationResult(
            classification=CLASS_INSUFFICIENT_DATA,
            flag_status=flag_status,
            anomaly_score=score,
            score_completeness=completeness,
            explanation=f"INSUFFICIENT_DATA: Anomaly score ({score}) is invalid (must be between 0 and 100).",
            warnings=warnings,
        )

    norm_comp = (completeness or "").strip().upper()

    # Guardrail 3: Data Sufficiency - UNAVAILABLE
    if norm_comp == "UNAVAILABLE":
        warnings.append("Score completeness is UNAVAILABLE; zero rules could be evaluated.")
        return ClassificationResult(
            classification=CLASS_INSUFFICIENT_DATA,
            flag_status=flag_status,
            anomaly_score=score,
            score_completeness=completeness,
            explanation=(
                "INSUFFICIENT_DATA: Anomaly score completeness is UNAVAILABLE because none of the scoring "
                "rules had sufficient data to be evaluated. Missing data cannot be interpreted as low risk."
            ),
            warnings=warnings,
        )

    # Guardrail 4: Data Sufficiency - PARTIAL
    if norm_comp == "PARTIAL":
        missing_rule_str = f" ({', '.join(insufficient)})" if insufficient else ""
        warnings.append(f"Score completeness is PARTIAL; missing rules: {', '.join(insufficient) if insufficient else 'one or more'}.")
        return ClassificationResult(
            classification=CLASS_INSUFFICIENT_DATA,
            flag_status=flag_status,
            anomaly_score=score,
            score_completeness=completeness,
            explanation=(
                f"INSUFFICIENT_DATA: Score completeness is PARTIAL because one or more scoring rules{missing_rule_str} "
                "could not be evaluated. By data sufficiency policy, incomplete assessments cannot be assigned a conclusive "
                f"color tier. Numerical score ({score:.1f}) is preserved for auditability."
            ),
            warnings=warnings,
        )

    # Guardrail 5: Unrecognized completeness status
    if norm_comp != "COMPLETE":
        warnings.append(f"Unrecognized completeness status '{completeness}'.")
        return ClassificationResult(
            classification=CLASS_INSUFFICIENT_DATA,
            flag_status=flag_status,
            anomaly_score=score,
            score_completeness=completeness,
            explanation=f"INSUFFICIENT_DATA: Inconsistent score completeness status '{completeness}'.",
            warnings=warnings,
        )

    # Valid COMPLETE score classification
    if score <= GREEN_SCORE_MAX:
        classification = CLASS_GREEN
        explanation = (
            f"GREEN: Anomaly score of {score:.1f} falls within the low-risk range (0–{GREEN_SCORE_MAX:.0f}) "
            "with complete data sufficiency across all 4 scoring rules."
        )
    elif score <= AMBER_SCORE_MAX:
        classification = CLASS_AMBER
        flag_detail = f" (flagged: {', '.join(flags)})" if flags else ""
        explanation = (
            f"AMBER: Anomaly score of {score:.1f} falls within the moderate-risk range ({AMBER_SCORE_MIN:.0f}–{AMBER_SCORE_MAX:.0f}), "
            f"indicating localized divergence{flag_detail}."
        )
    else:
        classification = CLASS_RED
        flag_detail = f" (flagged: {', '.join(flags)})" if flags else ""
        explanation = (
            f"RED: Anomaly score of {score:.1f} falls within the elevated-risk range ({RED_SCORE_MIN:.0f}–{RED_SCORE_MAX:.0f}), "
            f"reflecting multiple cumulative anomaly flags{flag_detail}."
        )

    return ClassificationResult(
        classification=classification,
        flag_status=flag_status,
        anomaly_score=score,
        score_completeness=completeness,
        explanation=explanation,
        warnings=warnings,
    )
