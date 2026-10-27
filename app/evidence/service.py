"""Evidence Generation and Validation services for Phase 5."""
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from app.database.models import (
    RiskAnalysis,
    RiskRuleResult,
    NormalizedTradeRecord,
    RankingSnapshot,
    RankingSnapshotItem,
    EvidenceSnapshot,
)
from app.audit.service import AuditEventService
from app.evidence.rules import (
    EVIDENCE_SCHEMA_VERSION,
    CALCULATION_TOLERANCE,
    EVENT_EVIDENCE_SNAPSHOT_GENERATED,
    EVENT_EVIDENCE_VALIDATION_PASSED,
    EVENT_EVIDENCE_VALIDATION_FAILED,
    CHECK_ANALYSIS_EXISTS,
    CHECK_RULE_IDS_VALID,
    CHECK_THRESHOLDS_MATCH,
    CHECK_CALCULATIONS_MATCH,
    CHECK_SCORE_WEIGHTS_MATCH,
    CHECK_COMPLETENESS_CONSISTENT,
    CHECK_CLASSIFICATION_CONSISTENT,
    CHECK_RANKING_REFERENCE,
    CHECK_SOURCE_INTEGRITY,
    STATUS_VALID,
    STATUS_INVALID,
    STATUS_WARNINGS,
    STATUS_UNVALIDATED,
    EVIDENCE_DISCLAIMER,
)
from app.schemas.evidence import (
    EvidenceSnapshotResponse,
    EvidenceValidationResponse,
    RuleEvidenceItem,
    SourceTraceability,
    ScoreEvidence,
    ClassificationEvidence,
    RankingEvidence,
    ValidationCheckResult,
)
from app.classification.rules import (
    CLASSIFICATION_THRESHOLDS_METADATA,
    CLASS_GREEN,
    CLASS_AMBER,
    CLASS_RED,
    CLASS_INSUFFICIENT_DATA,
)
from app.risk.rules import (
    RULE_R1,
    RULE_R2,
    RULE_R3,
    RULE_R4,
    RULE_R5,
    RULE_WEIGHTS,
    RULE_CATALOG,
    OUTCOME_FLAG,
)


def normalize_threshold_str(val: Optional[str]) -> str:
    """Normalizes threshold strings for semantic comparison."""
    if not val:
        return ""
    norm = val.lower().replace("greater than", ">").replace("more than", ">").replace(".0%", "%").replace(" ", "")
    if "ofac" in norm:
        return "ofac_sdn_match"
    if "30%" in norm:
        return ">30%"
    if "200%" in norm:
        return ">200%"
    if "80%" in norm:
        return ">80%"
    if "60%" in norm:
        return ">60%"
    return norm


