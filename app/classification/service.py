"""Classification service coordinating risk analysis classification and database persistence."""
import json
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.database.models import RiskAnalysis
from app.classification.engine import classify_risk_score, ClassificationResult
from app.classification.rules import (
    CLASS_GREEN,
    CLASS_AMBER,
    CLASS_RED,
    CLASS_INSUFFICIENT_DATA,
    FLAG_STATUS_FLAGGED,
    FLAG_STATUS_NOT_FLAGGED,
)


class ClassificationService:
    """Service to classify saved Phase 2 risk analysis results and update audits."""

    def __init__(self, db: Session):
        self.db = db

    def classify_analysis(self, analysis: RiskAnalysis) -> Tuple[RiskAnalysis, ClassificationResult]:
        """Evaluates classification rules for an analysis record and persists the classification."""
        flagged = json.loads(analysis.flagged_rules) if isinstance(analysis.flagged_rules, str) else (analysis.flagged_rules or [])
        evaluated = json.loads(analysis.evaluated_rules) if isinstance(analysis.evaluated_rules, str) else (analysis.evaluated_rules or [])
        insufficient = json.loads(analysis.insufficient_rules) if isinstance(analysis.insufficient_rules, str) else (analysis.insufficient_rules or [])

        result = classify_risk_score(
            score=analysis.combined_anomaly_score,
            completeness=analysis.score_completeness,
            flagged_rules=flagged,
            evaluated_rules=evaluated,
            insufficient_rules=insufficient,
        )

        analysis.classification = result.classification
        analysis.flag_status = result.flag_status
        analysis.classification_explanation = result.explanation

        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)

        # Phase 5: Update evidence snapshot & log audit event
        try:
            from app.database.models import EvidenceSnapshot
            from app.audit.service import AuditEventService
            from app.evidence.rules import EVENT_CLASSIFICATION_CREATED

            snap = (
                self.db.query(EvidenceSnapshot)
                .filter(EvidenceSnapshot.analysis_id == analysis.analysis_id)
                .first()
            )
            if snap:
                snap.classification = result.classification
                snap.flag_status = result.flag_status
                snap.classification_explanation = result.explanation
                self.db.commit()

            AuditEventService(self.db).record_event(
                event_type=EVENT_CLASSIFICATION_CREATED,
                related_record_id=analysis.analysis_id,
                operation_status="SUCCESS",
                metadata={
                    "classification": result.classification,
                    "flag_status": result.flag_status,
                    "score": analysis.combined_anomaly_score,
                },
            )
        except Exception:
            pass

        return analysis, result

    def classify_by_id(self, analysis_id: str) -> Optional[Tuple[RiskAnalysis, ClassificationResult]]:
        """Finds a RiskAnalysis by analysis_id, classifies it, and saves."""
        analysis = self.db.query(RiskAnalysis).filter(RiskAnalysis.analysis_id == analysis_id.strip()).first()
        if not analysis:
            return None
        return self.classify_analysis(analysis)

    def classify_batch(
        self,
        analysis_id: Optional[str] = None,
        commodity_code: Optional[str] = None,
        only_unclassified: bool = False,
        limit: int = 100,
    ) -> List[Tuple[RiskAnalysis, ClassificationResult]]:
        """Classifies a batch of stored risk analyses."""
        query = self.db.query(RiskAnalysis)
        if analysis_id:
            query = query.filter(RiskAnalysis.analysis_id == analysis_id.strip())
        if commodity_code:
            query = query.filter(RiskAnalysis.commodity_code == commodity_code.strip())
        if only_unclassified:
            query = query.filter(RiskAnalysis.classification.is_(None))

        records = query.order_by(desc(RiskAnalysis.created_at)).limit(limit).all()
        results = []
        for rec in records:
            res = self.classify_analysis(rec)
            results.append(res)

        return results

    def get_classification_summary(self) -> Dict[str, Any]:
        """Calculates breakdown across classifications and flag statuses."""
        total = self.db.query(RiskAnalysis).count()
        green_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.classification == CLASS_GREEN).count()
        amber_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.classification == CLASS_AMBER).count()
        red_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.classification == CLASS_RED).count()
        insufficient_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.classification == CLASS_INSUFFICIENT_DATA).count()
        unclassified_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.classification.is_(None)).count()

        flagged_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.flag_status == FLAG_STATUS_FLAGGED).count()
        not_flagged_count = self.db.query(RiskAnalysis).filter(RiskAnalysis.flag_status == FLAG_STATUS_NOT_FLAGGED).count()

        return {
            "total_analyses": total,
            "classified_count": total - unclassified_count,
            "unclassified_count": unclassified_count,
            "classification_breakdown": {
                CLASS_GREEN: green_count,
                CLASS_AMBER: amber_count,
                CLASS_RED: red_count,
                CLASS_INSUFFICIENT_DATA: insufficient_count,
            },
            "flag_status_breakdown": {
                FLAG_STATUS_FLAGGED: flagged_count,
                FLAG_STATUS_NOT_FLAGGED: not_flagged_count,
            },
        }
