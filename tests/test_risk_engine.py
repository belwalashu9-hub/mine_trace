"""Unit tests for Phase 2 Risk Rules (R1 - R5) and Combined Scoring Engine."""
import pytest
from app.risk.rules import (
    RULE_R1,
    RULE_R2,
    RULE_R3,
    RULE_R4,
    RULE_R5,
    OUTCOME_FLAG,
    OUTCOME_NOT_FLAGGED,
    OUTCOME_INSUFFICIENT_DATA,
    SANCTIONS_REVIEW_MATCH,
    SANCTIONS_NO_IDENTIFIED_MATCH,
    SANCTIONS_UNKNOWN,
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    COMPLETENESS_UNAVAILABLE,
)
from app.risk.engine import (
    evaluate_mirror_trade_gap,
    evaluate_volume_spike,
    evaluate_route_concentration,
    evaluate_unusual_unit_price,
    evaluate_sanctions_exposure,
    calculate_combined_anomaly_score,
    RuleEvaluationResult,
)


class MockOfacRecord:
    def __init__(self, source_record_id, primary_name, aliases=None, programs=None):
        self.source_record_id = source_record_id
        self.primary_name = primary_name
        self.aliases = aliases
        self.programs = programs


# ===========================================================================
# 1. Rule R1: Mirror Trade Gap Tests
# ===========================================================================
def test_r1_above_threshold():
    """Export=100,000, Import=60,000 -> Gap=40% -> FLAG (>30%)."""
    res = evaluate_mirror_trade_gap(export_value=100000.0, import_value=60000.0)
    assert res.outcome == OUTCOME_FLAG
    assert res.calculated_value == 40.0
    assert "differ by 40.00%" in res.explanation


def test_r1_below_threshold():
    """Export=100,000, Import=80,000 -> Gap=20% -> NOT_FLAGGED."""
    res = evaluate_mirror_trade_gap(export_value=100000.0, import_value=80000.0)
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 20.0


def test_r1_exactly_at_threshold():
    """Export=100,000, Import=70,000 -> Gap=30.0% -> NOT_FLAGGED (>30% required)."""
    res = evaluate_mirror_trade_gap(export_value=100000.0, import_value=70000.0)
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 30.0


def test_r1_missing_values():
    """Missing export or import value -> INSUFFICIENT_DATA (never treat missing as 0)."""
    res1 = evaluate_mirror_trade_gap(export_value=None, import_value=50000.0)
    assert res1.outcome == OUTCOME_INSUFFICIENT_DATA
    assert res1.calculated_value is None

    res2 = evaluate_mirror_trade_gap(export_value=50000.0, import_value=None)
    assert res2.outcome == OUTCOME_INSUFFICIENT_DATA

    res3 = evaluate_mirror_trade_gap(export_value=None, import_value=None)
    assert res3.outcome == OUTCOME_INSUFFICIENT_DATA


def test_r1_both_values_zero():
    """Both values zero -> INSUFFICIENT_DATA (no division by zero)."""
    res = evaluate_mirror_trade_gap(export_value=0.0, import_value=0.0)
    assert res.outcome == OUTCOME_INSUFFICIENT_DATA
    assert res.calculated_value is None
    assert "zero" in res.explanation.lower()


# ===========================================================================
# 2. Rule R2: Volume Spike Tests
# ===========================================================================
def test_r2_above_threshold():
    """Previous=100, Current=350 -> Increase=250% -> FLAG (>200%)."""
    res = evaluate_volume_spike(current_volume=350.0, previous_volume=100.0, current_period="2023", previous_period="2022")
    assert res.outcome == OUTCOME_FLAG
    assert res.calculated_value == 250.0
    assert "surged by 250.00%" in res.explanation


def test_r2_below_threshold():
    """Previous=100, Current=250 -> Increase=150% -> NOT_FLAGGED."""
    res = evaluate_volume_spike(current_volume=250.0, previous_volume=100.0, current_period="2023", previous_period="2022")
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 150.0


def test_r2_exactly_at_threshold():
    """Previous=100, Current=300 -> Increase=200.0% -> NOT_FLAGGED (>200% required)."""
    res = evaluate_volume_spike(current_volume=300.0, previous_volume=100.0, current_period="2023", previous_period="2022")
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 200.0


def test_r2_volume_decrease():
    """Volume decrease must NOT be flagged as a positive volume spike."""
    res = evaluate_volume_spike(current_volume=50.0, previous_volume=100.0, current_period="2023", previous_period="2022")
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == -50.0
    assert "decreased" in res.explanation.lower()


def test_r2_missing_baseline_and_zero_baseline():
    """Missing or zero previous baseline -> INSUFFICIENT_DATA."""
    res_missing = evaluate_volume_spike(current_volume=500.0, previous_volume=None, current_period="2023", previous_period=None)
    assert res_missing.outcome == OUTCOME_INSUFFICIENT_DATA

    res_zero = evaluate_volume_spike(current_volume=500.0, previous_volume=0.0, current_period="2023", previous_period="2022")
    assert res_zero.outcome == OUTCOME_INSUFFICIENT_DATA


