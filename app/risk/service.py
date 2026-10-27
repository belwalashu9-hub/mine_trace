"""Service orchestrating risk rule evaluations against database records and persisting audits."""
import json
import uuid
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.database.models import (
    NormalizedTradeRecord,
    OfacSanctionRecord,
    RiskAnalysis,
    RiskRuleResult,
)
from app.risk.rules import (
    RULE_R1,
    RULE_R2,
    RULE_R3,
    RULE_R4,
    RULE_R5,
    OUTCOME_INSUFFICIENT_DATA,
    RULE_CATALOG,
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
from app.classification.engine import classify_risk_score
from app.audit.service import AuditEventService
from app.evidence.rules import EVENT_RISK_ANALYSIS_CREATED


class RiskEngineService:
    """Coordinates risk assessment pipeline across stored trade flows and sanctions."""

    def __init__(self, db: Session):
        self.db = db

    def analyze_record(
        self,
        record: NormalizedTradeRecord,
        entity_name: Optional[str] = None,
    ) -> RiskAnalysis:
        """Runs the deterministic 5-rule risk engine on a single trade record and persists results."""
        analysis_uuid = str(uuid.uuid4())
        rule_evaluations: Dict[str, RuleEvaluationResult] = {}

        # -------------------------------------------------------------
        # Rule R1: Mirror Trade Gap
        # -------------------------------------------------------------
        # Look for corresponding mirror record (A->B export matched with B->A import)
        mirror_flow = "IMPORT" if record.flow_type == "EXPORT" else "EXPORT"
        mirror_record = (
            self.db.query(NormalizedTradeRecord)
            .filter(
                and_(
                    NormalizedTradeRecord.commodity_code == record.commodity_code,
                    NormalizedTradeRecord.reporter_country_code == record.partner_country_code,
                    NormalizedTradeRecord.partner_country_code == record.reporter_country_code,
                    NormalizedTradeRecord.period == record.period,
                    NormalizedTradeRecord.flow_type == mirror_flow,
                )
            )
            .first()
        )

        if record.flow_type == "EXPORT":
            export_val = record.trade_value_usd
            import_val = mirror_record.trade_value_usd if mirror_record else None
        else:
            import_val = record.trade_value_usd
            export_val = mirror_record.trade_value_usd if mirror_record else None

        rule_evaluations[RULE_R1] = evaluate_mirror_trade_gap(
            export_value=export_val,
            import_value=import_val,
            reporter_country=record.reporter_country_name,
            partner_country=record.partner_country_name,
            period=record.period,
        )

        # -------------------------------------------------------------
        # Rule R2: Volume Spike
        # -------------------------------------------------------------
        # Query preceding annual or monthly period baseline
        prev_year = record.period_year - 1
        prev_period_str = str(prev_year)
        if record.period_month is not None:
            prev_period_str = f"{prev_year}-{record.period_month:02d}"

        prev_record = (
            self.db.query(NormalizedTradeRecord)
            .filter(
                and_(
                    NormalizedTradeRecord.commodity_code == record.commodity_code,
                    NormalizedTradeRecord.reporter_country_code == record.reporter_country_code,
                    NormalizedTradeRecord.partner_country_code == record.partner_country_code,
                    NormalizedTradeRecord.flow_type == record.flow_type,
                    NormalizedTradeRecord.period_year == prev_year,
                )
            )
            .first()
        )

        curr_vol = record.net_weight_kg if record.net_weight_kg is not None else record.quantity
        prev_vol = None
        if prev_record:
            prev_vol = prev_record.net_weight_kg if prev_record.net_weight_kg is not None else prev_record.quantity

        unit = record.quantity_unit or "kg"
        rule_evaluations[RULE_R2] = evaluate_volume_spike(
            current_volume=curr_vol,
            previous_volume=prev_vol,
            current_period=record.period,
            previous_period=prev_record.period if prev_record else None,
            volume_unit=unit,
        )

        # -------------------------------------------------------------
        # Rule R3: Route Concentration
        # -------------------------------------------------------------
        # Evaluates import reliance on single supplier country
        if record.flow_type == "IMPORT":
            import_records = (
                self.db.query(NormalizedTradeRecord)
                .filter(
                    and_(
                        NormalizedTradeRecord.commodity_code == record.commodity_code,
                        NormalizedTradeRecord.reporter_country_code == record.reporter_country_code,
                        NormalizedTradeRecord.period == record.period,
                        NormalizedTradeRecord.flow_type == "IMPORT",
                    )
                )
                .all()
            )

            # Sum distinct partner volumes to avoid duplicate counting
            partner_volumes: Dict[str, float] = {}
            for imp in import_records:
                vol = imp.net_weight_kg if imp.net_weight_kg is not None else imp.quantity
                if vol is not None and vol > 0:
                    partner_volumes[imp.partner_country_code] = vol

            partner_vol = record.net_weight_kg if record.net_weight_kg is not None else record.quantity
            total_vol = sum(partner_volumes.values()) if partner_volumes else None

            rule_evaluations[RULE_R3] = evaluate_route_concentration(
                partner_import_volume=partner_vol,
                total_comparable_import_volume=total_vol,
                partner_country_name=record.partner_country_name,
                reporter_country_name=record.reporter_country_name,
                period=record.period,
                volume_unit=unit,
            )
        else:
            meta = RULE_CATALOG[RULE_R3]
            rule_evaluations[RULE_R3] = RuleEvaluationResult(
                rule_id=RULE_R3,
                rule_name=meta.name,
                rule_version=meta.version,
                weight=meta.weight,
                outcome=OUTCOME_INSUFFICIENT_DATA,
                threshold=meta.threshold,
                formula=meta.formula,
                calculated_value=None,
                input_values={"flow_type": record.flow_type},
                explanation="Route concentration is configured specifically for import dependency analysis.",
                warnings=["Trade flow is EXPORT; rule applies to IMPORT transactions."],
            )

        # -------------------------------------------------------------
        # Rule R4: Unusual Unit Price
        # -------------------------------------------------------------
        # Comparison group: transactions with same commodity code
        comp_records = (
            self.db.query(NormalizedTradeRecord)
            .filter(
                and_(
                    NormalizedTradeRecord.commodity_code == record.commodity_code,
                    NormalizedTradeRecord.trade_value_usd > 0,
                    NormalizedTradeRecord.net_weight_kg > 0,
                )
            )
            .all()
        )

        comparison_prices = [
            r.trade_value_usd / r.net_weight_kg
            for r in comp_records
            if r.trade_value_usd is not None and r.net_weight_kg is not None and r.net_weight_kg > 0
        ]

        rule_evaluations[RULE_R4] = evaluate_unusual_unit_price(
            trade_value=record.trade_value_usd,
            net_weight_kg=record.net_weight_kg,
            comparison_unit_prices=comparison_prices,
            commodity_code=record.commodity_code,
        )

        # -------------------------------------------------------------
        # Rule R5: Sanctions Exposure Status
        # -------------------------------------------------------------
        all_ofac_records = self.db.query(OfacSanctionRecord).all()
        rule_evaluations[RULE_R5] = evaluate_sanctions_exposure(
            entity_name=entity_name,
            ofac_records=all_ofac_records,
        )

        # -------------------------------------------------------------
        # Combined Anomaly Score Aggregation
        # -------------------------------------------------------------
        combined = calculate_combined_anomaly_score(rule_evaluations)

        # -------------------------------------------------------------
        # Phase 3: Risk Classification Engine
        # -------------------------------------------------------------
        cls_result = classify_risk_score(
            score=combined.score,
            completeness=combined.completeness,
            flagged_rules=combined.flagged_rules,
            evaluated_rules=combined.evaluated_rules,
            insufficient_rules=combined.insufficient_rules,
        )

        # -------------------------------------------------------------
        # Database Persistence
        # -------------------------------------------------------------
        analysis_db = RiskAnalysis(
            analysis_id=analysis_uuid,
            trade_record_id=record.id,
            commodity_code=record.commodity_code,
            mineral_type=record.mineral_type,
            reporter_country_code=record.reporter_country_code,
            partner_country_code=record.partner_country_code,
            period=record.period,
            combined_anomaly_score=combined.score,
            score_completeness=combined.completeness,
            evaluated_rules=json.dumps(combined.evaluated_rules),
            insufficient_rules=json.dumps(combined.insufficient_rules),
            flagged_rules=json.dumps(combined.flagged_rules),
            sanctions_status=combined.sanctions_status,
            sanctions_reference=combined.sanctions_reference,
            classification=cls_result.classification,
            flag_status=cls_result.flag_status,
            classification_explanation=cls_result.explanation,
        )
        self.db.add(analysis_db)
        self.db.flush()

        for r_res in combined.rule_results.values():
            rule_db = RiskRuleResult(
                analysis_id=analysis_uuid,
                rule_id=r_res.rule_id,
                rule_name=r_res.rule_name,
                rule_version=r_res.rule_version,
                weight=r_res.weight,
                outcome=r_res.outcome,
                threshold=r_res.threshold,
                formula=r_res.formula,
                calculated_value=r_res.calculated_value,
                input_values=json.dumps(r_res.input_values),
                explanation=r_res.explanation,
                warnings=json.dumps(r_res.warnings) if r_res.warnings else None,
            )
            self.db.add(rule_db)

        self.db.commit()
        self.db.refresh(analysis_db)

        # Phase 5: Automatically create immutable evidence snapshot and log audit event
        try:
            from app.evidence.service import EvidenceService
            EvidenceService(self.db).create_or_get_snapshot(analysis_db)
            AuditEventService(self.db).record_event(
                event_type=EVENT_RISK_ANALYSIS_CREATED,
                related_record_id=analysis_uuid,
                operation_status="SUCCESS",
                metadata={
                    "commodity_code": analysis_db.commodity_code,
                    "score": analysis_db.combined_anomaly_score,
                    "completeness": analysis_db.score_completeness,
                    "classification": analysis_db.classification,
                },
            )
        except Exception:
            pass

        return analysis_db

    def run_analysis_batch(
        self,
        trade_record_id: Optional[int] = None,
        commodity_code: Optional[str] = None,
        reporter_country_code: Optional[str] = None,
        period_year: Optional[int] = None,
        limit: int = 50,
        entity_name: Optional[str] = None,
    ) -> List[RiskAnalysis]:
        """Runs analysis across multiple eligible stored records."""
        query = self.db.query(NormalizedTradeRecord)
        if trade_record_id is not None:
            query = query.filter(NormalizedTradeRecord.id == trade_record_id)
        if commodity_code:
            query = query.filter(NormalizedTradeRecord.commodity_code == commodity_code.strip())
        if reporter_country_code:
            query = query.filter(NormalizedTradeRecord.reporter_country_code == reporter_country_code.strip().upper())
        if period_year:
            query = query.filter(NormalizedTradeRecord.period_year == period_year)

        records = query.order_by(NormalizedTradeRecord.id).limit(limit).all()
        results: List[RiskAnalysis] = []
        for rec in records:
            analysis = self.analyze_record(rec, entity_name=entity_name)
            results.append(analysis)

        return results
