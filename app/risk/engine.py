"""Deterministic, explainable Risk Detection Engine evaluating rules R1 to R5."""
import re
import statistics
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

from app.risk.rules import (
    RULE_R1,
    RULE_R2,
    RULE_R3,
    RULE_R4,
    RULE_R5,
    RULE_WEIGHTS,
    RULE_CATALOG,
    OUTCOME_FLAG,
    OUTCOME_NOT_FLAGGED,
    OUTCOME_INSUFFICIENT_DATA,
    SANCTIONS_REVIEW_MATCH,
    SANCTIONS_NO_IDENTIFIED_MATCH,
    SANCTIONS_UNKNOWN,
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    COMPLETENESS_UNAVAILABLE,
    THRESHOLD_R1_PERCENT,
    THRESHOLD_R2_PERCENT,
    THRESHOLD_R3_PERCENT,
    THRESHOLD_R4_PERCENT,
    MIN_UNIT_PRICE_SAMPLE_SIZE,
)


@dataclass
class RuleEvaluationResult:
    """Outcome of evaluating a single risk rule."""
    rule_id: str
    rule_name: str
    rule_version: str
    weight: int
    outcome: str
    threshold: str
    formula: str
    calculated_value: Optional[float]
    input_values: Dict[str, Any]
    explanation: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class CombinedRiskScoreResult:
    """Overall anomaly score and completeness breakdown."""
    score: float
    completeness: str  # COMPLETE, PARTIAL, UNAVAILABLE
    evaluated_rules: List[str]
    insufficient_rules: List[str]
    flagged_rules: List[str]
    rule_results: Dict[str, RuleEvaluationResult]
    sanctions_status: str
    sanctions_reference: Optional[str] = None