# ===========================================================================
# 3. Rule R3: Route Concentration Tests
# ===========================================================================
def test_r3_above_threshold():
    """Partner=900, Total=1000 -> Concentration=90% -> FLAG (>80%)."""
    res = evaluate_route_concentration(partner_import_volume=900.0, total_comparable_import_volume=1000.0)
    assert res.outcome == OUTCOME_FLAG
    assert res.calculated_value == 90.0


def test_r3_below_threshold():
    """Partner=700, Total=1000 -> Concentration=70% -> NOT_FLAGGED."""
    res = evaluate_route_concentration(partner_import_volume=700.0, total_comparable_import_volume=1000.0)
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 70.0


def test_r3_exactly_at_threshold():
    """Partner=800, Total=1000 -> Concentration=80.0% -> NOT_FLAGGED (>80% required)."""
    res = evaluate_route_concentration(partner_import_volume=800.0, total_comparable_import_volume=1000.0)
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 80.0


def test_r3_missing_or_zero_total():
    """Missing or zero total -> INSUFFICIENT_DATA."""
    res_none = evaluate_route_concentration(partner_import_volume=500.0, total_comparable_import_volume=None)
    assert res_none.outcome == OUTCOME_INSUFFICIENT_DATA

    res_zero = evaluate_route_concentration(partner_import_volume=0.0, total_comparable_import_volume=0.0)
    assert res_zero.outcome == OUTCOME_INSUFFICIENT_DATA


# ===========================================================================
# 4. Rule R4: Unusual Unit Price Tests
# ===========================================================================
def test_r4_above_threshold():
    """Unit price=170, Median=100 -> Deviation=70% -> FLAG (>60%)."""
    # 5 comparable prices with median 100
    comp_prices = [80.0, 90.0, 100.0, 110.0, 120.0]
    # Trade: 17,000 USD / 100 kg = 170 USD/kg
    res = evaluate_unusual_unit_price(trade_value=17000.0, net_weight_kg=100.0, comparison_unit_prices=comp_prices)
    assert res.outcome == OUTCOME_FLAG
    assert res.calculated_value == 70.0


def test_r4_below_threshold():
    """Unit price=140, Median=100 -> Deviation=40% -> NOT_FLAGGED."""
    comp_prices = [80.0, 90.0, 100.0, 110.0, 120.0]
    res = evaluate_unusual_unit_price(trade_value=14000.0, net_weight_kg=100.0, comparison_unit_prices=comp_prices)
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 40.0


def test_r4_exactly_at_threshold():
    """Unit price=160, Median=100 -> Deviation=60.0% -> NOT_FLAGGED (prompt example)."""
    comp_prices = [80.0, 90.0, 100.0, 110.0, 120.0]
    res = evaluate_unusual_unit_price(trade_value=16000.0, net_weight_kg=100.0, comparison_unit_prices=comp_prices)
    assert res.outcome == OUTCOME_NOT_FLAGGED
    assert res.calculated_value == 60.0


def test_r4_zero_weight_missing_and_insufficient_sample():
    """Zero weight, missing values, or too few comparable transactions -> INSUFFICIENT_DATA."""
    comp_prices = [100.0, 100.0, 100.0]
    # Zero weight
    res_zero_wt = evaluate_unusual_unit_price(trade_value=1000.0, net_weight_kg=0.0, comparison_unit_prices=comp_prices)
    assert res_zero_wt.outcome == OUTCOME_INSUFFICIENT_DATA

    # Missing trade value
    res_none = evaluate_unusual_unit_price(trade_value=None, net_weight_kg=50.0, comparison_unit_prices=comp_prices)
    assert res_none.outcome == OUTCOME_INSUFFICIENT_DATA

    # Only 2 comparable records when min required is 3
    res_few = evaluate_unusual_unit_price(trade_value=1000.0, net_weight_kg=10.0, comparison_unit_prices=[100.0, 105.0])
    assert res_few.outcome == OUTCOME_INSUFFICIENT_DATA
    assert "insufficient comparable records" in res_few.explanation.lower()


# ===========================================================================
# 5. Rule R5: Sanctions Exposure Status Tests
# ===========================================================================
def test_r5_exact_and_normalized_match():
    ofac_records = [
        MockOfacRecord("1001", "NORTHERN MINERALS TRADING LLC", "NORTHERN MINING", "RUSSIA-EO14024"),
    ]
    # Exact match
    res1 = evaluate_sanctions_exposure("NORTHERN MINERALS TRADING LLC", ofac_records)
    assert res1.outcome == SANCTIONS_REVIEW_MATCH
    assert "Source ID: 1001" in res1.explanation

    # Normalized match (lowercase, punctuation, corporate suffix variant)
    res2 = evaluate_sanctions_exposure("Northern Minerals Trading Ltd.", ofac_records)
    assert res2.outcome == SANCTIONS_REVIEW_MATCH

    # Alias match
    res3 = evaluate_sanctions_exposure("Northern Mining", ofac_records)
    assert res3.outcome == SANCTIONS_REVIEW_MATCH


