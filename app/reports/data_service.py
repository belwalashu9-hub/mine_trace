"""Report data service assembling authoritative, frozen evidence bundles for PDF generation."""
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.database.models import RiskAnalysis, EvidenceSnapshot, RiskRuleResult, AuditEvent, NormalizedTradeRecord
from app.reports.rules import (
    REPORT_PROJECT_NAME,
    REPORT_TITLE,
    REPORT_TEMPLATE_VERSION,
    REPORT_DISCLAIMER_TEXT,
    METHODOLOGY_LIMITATIONS_TEXT,
    SANCTIONS_LIMITATIONS_TEXT,
)


class ReportDataService:
    """Compiles structured, verified report data bundles from SQLite evidence."""

    def __init__(self, db: Session):
        self.db = db

    def compile_report_data(
        self,
        analysis_id: str,
        include_ai_explanation: bool = True,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compiles all report sections from saved analysis, evidence snapshot, and rule records.
        Does NOT recalculate any scores, thresholds, or classifications.
        """
        a_id = analysis_id.strip()
        analysis: Optional[RiskAnalysis] = (
            self.db.query(RiskAnalysis).filter(RiskAnalysis.analysis_id == a_id).first()
        )
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Risk analysis with ID '{a_id}' was not found in database.",
            )

        # 1. Fetch frozen Phase 5 evidence snapshot if available
        snapshot: Optional[EvidenceSnapshot] = (
            self.db.query(EvidenceSnapshot)
            .filter(EvidenceSnapshot.analysis_id == a_id)
            .order_by(EvidenceSnapshot.created_at.desc())
            .first()
        )

        has_snapshot = snapshot is not None
        trade: Optional[NormalizedTradeRecord] = None
        if analysis.trade_record_id:
            trade = (
                self.db.query(NormalizedTradeRecord)
                .filter(NormalizedTradeRecord.id == analysis.trade_record_id)
                .first()
            )

        # 2. Extract and format rule evaluations
        rule_items = []
        if has_snapshot and snapshot.rule_evaluations_snapshot:
            try:
                rule_items = json.loads(snapshot.rule_evaluations_snapshot)
            except Exception:
                rule_items = []

        if not rule_items:
            # Fallback to direct RiskRuleResult rows
            rule_results = (
                self.db.query(RiskRuleResult)
                .filter(RiskRuleResult.analysis_id == a_id)
                .all()
            )
            for r in rule_results:
                inputs_val = {}
                if r.input_values:
                    try:
                        inputs_val = json.loads(r.input_values)
                    except Exception:
                        inputs_val = {"raw": r.input_values}

                rule_items.append({
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "rule_version": r.rule_version or "1.0",
                    "weight": r.weight,
                    "outcome": r.outcome,
                    "formula": r.formula or "N/A",
                    "threshold": r.threshold or "N/A",
                    "calculated_value": r.calculated_value,
                    "input_values": inputs_val,
                    "explanation": r.explanation,
                    "data_quality_warnings": [],
                    "supporting_source_records": [f"TRADE-{analysis.trade_record_id}"] if analysis.trade_record_id else [],
                })

        # 3. Quality warnings
        quality_warnings = []
        if has_snapshot and snapshot.data_quality_warnings:
            try:
                quality_warnings = json.loads(snapshot.data_quality_warnings)
            except Exception:
                quality_warnings = [str(snapshot.data_quality_warnings)]

        if not has_snapshot:
            quality_warnings.insert(
                0,
                "WARNING: No frozen Phase 5 evidence snapshot found. "
                "Report generated from operational records.",
            )

        # 4. Evaluated and insufficient rule lists
        evaluated_rules = []
        insufficient_rules = []
        if analysis.evaluated_rules:
            try:
                evaluated_rules = json.loads(analysis.evaluated_rules)
            except Exception:
                evaluated_rules = [analysis.evaluated_rules]
        if analysis.insufficient_rules:
            try:
                insufficient_rules = json.loads(analysis.insufficient_rules)
            except Exception:
                insufficient_rules = [analysis.insufficient_rules]

        # 5. Sanctions Screening details
        sanctions_status = analysis.sanctions_status or "UNKNOWN"
        sanctions_reference = analysis.sanctions_reference or "OFAC Specially Designated Nationals (SDN) List"

        # 6. Source Traceability
        source_dataset = "UN Comtrade"
        source_record_id = str(analysis.trade_record_id) if analysis.trade_record_id else "Unavailable"
        source_url = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
        retrieval_timestamp = None

        if has_snapshot:
            source_dataset = snapshot.source_dataset_name or source_dataset
            source_record_id = snapshot.source_record_id or source_record_id
            source_url = snapshot.source_reference_url or source_url
            retrieval_timestamp = snapshot.source_retrieval_timestamp
        elif trade:
            source_dataset = "UN Comtrade"
            source_record_id = f"TRADE-{trade.id}"
            source_url = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
            retrieval_timestamp = trade.retrieval_timestamp

        # 7. Audit Events
        audit_records = (
            self.db.query(AuditEvent)
            .filter(AuditEvent.related_record_id == a_id)
            .order_by(AuditEvent.timestamp.desc())
            .limit(10)
            .all()
        )
        audit_event_summaries = [
            {
                "event_id": ev.event_id,
                "event_type": ev.event_type,
                "timestamp": ev.timestamp.isoformat() if ev.timestamp else "N/A",
                "status": ev.operation_status,
            }
            for ev in audit_records
        ]

        # 8. Validated AI Explanation
        ai_section = {
            "available": False,
            "explanation": None,
            "evidence_ids": [],
            "supporting_documents": [],
            "validation_status": "NOT_REQUESTED",
        }

        if include_ai_explanation:
            try:
                from app.rag.service import RAGService
                from app.schemas.ai import ExplainRequest

                rag_srv = RAGService(self.db)
                req = ExplainRequest(
                    analysis_id=a_id,
                    question=f"Provide an evidence-grounded risk summary for transaction {a_id}.",
                    use_template_only=True,  # Deterministic grounding ensures verified claims
                )
                ai_resp = rag_srv.explain(req)
                if ai_resp and ai_resp.claim_validation.overall_grounded:
                    ai_section = {
                        "available": True,
                        "explanation": ai_resp.explanation,
                        "evidence_ids": ai_resp.grounded_evidence_ids,
                        "supporting_documents": [c.filename for c in ai_resp.supporting_documents],
                        "validation_status": "VALIDATED",
                    }
                else:
                    ai_section = {
                        "available": False,
                        "explanation": "AI explanation could not be verified against authoritative records.",
                        "evidence_ids": [],
                        "supporting_documents": [],
                        "validation_status": "UNVALIDATED_CLAIMS",
                    }
            except Exception:
                ai_section = {
                    "available": False,
                    "explanation": "No pre-existing validated AI explanation available for this record.",
                    "evidence_ids": [],
                    "supporting_documents": [],
                    "validation_status": "UNAVAILABLE",
                }

        # 9. Assembly of final report bundle
        report_bundle = {
            "metadata": {
                "project_name": REPORT_PROJECT_NAME,
                "report_title": REPORT_TITLE,
                "template_version": REPORT_TEMPLATE_VERSION,
                "analysis_id": a_id,
                "evidence_snapshot_id": snapshot.evidence_id if has_snapshot else None,
                "analysis_timestamp": analysis.created_at.isoformat() if analysis.created_at else "N/A",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "notes": notes,
                "has_evidence_snapshot": has_snapshot,
            },
            "executive_summary": {
                "mineral_type": analysis.mineral_type or "Unknown Mineral",
                "commodity_code": analysis.commodity_code or "Unknown Code",
                "reporter_country_code": analysis.reporter_country_code or "N/A",
                "partner_country_code": analysis.partner_country_code or "N/A",
                "period": analysis.period or "N/A",
                "combined_anomaly_score": analysis.combined_anomaly_score,
                "score_completeness": analysis.score_completeness or "UNAVAILABLE",
                "classification": analysis.classification or "INSUFFICIENT_DATA",
                "flag_status": analysis.flag_status or "NOT_FLAGGED",
                "sanctions_status": sanctions_status,
                "evaluated_rules_count": len(evaluated_rules),
                "insufficient_rules_count": len(insufficient_rules),
                "flagged_rules_count": len(rule_items),
                "quality_warnings": quality_warnings,
            },
            "risk_rules": {
                "evaluated_rules": evaluated_rules,
                "insufficient_rules": insufficient_rules,
                "rule_details": rule_items,
            },
            "classification": {
                "score": analysis.combined_anomaly_score,
                "classification": analysis.classification or "INSUFFICIENT_DATA",
                "flag_status": analysis.flag_status or "NOT_FLAGGED",
                "policy_version": snapshot.classification_policy_version if has_snapshot else "1.0",
                "explanation": analysis.classification_explanation or "No explanation recorded.",
                "thresholds": "GREEN (0-19), AMBER (20-49), RED (50-100), INSUFFICIENT_DATA (PARTIAL/UNAVAILABLE)",
                "completeness": analysis.score_completeness or "UNAVAILABLE",
            },
            "sanctions": {
                "sanctions_status": sanctions_status,
                "reference": sanctions_reference,
                "limitations": SANCTIONS_LIMITATIONS_TEXT,
            },
            "evidence_traceability": {
                "source_dataset": source_dataset,
                "source_record_id": source_record_id,
                "source_reference_url": source_url or "Unavailable in source record",
                "retrieval_timestamp": retrieval_timestamp.isoformat() if retrieval_timestamp else "Unavailable",
                "analysis_id": a_id,
                "analysis_timestamp": analysis.created_at.isoformat() if analysis.created_at else "N/A",
                "snapshot_id": snapshot.evidence_id if has_snapshot else "Unavailable",
                "validation_status": snapshot.validation_status if has_snapshot else "UNVALIDATED",
                "audit_events": audit_event_summaries,
            },
            "ai_explanation": ai_section,
            "methodology_and_limitations": {
                "disclaimer": REPORT_DISCLAIMER_TEXT,
                "methodology": METHODOLOGY_LIMITATIONS_TEXT,
            },
        }

        return report_bundle