# ---------------------------------------------------------------------------
# Rule R1: Mirror Trade Gap
# ---------------------------------------------------------------------------
def evaluate_mirror_trade_gap(
    export_value: Optional[float],
    import_value: Optional[float],
    reporter_country: str = "Reporter",
    partner_country: str = "Partner",
    period: str = "N/A",
) -> RuleEvaluationResult:
    """
    Evaluates discrepancy between reported export value and matching partner import value.
    Formula: abs(export_value - import_value) / max(export_value, import_value) * 100
    Trigger: Gap > 30.0%
    """
    meta = RULE_CATALOG[RULE_R1]
    inputs = {
        "export_value": export_value,
        "import_value": import_value,
        "reporter_country": reporter_country,
        "partner_country": partner_country,
        "period": period,
    }

    # Missing value handling: Never treat missing as zero
    if export_value is None or import_value is None:
        missing_item = "export value" if export_value is None else "matching partner import value"
        if export_value is None and import_value is None:
            missing_item = "both export and import values"
        return RuleEvaluationResult(
            rule_id=RULE_R1,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Insufficient data to evaluate mirror trade gap: {missing_item} is missing.",
            warnings=["Mirror comparison requires both valid export and import reports."],
        )

    # Invalid negative values
    if export_value < 0 or import_value < 0:
        return RuleEvaluationResult(
            rule_id=RULE_R1,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation="Trade values cannot be negative.",
            warnings=["Encountered negative values during mirror trade gap calculation."],
        )

    # Division by zero prevention: Both values zero
    max_val = max(export_value, import_value)
    if max_val == 0.0:
        return RuleEvaluationResult(
            rule_id=RULE_R1,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation="Both reported export and import values are zero; mirror gap cannot be computed.",
            warnings=["Cannot compute percentage gap when both trade values are zero."],
        )

    # Calculate gap
    gap_percentage = round((abs(export_value - import_value) / max_val) * 100.0, 2)
    is_flagged = gap_percentage > THRESHOLD_R1_PERCENT

    outcome = OUTCOME_FLAG if is_flagged else OUTCOME_NOT_FLAGGED
    if is_flagged:
        explanation = (
            f"Reported export value ({export_value:,.2f}) and matching partner import value "
            f"({import_value:,.2f}) differ by {gap_percentage:.2f}%, exceeding the {THRESHOLD_R1_PERCENT}% threshold."
        )
    else:
        explanation = (
            f"Mirror trade discrepancy of {gap_percentage:.2f}% is within the acceptable "
            f"threshold of {THRESHOLD_R1_PERCENT}%."
        )

    return RuleEvaluationResult(
        rule_id=RULE_R1,
        rule_name=meta.name,
        rule_version=meta.version,
        weight=meta.weight,
        outcome=outcome,
        threshold=meta.threshold,
        formula=meta.formula,
        calculated_value=gap_percentage,
        input_values=inputs,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Rule R2: Volume Spike
# ---------------------------------------------------------------------------
def evaluate_volume_spike(
    current_volume: Optional[float],
    previous_volume: Optional[float],
    current_period: str = "Current",
    previous_period: Optional[str] = None,
    volume_unit: str = "kg",
) -> RuleEvaluationResult:
    """
    Evaluates surge in trade volume against comparable prior period baseline.
    Formula: (current_volume - previous_volume) / previous_volume * 100
    Trigger: Increase > 200.0%
    """
    meta = RULE_CATALOG[RULE_R2]
    inputs = {
        "current_volume": current_volume,
        "previous_volume": previous_volume,
        "current_period": current_period,
        "previous_period": previous_period,
        "volume_unit": volume_unit,
    }

    # Baseline requirement
    if previous_volume is None or current_volume is None or previous_period is None:
        missing_desc = []
        if current_volume is None:
            missing_desc.append("current period volume")
        if previous_volume is None or previous_period is None:
            missing_desc.append("historical previous period baseline")
        return RuleEvaluationResult(
            rule_id=RULE_R2,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Insufficient historical data: missing {', '.join(missing_desc)}.",
            warnings=["Volume spike rule requires a valid prior period baseline."],
        )

    # Division by zero: previous_volume == 0
    if previous_volume <= 0.0:
        return RuleEvaluationResult(
            rule_id=RULE_R2,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Previous baseline volume is zero or negative ({previous_volume}); cannot calculate percentage change.",
            warnings=["Baseline volume must be greater than zero for spike percentage calculation."],
        )

    if current_volume < 0.0:
        return RuleEvaluationResult(
            rule_id=RULE_R2,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation="Current volume cannot be negative.",
            warnings=["Encountered negative current volume."],
        )

    # Calculate change
    change_percentage = round(((current_volume - previous_volume) / previous_volume) * 100.0, 2)
    is_flagged = change_percentage > THRESHOLD_R2_PERCENT

    outcome = OUTCOME_FLAG if is_flagged else OUTCOME_NOT_FLAGGED
    if is_flagged:
        explanation = (
            f"Trade volume surged by {change_percentage:.2f}% from {previous_volume:,.2f} {volume_unit} "
            f"({previous_period}) to {current_volume:,.2f} {volume_unit} ({current_period}), "
            f"exceeding the {THRESHOLD_R2_PERCENT}% threshold."
        )
    elif change_percentage < 0:
        explanation = (
            f"Trade volume decreased by {abs(change_percentage):.2f}% compared to {previous_period}; "
            f"no upward volume spike detected."
        )
    else:
        explanation = (
            f"Volume increase of {change_percentage:.2f}% is within the acceptable threshold of {THRESHOLD_R2_PERCENT}%."
        )

    return RuleEvaluationResult(
        rule_id=RULE_R2,
        rule_name=meta.name,
        rule_version=meta.version,
        weight=meta.weight,
        outcome=outcome,
        threshold=meta.threshold,
        formula=meta.formula,
        calculated_value=change_percentage,
        input_values=inputs,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Rule R3: Route Concentration
# ---------------------------------------------------------------------------
def evaluate_route_concentration(
    partner_import_volume: Optional[float],
    total_comparable_import_volume: Optional[float],
    partner_country_name: str = "Partner",
    reporter_country_name: str = "Reporter",
    period: str = "Period",
    volume_unit: str = "kg",
) -> RuleEvaluationResult:
    """
    Evaluates whether a reporting country depends on a single partner for > 80% of imports.
    Formula: partner_import_volume / total_comparable_import_volume * 100
    Trigger: Concentration > 80.0%
    """
    meta = RULE_CATALOG[RULE_R3]
    inputs = {
        "partner_import_volume": partner_import_volume,
        "total_comparable_import_volume": total_comparable_import_volume,
        "partner_country": partner_country_name,
        "reporter_country": reporter_country_name,
        "period": period,
        "volume_unit": volume_unit,
    }

    if partner_import_volume is None or total_comparable_import_volume is None:
        missing_item = "partner volume" if partner_import_volume is None else "total import volume"
        return RuleEvaluationResult(
            rule_id=RULE_R3,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Insufficient data to evaluate route concentration: {missing_item} is missing.",
            warnings=["Route concentration requires both partner volume and total market import volume."],
        )

    if total_comparable_import_volume <= 0.0 or partner_import_volume < 0.0:
        return RuleEvaluationResult(
            rule_id=RULE_R3,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Total comparable import volume is zero or invalid ({total_comparable_import_volume}).",
            warnings=["Total comparable import volume must be greater than zero."],
        )

    # Concentration percentage
    concentration = round((partner_import_volume / total_comparable_import_volume) * 100.0, 2)
    # Clamp to max 100% in case of minor reporting discrepancies
    concentration = min(concentration, 100.0)

    is_flagged = concentration > THRESHOLD_R3_PERCENT
    outcome = OUTCOME_FLAG if is_flagged else OUTCOME_NOT_FLAGGED

    if is_flagged:
        explanation = (
            f"Partner {partner_country_name} supplies {concentration:.2f}% ({partner_import_volume:,.2f} {volume_unit}) "
            f"of total comparable imports ({total_comparable_import_volume:,.2f} {volume_unit}) for {reporter_country_name} "
            f"in {period}, exceeding the {THRESHOLD_R3_PERCENT}% concentration threshold."
        )
    else:
        explanation = (
            f"Partner {partner_country_name} represents {concentration:.2f}% of total comparable imports, "
            f"which does not exceed the {THRESHOLD_R3_PERCENT}% threshold."
        )

    return RuleEvaluationResult(
        rule_id=RULE_R3,
        rule_name=meta.name,
        rule_version=meta.version,
        weight=meta.weight,
        outcome=outcome,
        threshold=meta.threshold,
        formula=meta.formula,
        calculated_value=concentration,
        input_values=inputs,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Rule R4: Unusual Unit Price
# ---------------------------------------------------------------------------
def evaluate_unusual_unit_price(
    trade_value: Optional[float],
    net_weight_kg: Optional[float],
    comparison_unit_prices: List[float],
    min_sample_size: int = MIN_UNIT_PRICE_SAMPLE_SIZE,
    commodity_code: str = "N/A",
) -> RuleEvaluationResult:
    """
    Evaluates unit price deviation (USD/kg) against median of comparable commodity transactions.
    Formula: abs(unit_price - comparable_median_price) / comparable_median_price * 100
    Trigger: Deviation > 60.0% (Note: exactly 60.0% is NOT_FLAGGED)
    """
    meta = RULE_CATALOG[RULE_R4]
    
    unit_price = None
    if trade_value is not None and net_weight_kg is not None and net_weight_kg > 0 and trade_value >= 0:
        unit_price = round(trade_value / net_weight_kg, 4)

    inputs = {
        "trade_value": trade_value,
        "net_weight_kg": net_weight_kg,
        "calculated_unit_price": unit_price,
        "sample_size": len(comparison_unit_prices),
        "min_required_sample_size": min_sample_size,
        "commodity_code": commodity_code,
    }

    if trade_value is None or net_weight_kg is None:
        missing_item = "trade value" if trade_value is None else "net weight"
        return RuleEvaluationResult(
            rule_id=RULE_R4,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Insufficient transaction data: {missing_item} is missing.",
            warnings=["Unit price requires valid trade value and net weight in kg."],
        )

    if net_weight_kg <= 0:
        return RuleEvaluationResult(
            rule_id=RULE_R4,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=f"Net weight must be greater than zero to compute unit price (got {net_weight_kg}).",
            warnings=["Net weight zero or negative."],
        )

    # Valid comparison sample check
    valid_prices = [p for p in comparison_unit_prices if p is not None and p > 0]
    if len(valid_prices) < min_sample_size:
        return RuleEvaluationResult(
            rule_id=RULE_R4,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=(
                f"Insufficient comparable records: found {len(valid_prices)} valid transactions, "
                f"but at least {min_sample_size} are required to establish a robust median benchmark."
            ),
            warnings=[f"Minimum benchmark sample size requirement ({min_sample_size}) not met."],
        )

    median_price = round(float(statistics.median(valid_prices)), 4)
    inputs["comparable_median_price"] = median_price

    if median_price <= 0:
        return RuleEvaluationResult(
            rule_id=RULE_R4,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=OUTCOME_INSUFFICIENT_DATA,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation="Comparable median price is zero or invalid; cannot compute deviation.",
            warnings=["Median unit price is zero."],
        )

    # Calculate deviation percentage
    assert unit_price is not None
    deviation = round((abs(unit_price - median_price) / median_price) * 100.0, 2)
    is_flagged = deviation > THRESHOLD_R4_PERCENT

    outcome = OUTCOME_FLAG if is_flagged else OUTCOME_NOT_FLAGGED
    if is_flagged:
        direction = "higher" if unit_price > median_price else "lower"
        explanation = (
            f"Unit price of {unit_price:,.2f} USD/kg deviates by {deviation:.2f}% ({direction}) "
            f"from the comparable commodity median of {median_price:,.2f} USD/kg "
            f"(sample size: {len(valid_prices)}), exceeding the {THRESHOLD_R4_PERCENT}% threshold."
        )
    else:
        explanation = (
            f"Unit price of {unit_price:,.2f} USD/kg deviates by {deviation:.2f}% from the "
            f"comparable median of {median_price:,.2f} USD/kg, which is within the acceptable {THRESHOLD_R4_PERCENT}% threshold."
        )

    return RuleEvaluationResult(
        rule_id=RULE_R4,
        rule_name=meta.name,
        rule_version=meta.version,
        weight=meta.weight,
        outcome=outcome,
        threshold=meta.threshold,
        formula=meta.formula,
        calculated_value=deviation,
        input_values=inputs,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Rule R5: Sanctions Exposure Status
# ---------------------------------------------------------------------------
def normalize_entity_text(text: Optional[str]) -> str:
    """Normalizes entity names for string comparison without altering evidence."""
    if not text:
        return ""
    # Uppercase and strip legal company suffix designations and punctuation
    cleaned = re.sub(r"[^\w\s]", " ", text.upper())
    # Remove common corporate suffixes
    tokens = [
        t for t in cleaned.split()
        if t not in {"LLC", "LTD", "LIMITED", "CORP", "CORPORATION", "INC", "INCORPORATED", "CO", "COMPANY", "JSC", "PJSC", "OJSC", "GMBH", "AG", "SA", "PLC"}
    ]
    return " ".join(tokens).strip()


def evaluate_sanctions_exposure(
    entity_name: Optional[str],
    ofac_records: List[Any],
) -> RuleEvaluationResult:
    """
    Cautiously screens an entity name against locally stored OFAC SDN records.
    Returns:
      - REVIEW_MATCH: Identified match found in local SDN list
      - NO_IDENTIFIED_MATCH: Searched local list and found no matching records
      - UNKNOWN: Missing or unavailable entity identifier in source data
    """
    meta = RULE_CATALOG[RULE_R5]
    inputs = {
        "query_entity_name": entity_name,
        "available_ofac_records_count": len(ofac_records),
    }

    # If entity identifier is not present (e.g. UN Comtrade country-level aggregate)
    if not entity_name or not str(entity_name).strip():
        return RuleEvaluationResult(
            rule_id=RULE_R5,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=SANCTIONS_UNKNOWN,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=(
                "UNKNOWN: Source trade record provides country-level aggregate trade data and contains "
                "no specific company or entity identifier suitable for sanctions screening. "
                "Sanctions screening cannot be performed without entity identification."
            ),
            warnings=["UN Comtrade data reflects country-level flows, not specific transacting companies."],
        )

    norm_query = normalize_entity_text(entity_name)
    if not norm_query:
        return RuleEvaluationResult(
            rule_id=RULE_R5,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=SANCTIONS_UNKNOWN,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation="UNKNOWN: Provided entity query consists solely of generic corporate stopwords.",
        )

    # Check against OFAC records
    match_found = False
    matched_record_id = None
    matched_name = None
    matched_programs = None
    matched_field = None

    for rec in ofac_records:
        primary = getattr(rec, "primary_name", "") or ""
        aliases = getattr(rec, "aliases", "") or ""
        rec_id = getattr(rec, "source_record_id", "") or str(getattr(rec, "id", ""))
        programs = getattr(rec, "programs", "") or ""

        norm_primary = normalize_entity_text(primary)
        if norm_query == norm_primary:
            match_found = True
            matched_record_id = rec_id
            matched_name = primary
            matched_programs = programs
            matched_field = "primary_name"
            break

        # Check aliases
        if aliases:
            for alias in aliases.split(";"):
                if norm_query == normalize_entity_text(alias):
                    match_found = True
                    matched_record_id = rec_id
                    matched_name = alias.strip()
                    matched_programs = programs
                    matched_field = "aliases"
                    break
        if match_found:
            break

    if match_found:
        inputs["matched_record_id"] = matched_record_id
        inputs["matched_name"] = matched_name
        inputs["matched_programs"] = matched_programs
        inputs["matched_field"] = matched_field
        explanation = (
            f"REVIEW_MATCH: Entity '{entity_name}' matches OFAC SDN entry '{matched_name}' "
            f"(Source ID: {matched_record_id}, Program: {matched_programs or 'N/A'}, Matched field: {matched_field}). "
            f"Manual compliance review required."
        )
        return RuleEvaluationResult(
            rule_id=RULE_R5,
            rule_name=meta.name,
            rule_version=meta.version,
            weight=meta.weight,
            outcome=SANCTIONS_REVIEW_MATCH,
            threshold=meta.threshold,
            formula=meta.formula,
            calculated_value=None,
            input_values=inputs,
            explanation=explanation,
            warnings=["Identified match on local OFAC SDN list requires secondary verification."],
        )

    explanation = (
        f"NO_IDENTIFIED_MATCH: Entity '{entity_name}' did not match any of the {len(ofac_records)} "
        f"entries in the locally available OFAC SDN dataset. Note: this does not guarantee the entity "
        f"is unencumbered by other regulatory restrictions."
    )
    return RuleEvaluationResult(
        rule_id=RULE_R5,
        rule_name=meta.name,
        rule_version=meta.version,
        weight=meta.weight,
        outcome=SANCTIONS_NO_IDENTIFIED_MATCH,
        threshold=meta.threshold,
        formula=meta.formula,
        calculated_value=None,
        input_values=inputs,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Combined Anomaly Score Aggregator
# ---------------------------------------------------------------------------
def calculate_combined_anomaly_score(
    rule_results: Dict[str, RuleEvaluationResult],
) -> CombinedRiskScoreResult:
    """
    Computes deterministic weighted anomaly score (0 - 100) across rules R1 - R4.
    R5 is evaluated and tracked as a separate sanctions screening status.
    """
    evaluated_rules = []
    insufficient_rules = []
    flagged_rules = []
    total_score = 0.0

    scoring_rules = [RULE_R1, RULE_R2, RULE_R3, RULE_R4]

    for rule_id in scoring_rules:
        result = rule_results.get(rule_id)
        if result is None or result.outcome == OUTCOME_INSUFFICIENT_DATA:
            insufficient_rules.append(rule_id)
        else:
            evaluated_rules.append(rule_id)
            if result.outcome == OUTCOME_FLAG:
                flagged_rules.append(rule_id)
                total_score += result.weight

    # Determine score completeness
    if len(insufficient_rules) == 0:
        completeness = COMPLETENESS_COMPLETE
    elif len(evaluated_rules) == 0:
        completeness = COMPLETENESS_UNAVAILABLE
    else:
        completeness = COMPLETENESS_PARTIAL

    # Extract R5 status
    r5_result = rule_results.get(RULE_R5)
    sanctions_status = r5_result.outcome if r5_result else SANCTIONS_UNKNOWN
    sanctions_reference = None
    if r5_result and r5_result.input_values.get("matched_record_id"):
        sanctions_reference = str(r5_result.input_values.get("matched_record_id"))

    return CombinedRiskScoreResult(
        score=round(total_score, 1),
        completeness=completeness,
        evaluated_rules=evaluated_rules,
        insufficient_rules=insufficient_rules,
        flagged_rules=flagged_rules,
        rule_results=rule_results,
        sanctions_status=sanctions_status,
        sanctions_reference=sanctions_reference,
    )
