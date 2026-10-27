"""Structured evidence builder extracting exact SQLite facts for RAG context."""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.database.models import RiskAnalysis
from app.evidence.service import EvidenceService
from app.schemas.evidence import EvidenceSnapshotResponse


class EvidenceBuilder:
    """Extracts authoritative structured facts and numbers directly from SQLite."""

    def __init__(self, db: Session):
        self.db = db
        self.evidence_service = EvidenceService(db)

    def get_analysis(self, analysis_id: str) -> Optional[RiskAnalysis]:
        """Looks up the target RiskAnalysis record."""
        return (
            self.db.query(RiskAnalysis)
            .filter(RiskAnalysis.analysis_id == analysis_id.strip())
            .first()
        )

    def build_structured_context(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Constructs an authoritative structured evidence dictionary for an analysis."""
        analysis = self.get_analysis(analysis_id)
        if not analysis:
            return None

        snapshot_resp: Optional[EvidenceSnapshotResponse] = self.evidence_service.get_snapshot_response(analysis_id)
        if not snapshot_resp:
            return None

        source_info = snapshot_resp.source_traceability
        score_info = snapshot_resp.score
        cls_info = snapshot_resp.classification
        rules = snapshot_resp.rules

        # Build detailed rule summaries
        rule_details = []
        for r in rules:
            rule_details.append({
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "outcome": r.outcome,
                "weight": r.weight,
                "threshold": r.threshold,
                "formula": r.formula,
                "calculated_value": r.calculated_value,
                "input_values": r.input_values,
                "explanation": r.explanation,
                "warnings": r.warnings,
            })

        structured_facts = {
            "analysis_id": analysis.analysis_id,
            "evidence_id": snapshot_resp.evidence_id,
            "analysis_timestamp": str(analysis.created_at),
            "trade": {
                "trade_record_id": source_info.trade_record_id,
                "commodity_code": analysis.commodity_code,
                "mineral_type": analysis.mineral_type or "Unknown",
                "reporter_country_code": analysis.reporter_country_code,
                "partner_country_code": analysis.partner_country_code,
                "period": analysis.period,
                "source_payload": source_info.source_payload_snapshot,
            },
            "scoring": {
                "combined_anomaly_score": score_info.combined_anomaly_score,
                "score_completeness": score_info.score_completeness,
                "evaluated_rules": score_info.evaluated_rules,
                "insufficient_rules": score_info.insufficient_rules,
                "flagged_rules": score_info.flagged_rules,
                "sanctions_status": score_info.sanctions_status,
                "sanctions_reference": score_info.sanctions_reference,
            },
            "classification": {
                "classification": cls_info.classification or "UNCLASSIFIED",
                "flag_status": cls_info.flag_status or "UNKNOWN",
                "explanation": cls_info.explanation,
                "thresholds_applied": cls_info.thresholds_applied,
            },
            "ranking": snapshot_resp.ranking.model_dump() if snapshot_resp.ranking else None,
            "rules": rule_details,
            "validation_status": snapshot_resp.validation_status,
        }

        return structured_facts

    def format_facts_as_markdown(self, facts: Dict[str, Any]) -> str:
        """Renders structured facts into a clear markdown briefing block for prompting."""
        t = facts["trade"]
        s = facts["scoring"]
        c = facts["classification"]

        lines = [
            f"### Structured Risk Analysis Evidence: {facts['analysis_id']}",
            f"- Evidence Snapshot ID: {facts['evidence_id']}",
            f"- Commodity / Mineral: {t['commodity_code']} ({t['mineral_type']})",
            f"- Corridor: Reporter {t['reporter_country_code']} -> Partner {t['partner_country_code']} (Period: {t['period']})",
            f"- Numerical Anomaly Score: {s['combined_anomaly_score']:.1f} / 100.0 (Completeness: {s['score_completeness']})",
            f"- Risk Classification: {c['classification']} (Anomaly Status: {c['flag_status']})",
            f"- Sanctions Screening (Rule R5): {s['sanctions_status']}",
            "",
            "#### Evaluated Risk Rules Breakdown:",
        ]

        for r in facts["rules"]:
            lines.append(
                f"- **{r['rule_id']}: {r['rule_name']}**: Outcome = `{r['outcome']}` (Weight: {r['weight']})"
            )
            lines.append(f"  - Formula: `{r['formula']}` | Configured Threshold: `{r['threshold']}`")
            if r["calculated_value"] is not None:
                lines.append(f"  - Calculated Value: {r['calculated_value']:.2f}% | Inputs: {r['input_values']}")
            lines.append(f"  - Finding: {r['explanation']}")

        return "\n".join(lines)
