"""Unit tests for Phase 3 Risk Classification Engine and Data Sufficiency Rules."""
import pytest
from app.classification.rules import (
    CLASS_GREEN,
    CLASS_AMBER,
    CLASS_RED,
    CLASS_INSUFFICIENT_DATA,
    FLAG_STATUS_FLAGGED,
    FLAG_STATUS_NOT_FLAGGED,
    FLAG_STATUS_INSUFFICIENT_DATA,
    PROTOTYPE_DISCLAIMER,
)
from app.classification.engine import classify_risk_score


# ===========================================================================
# 1. Exact Threshold Boundary Tests (COMPLETE data)
# ===========================================================================
def test_exact_boundary_zero_is_green():
    """Score 0.0 with COMPLETE data must classify as GREEN."""
    res = classify_risk_score(score=0.0, completeness="COMPLETE", evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.classification == CLASS_GREEN
    assert res.flag_status == FLAG_STATUS_NOT_FLAGGED
    assert res.anomaly_score == 0.0


def test_exact_boundary_19_is_green():
    """Score 19.0 with COMPLETE data must classify as GREEN."""
    res = classify_risk_score(score=19.0, completeness="COMPLETE", evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.classification == CLASS_GREEN
    assert res.flag_status == FLAG_STATUS_NOT_FLAGGED
    assert res.anomaly_score == 19.0


def test_exact_boundary_20_is_amber():
    """Score 20.0 with COMPLETE data must classify as AMBER."""
    res = classify_risk_score(score=20.0, completeness="COMPLETE", flagged_rules=["R2"], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.classification == CLASS_AMBER
    assert res.flag_status == FLAG_STATUS_FLAGGED
    assert res.anomaly_score == 20.0


def test_exact_boundary_49_is_amber():
    """Score 49.0 with COMPLETE data must classify as AMBER."""
    res = classify_risk_score(score=49.0, completeness="COMPLETE", flagged_rules=["R1"], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.classification == CLASS_AMBER
    assert res.flag_status == FLAG_STATUS_FLAGGED
    assert res.anomaly_score == 49.0


def test_exact_boundary_50_is_red():
    """Score 50.0 with COMPLETE data must classify as RED."""
    res = classify_risk_score(score=50.0, completeness="COMPLETE", flagged_rules=["R1", "R2"], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.classification == CLASS_RED
    assert res.flag_status == FLAG_STATUS_FLAGGED
    assert res.anomaly_score == 50.0


def test_exact_boundary_100_is_red():
    """Score 100.0 with COMPLETE data must classify as RED."""
    res = classify_risk_score(score=100.0, completeness="COMPLETE", flagged_rules=["R1", "R2", "R3", "R4"], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.classification == CLASS_RED
    assert res.flag_status == FLAG_STATUS_FLAGGED
    assert res.anomaly_score == 100.0


# ===========================================================================
# 2. Out-of-Bounds Score Rejection Tests
# ===========================================================================
def test_reject_negative_score():
    """Score < 0 must be rejected and return INSUFFICIENT_DATA."""
    res = classify_risk_score(score=-5.0, completeness="COMPLETE")
    assert res.classification == CLASS_INSUFFICIENT_DATA
    assert res.anomaly_score == -5.0
    assert any("outside valid boundary" in w.lower() for w in res.warnings)


def test_reject_score_above_100():
    """Score > 100 must be rejected and return INSUFFICIENT_DATA."""
    res = classify_risk_score(score=105.0, completeness="COMPLETE")
    assert res.classification == CLASS_INSUFFICIENT_DATA
    assert res.anomaly_score == 105.0
    assert any("outside valid boundary" in w.lower() for w in res.warnings)


# ===========================================================================
# 3. Data Sufficiency & Missing Value Policy Tests
# ===========================================================================
def test_unavailable_completeness_returns_insufficient_data():
    """Completeness UNAVAILABLE must return INSUFFICIENT_DATA."""
    res = classify_risk_score(score=0.0, completeness="UNAVAILABLE")
    assert res.classification == CLASS_INSUFFICIENT_DATA
    assert "UNAVAILABLE" in res.explanation
    assert res.anomaly_score == 0.0


def test_partial_completeness_never_assigns_green():
    """
    CRITICAL POLICY:
    If completeness is PARTIAL, return INSUFFICIENT_DATA by default.
    Never assign GREEN simply because available evidence is insufficient.
    """
    # Even with a low score of 0.0 or 10.0, incomplete data cannot be classified as GREEN
    res_low = classify_risk_score(
        score=0.0,
        completeness="PARTIAL",
        evaluated_rules=["R1", "R2"],
        insufficient_rules=["R3", "R4"],
    )
    assert res_low.classification == CLASS_INSUFFICIENT_DATA
    assert res_low.classification != CLASS_GREEN
    assert res_low.anomaly_score == 0.0
    assert "PARTIAL" in res_low.explanation
    assert "R3, R4" in res_low.explanation


def test_partial_completeness_preserves_numerical_score():
    """Preserves original numerical score even when classification is INSUFFICIENT_DATA."""
    res_high = classify_risk_score(
        score=50.0,
        completeness="PARTIAL",
        flagged_rules=["R1", "R2"],
        evaluated_rules=["R1", "R2"],
        insufficient_rules=["R3", "R4"],
    )
    assert res_high.classification == CLASS_INSUFFICIENT_DATA
    assert res_high.anomaly_score == 50.0
    assert res_high.flag_status == FLAG_STATUS_FLAGGED


def test_missing_score_and_inconsistent_completeness():
    """Missing score or inconsistent completeness returns INSUFFICIENT_DATA with warning."""
    res_none_score = classify_risk_score(score=None, completeness="COMPLETE")
    assert res_none_score.classification == CLASS_INSUFFICIENT_DATA
    assert res_none_score.anomaly_score is None

    res_invalid_comp = classify_risk_score(score=25.0, completeness="INVALID_STATUS")
    assert res_invalid_comp.classification == CLASS_INSUFFICIENT_DATA
    assert any("inconsistent" in res_invalid_comp.explanation.lower() or "unrecognized" in w.lower() for w in res_invalid_comp.warnings)


# ===========================================================================
# 4. Flag Status Separation Tests
# ===========================================================================
def test_flag_status_separation_from_color():
    """Flag status is FLAGGED when >=1 rule flags, NOT_FLAGGED when 0 rules flag."""
    res_flagged = classify_risk_score(score=30.0, completeness="COMPLETE", flagged_rules=["R1"], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res_flagged.flag_status == FLAG_STATUS_FLAGGED
    assert res_flagged.classification == CLASS_AMBER

    res_not_flagged = classify_risk_score(score=0.0, completeness="COMPLETE", flagged_rules=[], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res_not_flagged.flag_status == FLAG_STATUS_NOT_FLAGGED
    assert res_not_flagged.classification == CLASS_GREEN


def test_prototype_disclaimer_present():
    """Verify prototype disclaimer is included in classification results."""
    res = classify_risk_score(score=50.0, completeness="COMPLETE", flagged_rules=["R1", "R2"], evaluated_rules=["R1", "R2", "R3", "R4"])
    assert res.disclaimer == PROTOTYPE_DISCLAIMER
    assert "not been statistically validated" in res.disclaimer.lower()
