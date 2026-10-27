"""Claim validator verifying generated text against authoritative SQLite structured evidence."""
import re
from typing import Dict, Any, List, Optional, Tuple

from app.risk.rules import RULE_CATALOG
from app.schemas.ai import NumericalClaimValidation


INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"override\s+(the\s+)?risk\s+score",
    r"system\s+prompt",
    r"jailbreak",
    r"pretend\s+you\s+are",
    r"you\s+are\s+now\s+in\s+developer\s+mode",
]


class ClaimValidator:
    """Verifies factual claims in generated answers against structured evidence."""

    def __init__(self, tolerance: float = 1e-2):
        self.tolerance = tolerance

    def validate_explanation(
        self,
        answer: str,
        structured_facts: Optional[Dict[str, Any]],
        retrieved_chunks: List[Dict[str, Any]],
    ) -> Tuple[str, List[NumericalClaimValidation], List[str]]:
        """
        Validates the generated answer against authoritative facts.
        Returns (validation_status, numerical_claims, warnings).
        """
        validation_status = "VALID"
        numerical_claims: List[NumericalClaimValidation] = []
        warnings: List[str] = []

        # -------------------------------------------------------------
        # 1. Prompt Injection & Adversarial Content Check
        # -------------------------------------------------------------
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, answer, re.IGNORECASE):
                validation_status = "INVALID"
                warnings.append(f"Potential prompt injection pattern detected in response: '{pattern}'")

        # -------------------------------------------------------------
        # 2. Structured Evidence Verification (when an analysis was queried)
        # -------------------------------------------------------------
        if structured_facts:
            a_id = structured_facts["analysis_id"]
            actual_score = float(structured_facts["scoring"]["combined_anomaly_score"])
            actual_cls = structured_facts["classification"]["classification"]

            # Verify Score Claim: look for numbers near "score"
            score_matches = re.findall(r"(?:score|anomaly score|rating)[:\s]+(?:of\s+)?(\d+(?:\.\d+)?)", answer, re.IGNORECASE)
            for sm in score_matches:
                try:
                    val = float(sm)
                    if abs(val - actual_score) <= self.tolerance:
                        numerical_claims.append(
                            NumericalClaimValidation(
                                claim=f"Anomaly score reported as {val}",
                                verified=True,
                                expected_value=actual_score,
                                notes="Matches recorded anomaly score in SQLite.",
                            )
                        )
                    else:
                        numerical_claims.append(
                            NumericalClaimValidation(
                                claim=f"Anomaly score reported as {val}",
                                verified=False,
                                expected_value=actual_score,
                                notes=f"Diverges from actual recorded score {actual_score}.",
                            )
                        )
                        validation_status = "WARNINGS"
                        warnings.append(f"Answer claimed score of {val}, but recorded score is {actual_score}.")
                except ValueError:
                    pass

            # Verify Classification Mention: check if answer mentions a color tier
            for tier in ["GREEN", "AMBER", "RED", "INSUFFICIENT_DATA"]:
                # If tier is mentioned as classification
                tier_pattern = rf"\b(?:classification|tier|status)[:\s]+(?:of\s+)?{tier}\b"
                if re.search(tier_pattern, answer, re.IGNORECASE):
                    if tier != actual_cls:
                        validation_status = "WARNINGS"
                        warnings.append(f"Answer cited classification '{tier}', but recorded classification is '{actual_cls}'.")

            # Verify Individual Rule Thresholds & Values
            for r in structured_facts["rules"]:
                rid = r["rule_id"]
                calc_val = r["calculated_value"]
                # If rule calculated value is mentioned, check accuracy
                if calc_val is not None:
                    # Look for percentage near rule id (e.g., "R1 ... 40%")
                    rule_pattern = rf"{rid}[^.\n]*?(\d+(?:\.\d+)?)\s*%"
                    m = re.search(rule_pattern, answer, re.IGNORECASE)
                    if m:
                        claimed_pct = float(m.group(1))
                        is_close = abs(claimed_pct - calc_val) <= 0.5  # allow small rounding
                        numerical_claims.append(
                            NumericalClaimValidation(
                                claim=f"{rid} value cited as {claimed_pct}%",
                                verified=is_close,
                                expected_value=round(calc_val, 2),
                                notes="Verified against rule calculations." if is_close else "Recalculated rule value mismatch.",
                            )
                        )
                        if not is_close:
                            validation_status = "WARNINGS"
                            warnings.append(f"Rule {rid} was cited as {claimed_pct}%, but recorded value was {calc_val:.2f}%.")

        return validation_status, numerical_claims, warnings