def test_r5_no_identified_match():
    ofac_records = [
        MockOfacRecord("1001", "NORTHERN MINERALS TRADING LLC"),
    ]
    res = evaluate_sanctions_exposure("PACIFIC CLEAN LOGISTICS", ofac_records)
    assert res.outcome == SANCTIONS_NO_IDENTIFIED_MATCH
    assert "did not match" in res.explanation


def test_r5_unavailable_entity_identifier():
    """Country-level trade data with no company identifier returns UNKNOWN."""
    ofac_records = [MockOfacRecord("1001", "SOME ENTITY")]
    res = evaluate_sanctions_exposure(None, ofac_records)
    assert res.outcome == SANCTIONS_UNKNOWN
    assert "country-level aggregate trade data" in res.explanation


# ===========================================================================
# 6. Combined Anomaly Score Tests
# ===========================================================================
def make_mock_result(rule_id, outcome, weight):
    return RuleEvaluationResult(
        rule_id=rule_id,
        rule_name=f"Rule {rule_id}",
        rule_version="1.0",
        weight=weight,
        outcome=outcome,
        threshold="N/A",
        formula="N/A",
        calculated_value=50.0 if outcome != OUTCOME_INSUFFICIENT_DATA else None,
        input_values={},
        explanation="Test explanation",
    )


@pytest.mark.parametrize(
    "r1_out,r2_out,r3_out,r4_out,expected_score",
    [
        (OUTCOME_FLAG, OUTCOME_FLAG, OUTCOME_FLAG, OUTCOME_FLAG, 100.0),   # 30+20+30+20
        (OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, 0.0),
        (OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, 30.0),
        (OUTCOME_NOT_FLAGGED, OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, 20.0),
        (OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, 30.0),
        (OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, OUTCOME_FLAG, 20.0),
        (OUTCOME_FLAG, OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, OUTCOME_NOT_FLAGGED, 50.0),
        (OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, 60.0),
        (OUTCOME_FLAG, OUTCOME_FLAG, OUTCOME_NOT_FLAGGED, OUTCOME_FLAG, 70.0),
    ],
)
def test_combined_score_permutations(r1_out, r2_out, r3_out, r4_out, expected_score):
    rule_results = {
        RULE_R1: make_mock_result(RULE_R1, r1_out, 30),
        RULE_R2: make_mock_result(RULE_R2, r2_out, 20),
        RULE_R3: make_mock_result(RULE_R3, r3_out, 30),
        RULE_R4: make_mock_result(RULE_R4, r4_out, 20),
        RULE_R5: make_mock_result(RULE_R5, SANCTIONS_UNKNOWN, 0),
    }
    combined = calculate_combined_anomaly_score(rule_results)
    assert combined.score == expected_score
    assert combined.completeness == COMPLETENESS_COMPLETE


def test_combined_score_completeness_states():
    # Partial completeness: 3 evaluated, 1 insufficient
    partial_results = {
        RULE_R1: make_mock_result(RULE_R1, OUTCOME_FLAG, 30),
        RULE_R2: make_mock_result(RULE_R2, OUTCOME_NOT_FLAGGED, 20),
        RULE_R3: make_mock_result(RULE_R3, OUTCOME_INSUFFICIENT_DATA, 30),
        RULE_R4: make_mock_result(RULE_R4, OUTCOME_NOT_FLAGGED, 20),
    }
    res_partial = calculate_combined_anomaly_score(partial_results)
    assert res_partial.completeness == COMPLETENESS_PARTIAL
    assert res_partial.score == 30.0
    assert RULE_R3 in res_partial.insufficient_rules

    # Unavailable completeness: all 4 insufficient
    unavail_results = {
        RULE_R1: make_mock_result(RULE_R1, OUTCOME_INSUFFICIENT_DATA, 30),
        RULE_R2: make_mock_result(RULE_R2, OUTCOME_INSUFFICIENT_DATA, 20),
        RULE_R3: make_mock_result(RULE_R3, OUTCOME_INSUFFICIENT_DATA, 30),
        RULE_R4: make_mock_result(RULE_R4, OUTCOME_INSUFFICIENT_DATA, 20),
    }
    res_unavail = calculate_combined_anomaly_score(unavail_results)
    assert res_unavail.completeness == COMPLETENESS_UNAVAILABLE
    assert res_unavail.score == 0.0
    assert len(res_unavail.insufficient_rules) == 4