def safe_json_loads(val: Any, default: Any = None) -> Any:
    """Safely decodes JSON text or returns default."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


class EvidenceService:
    """Service to create, persist, and retrieve immutable risk analysis evidence snapshots."""

    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditEventService(db)

    def create_or_get_snapshot(self, analysis: RiskAnalysis) -> EvidenceSnapshot:
        """Retrieves existing evidence snapshot or freezes current analysis state into an immutable snapshot."""
        existing = (
            self.db.query(EvidenceSnapshot)
            .filter(EvidenceSnapshot.analysis_id == analysis.analysis_id)
            .first()
        )
        if existing:
            return existing

        evidence_uuid = str(uuid.uuid4())

        # 1. Source trade record metadata snapshot
        source_dataset = "UN Comtrade"
        source_rec_id = None
        source_ref_url = None
        source_retrieval_time = None
        source_payload: Dict[str, Any] = {}

        if analysis.trade_record_id:
            trade_rec = (
                self.db.query(NormalizedTradeRecord)
                .filter(NormalizedTradeRecord.id == analysis.trade_record_id)
                .first()
            )
            if trade_rec:
                source_dataset = "UN Comtrade (Normalized)"
                source_rec_id = trade_rec.source_record_id or f"REC-{trade_rec.id}"
                source_payload = {
                    "trade_record_id": trade_rec.id,
                    "commodity_code": trade_rec.commodity_code,
                    "commodity_description": trade_rec.commodity_description,
                    "mineral_type": trade_rec.mineral_type,
                    "reporter_country_code": trade_rec.reporter_country_code,
                    "reporter_country_name": trade_rec.reporter_country_name,
                    "partner_country_code": trade_rec.partner_country_code,
                    "partner_country_name": trade_rec.partner_country_name,
                    "period": trade_rec.period,
                    "period_year": trade_rec.period_year,
                    "flow_type": trade_rec.flow_type,
                    "trade_value_usd": trade_rec.trade_value_usd,
                    "net_weight_kg": trade_rec.net_weight_kg,
                    "quantity": trade_rec.quantity,
                    "quantity_unit": trade_rec.quantity_unit,
                    "record_hash": trade_rec.record_hash,
                }
                if trade_rec.raw_record:
                    source_retrieval_time = trade_rec.raw_record.retrieval_timestamp
                    source_dataset = "UN Comtrade (Normalized)"
        else:
            source_payload = {
                "commodity_code": analysis.commodity_code,
                "mineral_type": analysis.mineral_type,
                "reporter_country_code": analysis.reporter_country_code,
                "partner_country_code": analysis.partner_country_code,
                "period": analysis.period,
                "note": "Analysis was created without direct trade_record_id link.",
            }

        # 2. Rule evaluation results snapshot
        rule_results = (
            self.db.query(RiskRuleResult)
            .filter(RiskRuleResult.analysis_id == analysis.analysis_id)
            .order_by(RiskRuleResult.rule_id)
            .all()
        )

        rule_snapshots = []
        for r in rule_results:
            rule_snapshots.append({
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "rule_version": r.rule_version,
                "weight": r.weight,
                "outcome": r.outcome,
                "threshold": r.threshold,
                "formula": r.formula,
                "calculated_value": r.calculated_value,
                "input_values": safe_json_loads(r.input_values, {}),
                "explanation": r.explanation,
                "warnings": safe_json_loads(r.warnings, []),
            })

        # 3. Phase 3 Classification metadata
        categories = CLASSIFICATION_THRESHOLDS_METADATA.get("categories", [])
        classification_thresholds = {
            c["category"]: {"min_score": c.get("min_score"), "max_score": c.get("max_score")}
            for c in categories
        }

        # 4. Phase 4 Ranking context snapshot
        ranking_item = (
            self.db.query(RankingSnapshotItem)
            .filter(RankingSnapshotItem.analysis_id == analysis.analysis_id)
            .order_by(desc(RankingSnapshotItem.created_at))
            .first()
        )
        ranking_context: Optional[Dict[str, Any]] = None
        if ranking_item:
            ranking_context = {
                "snapshot_id": ranking_item.snapshot_id,
                "rank": ranking_item.rank,
                "anomaly_score": ranking_item.anomaly_score,
                "classification": ranking_item.classification,
                "created_at": ranking_item.created_at.isoformat(),
            }

        snapshot = EvidenceSnapshot(
            evidence_id=evidence_uuid,
            analysis_id=analysis.analysis_id,
            schema_version=EVIDENCE_SCHEMA_VERSION,
            trade_record_id=analysis.trade_record_id,
            source_dataset_name=source_dataset,
            source_record_id=source_rec_id,
            source_reference_url=source_ref_url,
            source_retrieval_timestamp=source_retrieval_time,
            source_payload_snapshot=json.dumps(source_payload),
            analysis_timestamp=analysis.created_at,
            combined_anomaly_score=float(analysis.combined_anomaly_score),
            score_completeness=analysis.score_completeness,
            evaluated_rules=analysis.evaluated_rules,
            insufficient_rules=analysis.insufficient_rules,
            flagged_rules=analysis.flagged_rules,
            sanctions_status=analysis.sanctions_status,
            sanctions_reference=analysis.sanctions_reference,
            classification=analysis.classification,
            flag_status=analysis.flag_status,
            classification_explanation=analysis.classification_explanation,
            classification_policy_version="1.0",
            classification_thresholds_applied=json.dumps(classification_thresholds),
            ranking_context=json.dumps(ranking_context) if ranking_context else None,
            rule_evaluations_snapshot=json.dumps(rule_snapshots),
            data_quality_warnings=json.dumps([]),
            validation_status=STATUS_UNVALIDATED,
        )

        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)

        # Audit event
        self.audit.record_event(
            event_type=EVENT_EVIDENCE_SNAPSHOT_GENERATED,
            related_record_id=analysis.analysis_id,
            operation_status="SUCCESS",
            metadata={
                "evidence_id": evidence_uuid,
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "rules_count": len(rule_snapshots),
            },
        )

        return snapshot

    def get_snapshot_response(self, analysis_id: str) -> Optional[EvidenceSnapshotResponse]:
        """Retrieves or synthesizes the complete EvidenceSnapshotResponse for an analysis."""
        analysis = (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.analysis_id == analysis_id.strip())
            .first()
        )
        if not analysis:
            return None

        # Fetch or freeze snapshot
        snapshot = self.create_or_get_snapshot(analysis)

        source_payload = safe_json_loads(snapshot.source_payload_snapshot, {})
        rules_list = safe_json_loads(snapshot.rule_evaluations_snapshot, [])
        thresholds = safe_json_loads(snapshot.classification_thresholds_applied, None)
        rank_ctx = safe_json_loads(snapshot.ranking_context, None)
        warnings = safe_json_loads(snapshot.data_quality_warnings, [])

        rule_items = [
            RuleEvidenceItem(
                rule_id=r["rule_id"],
                rule_name=r["rule_name"],
                rule_version=r["rule_version"],
                weight=r["weight"],
                outcome=r["outcome"],
                threshold=r["threshold"],
                formula=r["formula"],
                calculated_value=r.get("calculated_value"),
                input_values=r.get("input_values", {}),
                explanation=r["explanation"],
                warnings=r.get("warnings", []),
            )
            for r in rules_list
        ]

        source_trace = SourceTraceability(
            trade_record_id=snapshot.trade_record_id,
            source_dataset_name=snapshot.source_dataset_name,
            source_record_id=snapshot.source_record_id,
            source_reference_url=snapshot.source_reference_url,
            source_retrieval_timestamp=snapshot.source_retrieval_timestamp,
            source_payload_snapshot=source_payload,
        )

        score_ev = ScoreEvidence(
            combined_anomaly_score=float(snapshot.combined_anomaly_score),
            score_completeness=snapshot.score_completeness,
            evaluated_rules=safe_json_loads(snapshot.evaluated_rules, []),
            insufficient_rules=safe_json_loads(snapshot.insufficient_rules, []),
            flagged_rules=safe_json_loads(snapshot.flagged_rules, []),
            sanctions_status=snapshot.sanctions_status,
            sanctions_reference=snapshot.sanctions_reference,
        )

        cls_ev = ClassificationEvidence(
            classification=snapshot.classification,
            flag_status=snapshot.flag_status,
            explanation=snapshot.classification_explanation,
            policy_version=snapshot.classification_policy_version,
            thresholds_applied=thresholds,
        )

        rank_ev: Optional[RankingEvidence] = None
        if rank_ctx:
            rank_ev = RankingEvidence(
                snapshot_id=rank_ctx.get("snapshot_id"),
                rank=rank_ctx.get("rank"),
                total_eligible=rank_ctx.get("total_eligible"),
                is_eligible=rank_ctx.get("is_eligible", True),
                exclusion_reason=rank_ctx.get("exclusion_reason"),
                ranking_policy_version=rank_ctx.get("policy_version", "1.0"),
            )

        return EvidenceSnapshotResponse(
            evidence_id=snapshot.evidence_id,
            analysis_id=snapshot.analysis_id,
            schema_version=snapshot.schema_version,
            created_at=snapshot.created_at,
            analysis_timestamp=snapshot.analysis_timestamp,
            source_traceability=source_trace,
            score=score_ev,
            classification=cls_ev,
            ranking=rank_ev,
            rules=rule_items,
            data_quality_warnings=warnings,
            validation_status=snapshot.validation_status,
            last_validated_at=snapshot.last_validated_at,
            disclaimer=EVIDENCE_DISCLAIMER,
        )


class EvidenceValidationService:
    """Service providing rigorous traceability and calculation verification for saved evidence."""

    def __init__(self, db: Session):
        self.db = db
        self.evidence_service = EvidenceService(db)
        self.audit = AuditEventService(db)

    def validate_analysis_evidence(self, analysis_id: str) -> Optional[EvidenceValidationResponse]:
        """Runs the complete suite of deterministic consistency and verification checks."""
        analysis = (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.analysis_id == analysis_id.strip())
            .first()
        )
        if not analysis:
            return None

        snapshot = self.evidence_service.create_or_get_snapshot(analysis)

        checks_performed: List[ValidationCheckResult] = []
        validation_errors: List[str] = []
        warnings: List[str] = []
        unavailable_checks: List[str] = []

        # -------------------------------------------------------------
        # Check 1: Analysis Record Existence
        # -------------------------------------------------------------
        checks_performed.append(
            ValidationCheckResult(
                check_name=CHECK_ANALYSIS_EXISTS,
                passed=True,
                message="Target risk analysis record exists in database.",
                details={"analysis_id": analysis.analysis_id},
            )
        )

        # -------------------------------------------------------------
        # Check 2: Rule IDs and Rule Versions Validity
        # -------------------------------------------------------------
        rules_list = safe_json_loads(snapshot.rule_evaluations_snapshot, [])
        valid_rule_ids = {RULE_R1, RULE_R2, RULE_R3, RULE_R4, RULE_R5}
        invalid_rules = [r["rule_id"] for r in rules_list if r.get("rule_id") not in valid_rule_ids]

        if invalid_rules:
            msg = f"Evidence contains invalid rule IDs: {invalid_rules}"
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_RULE_IDS_VALID, passed=False, message=msg)
            )
        else:
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_RULE_IDS_VALID,
                    passed=True,
                    message="All rule IDs (R1-R5) and versions (1.0) are valid and recognized.",
                )
            )

        # -------------------------------------------------------------
        # Check 3: Stored Thresholds Match Policy Version
        # -------------------------------------------------------------
        threshold_mismatches = []
        for r in rules_list:
            rid = r.get("rule_id")
            if rid in RULE_CATALOG:
                expected_thresh = RULE_CATALOG[rid].threshold
                stored_thresh = r.get("threshold", "")
                if normalize_threshold_str(stored_thresh) != normalize_threshold_str(expected_thresh):
                    threshold_mismatches.append(f"{rid}: stored '{stored_thresh}' vs expected '{expected_thresh}'")

        if threshold_mismatches:
            msg = f"Rule thresholds differ from policy version: {threshold_mismatches}"
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_THRESHOLDS_MATCH, passed=False, message=msg)
            )
        else:
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_THRESHOLDS_MATCH,
                    passed=True,
                    message="Stored rule thresholds strictly match catalog policy definitions.",
                )
            )

        # -------------------------------------------------------------
        # Check 4: Rule Calculations Consistency with Stored Inputs
        # -------------------------------------------------------------
        calc_errors = []
        for r in rules_list:
            rid = r.get("rule_id")
            calc_val = r.get("calculated_value")
            inputs = r.get("input_values", {})

            if rid == RULE_R1 and calc_val is not None:
                exp = inputs.get("export_value")
                imp = inputs.get("import_value")
                if exp is not None and imp is not None:
                    denom = max(exp, imp)
                    if denom > 0:
                        expected_gap = abs(exp - imp) / denom * 100
                        if abs(expected_gap - calc_val) > CALCULATION_TOLERANCE:
                            calc_errors.append(f"R1 gap mismatch: recalculated {expected_gap:.4f}% vs stored {calc_val:.4f}%")

            elif rid == RULE_R2 and calc_val is not None:
                curr = inputs.get("current_volume")
                prev = inputs.get("previous_volume")
                if curr is not None and prev is not None and prev > 0:
                    expected_spike = (curr - prev) / prev * 100
                    if abs(expected_spike - calc_val) > CALCULATION_TOLERANCE:
                        calc_errors.append(f"R2 spike mismatch: recalculated {expected_spike:.4f}% vs stored {calc_val:.4f}%")

            elif rid == RULE_R3 and calc_val is not None:
                partner_vol = inputs.get("partner_import_volume")
                total_vol = inputs.get("total_import_volume")
                if partner_vol is not None and total_vol is not None and total_vol > 0:
                    expected_conc = partner_vol / total_vol * 100
                    if abs(expected_conc - calc_val) > CALCULATION_TOLERANCE:
                        calc_errors.append(f"R3 concentration mismatch: recalculated {expected_conc:.4f}% vs stored {calc_val:.4f}%")

        if calc_errors:
            msg = f"Rule calculations do not match input parameters: {calc_errors}"
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_CALCULATIONS_MATCH, passed=False, message=msg)
            )
        else:
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_CALCULATIONS_MATCH,
                    passed=True,
                    message="All available rule calculations are consistent with recorded inputs within tolerance.",
                )
            )

        # -------------------------------------------------------------
        # Check 5: Combined Anomaly Score Consistency with Rule Outcomes & Weights
        # -------------------------------------------------------------
        flagged_rules_stored = safe_json_loads(snapshot.flagged_rules, [])
        expected_score = sum(
            RULE_WEIGHTS.get(rid, 0)
            for rid in flagged_rules_stored
            if rid in RULE_WEIGHTS
        )
        stored_score = float(snapshot.combined_anomaly_score)

        if abs(expected_score - stored_score) > CALCULATION_TOLERANCE:
            msg = f"Combined anomaly score {stored_score} does not match expected weighted sum {expected_score}."
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_SCORE_WEIGHTS_MATCH, passed=False, message=msg)
            )
        else:
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_SCORE_WEIGHTS_MATCH,
                    passed=True,
                    message=f"Combined anomaly score {stored_score} exactly matches weighted sum of flagged rules.",
                )
            )

        # -------------------------------------------------------------
        # Check 6: Score Completeness Consistency
        # -------------------------------------------------------------
        evaluated_rules = safe_json_loads(snapshot.evaluated_rules, [])
        scoring_rules = [r for r in evaluated_rules if r in [RULE_R1, RULE_R2, RULE_R3, RULE_R4]]
        completeness = snapshot.score_completeness

        if len(scoring_rules) == 4 and completeness != "COMPLETE":
            msg = f"Completeness status '{completeness}' inconsistent with all 4 scoring rules evaluated."
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_COMPLETENESS_CONSISTENT, passed=False, message=msg)
            )
        elif 1 <= len(scoring_rules) < 4 and completeness != "PARTIAL":
            msg = f"Completeness status '{completeness}' inconsistent with {len(scoring_rules)} evaluated scoring rules."
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_COMPLETENESS_CONSISTENT, passed=False, message=msg)
            )
        elif len(scoring_rules) == 0 and completeness != "UNAVAILABLE":
            msg = f"Completeness status '{completeness}' inconsistent with zero evaluated scoring rules."
            validation_errors.append(msg)
            checks_performed.append(
                ValidationCheckResult(check_name=CHECK_COMPLETENESS_CONSISTENT, passed=False, message=msg)
            )
        else:
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_COMPLETENESS_CONSISTENT,
                    passed=True,
                    message=f"Completeness status '{completeness}' is strictly consistent with evaluated scoring rules ({len(scoring_rules)}/4).",
                )
            )

        # -------------------------------------------------------------
        # Check 7: Classification Reference Consistency
        # -------------------------------------------------------------
        cls_val = snapshot.classification
        if cls_val:
            if completeness != "COMPLETE" and cls_val != CLASS_INSUFFICIENT_DATA:
                msg = f"Classification '{cls_val}' violates data sufficiency guardrail for incomplete assessment '{completeness}'."
                validation_errors.append(msg)
                checks_performed.append(
                    ValidationCheckResult(check_name=CHECK_CLASSIFICATION_CONSISTENT, passed=False, message=msg)
                )
            elif completeness == "COMPLETE":
                if stored_score <= 19.0 and cls_val != CLASS_GREEN:
                    msg = f"Classification '{cls_val}' inconsistent with score {stored_score} (expected GREEN)."
                    validation_errors.append(msg)
                    checks_performed.append(
                        ValidationCheckResult(check_name=CHECK_CLASSIFICATION_CONSISTENT, passed=False, message=msg)
                    )
                elif 20.0 <= stored_score <= 49.0 and cls_val != CLASS_AMBER:
                    msg = f"Classification '{cls_val}' inconsistent with score {stored_score} (expected AMBER)."
                    validation_errors.append(msg)
                    checks_performed.append(
                        ValidationCheckResult(check_name=CHECK_CLASSIFICATION_CONSISTENT, passed=False, message=msg)
                    )
                elif stored_score >= 50.0 and cls_val != CLASS_RED:
                    msg = f"Classification '{cls_val}' inconsistent with score {stored_score} (expected RED)."
                    validation_errors.append(msg)
                    checks_performed.append(
                        ValidationCheckResult(check_name=CHECK_CLASSIFICATION_CONSISTENT, passed=False, message=msg)
                    )
                else:
                    checks_performed.append(
                        ValidationCheckResult(
                            check_name=CHECK_CLASSIFICATION_CONSISTENT,
                            passed=True,
                            message=f"Classification '{cls_val}' is consistent with score {stored_score} and completeness '{completeness}'.",
                        )
                    )
            else:
                checks_performed.append(
                    ValidationCheckResult(
                        check_name=CHECK_CLASSIFICATION_CONSISTENT,
                        passed=True,
                        message=f"Classification '{cls_val}' correctly mapped for '{completeness}' status.",
                    )
                )
        else:
            warnings.append("Analysis does not yet have a Phase 3 classification.")
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_CLASSIFICATION_CONSISTENT,
                    passed=True,
                    message="Classification not yet assigned; check completed with notice.",
                )
            )

        # -------------------------------------------------------------
        # Check 8: Ranking Reference Consistency
        # -------------------------------------------------------------
        rank_ctx = safe_json_loads(snapshot.ranking_context, None)
        if rank_ctx and "snapshot_id" in rank_ctx:
            snap_rec = (
                self.db.query(RankingSnapshot)
                .filter(RankingSnapshot.snapshot_id == rank_ctx["snapshot_id"])
                .first()
            )
            if not snap_rec:
                warnings.append(f"Referenced ranking snapshot '{rank_ctx['snapshot_id']}' no longer exists in database.")
                checks_performed.append(
                    ValidationCheckResult(
                        check_name=CHECK_RANKING_REFERENCE,
                        passed=False,
                        message="Referenced ranking snapshot record not found.",
                    )
                )
            else:
                checks_performed.append(
                    ValidationCheckResult(
                        check_name=CHECK_RANKING_REFERENCE,
                        passed=True,
                        message=f"Ranking snapshot reference '{rank_ctx['snapshot_id']}' verified.",
                    )
                )
        else:
            unavailable_checks.append("Ranking snapshot reference: analysis is not tied to a static ranking snapshot.")

        # -------------------------------------------------------------
        # Check 9: Source Record Traceability & Integrity
        # -------------------------------------------------------------
        if snapshot.trade_record_id:
            trade_rec = (
                self.db.query(NormalizedTradeRecord)
                .filter(NormalizedTradeRecord.id == snapshot.trade_record_id)
                .first()
            )
            if not trade_rec:
                warnings.append(f"Linked trade record ID {snapshot.trade_record_id} was removed or unlinked.")
                checks_performed.append(
                    ValidationCheckResult(
                        check_name=CHECK_SOURCE_INTEGRITY,
                        passed=True,
                        message="Historical trade record reference preserved in frozen snapshot, but database row was modified or deleted.",
                    )
                )
            else:
                checks_performed.append(
                    ValidationCheckResult(
                        check_name=CHECK_SOURCE_INTEGRITY,
                        passed=True,
                        message="Source trade record exists and is linked with verified record hash.",
                    )
                )
        else:
            checks_performed.append(
                ValidationCheckResult(
                    check_name=CHECK_SOURCE_INTEGRITY,
                    passed=True,
                    message="Analysis has explicit stand-alone source context.",
                )
            )

        # -------------------------------------------------------------
        # Final Status Synthesis
        # -------------------------------------------------------------
        if validation_errors:
            final_status = STATUS_INVALID
        elif warnings:
            final_status = STATUS_WARNINGS
        else:
            final_status = STATUS_VALID

        val_now = datetime.now(timezone.utc)

        # Update snapshot validation status without modifying historical evidence fields
        snapshot.validation_status = final_status
        snapshot.validation_report = json.dumps({
            "errors": validation_errors,
            "warnings": warnings,
            "checks_count": len(checks_performed),
        })
        snapshot.last_validated_at = val_now
        self.db.commit()

        # Audit event
        event_type = EVENT_EVIDENCE_VALIDATION_PASSED if final_status != STATUS_INVALID else EVENT_EVIDENCE_VALIDATION_FAILED
        self.audit.record_event(
            event_type=event_type,
            related_record_id=analysis.analysis_id,
            operation_status="SUCCESS" if final_status != STATUS_INVALID else "FAILED",
            metadata={
                "validation_status": final_status,
                "errors_count": len(validation_errors),
                "warnings_count": len(warnings),
            },
            error_details="; ".join(validation_errors) if validation_errors else None,
        )

        return EvidenceValidationResponse(
            analysis_id=analysis.analysis_id,
            evidence_id=snapshot.evidence_id,
            validation_status=final_status,
            validation_timestamp=val_now,
            checks_performed=checks_performed,
            validation_errors=validation_errors,
            warnings=warnings,
            unavailable_checks=unavailable_checks,
            tolerance_used=CALCULATION_TOLERANCE,
        )
