"""FastAPI routes for Phase 2 Risk Detection and Scoring Engine."""
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.repository import MineTraceRepository
from app.database.models import RiskAnalysis
from app.risk.rules import get_rule_catalog_list
from app.risk.service import RiskEngineService
from app.schemas.risk import (
    RuleMetadataResponse,
    RiskAnalysisResponse,
    RiskAnalysisListResponse,
    RiskAnalysisRequest,
    RiskSummaryResponse,
)

router = APIRouter(prefix="/api/v1/risk", tags=["Risk Intelligence Engine"])


def serialize_risk_analysis(a: RiskAnalysis) -> Dict[str, Any]:
    """Helper to deserialize JSON columns into structured lists/dicts for Pydantic response."""
    return {
        "analysis_id": a.analysis_id,
        "trade_record_id": a.trade_record_id,
        "commodity_code": a.commodity_code,
        "mineral_type": a.mineral_type,
        "reporter_country_code": a.reporter_country_code,
        "partner_country_code": a.partner_country_code,
        "period": a.period,
        "combined_anomaly_score": a.combined_anomaly_score,
        "score_completeness": a.score_completeness,
        "evaluated_rules": json.loads(a.evaluated_rules) if isinstance(a.evaluated_rules, str) else (a.evaluated_rules or []),
        "insufficient_rules": json.loads(a.insufficient_rules) if isinstance(a.insufficient_rules, str) else (a.insufficient_rules or []),
        "flagged_rules": json.loads(a.flagged_rules) if isinstance(a.flagged_rules, str) else (a.flagged_rules or []),
        "sanctions_status": a.sanctions_status,
        "sanctions_reference": a.sanctions_reference,
        "classification": a.classification,
        "flag_status": a.flag_status,
        "classification_explanation": a.classification_explanation,
        "created_at": a.created_at,
        "rule_results": [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "rule_version": r.rule_version,
                "weight": r.weight,
                "outcome": r.outcome,
                "threshold": r.threshold,
                "formula": r.formula,
                "calculated_value": r.calculated_value,
                "input_values": json.loads(r.input_values) if isinstance(r.input_values, str) else (r.input_values or {}),
                "explanation": r.explanation,
                "warnings": json.loads(r.warnings) if isinstance(r.warnings, str) and r.warnings else [],
            }
            for r in a.rule_results
        ],
    }


@router.get("/rules", response_model=List[RuleMetadataResponse])
def get_risk_rules():
    """Returns rule IDs, descriptions, formulas, thresholds, weights, and versions."""
    return get_rule_catalog_list()


@router.post("/analyze", response_model=List[RiskAnalysisResponse], status_code=status.HTTP_200_OK)
def run_risk_analysis(
    payload: RiskAnalysisRequest = RiskAnalysisRequest(),
    db: Session = Depends(get_db),
):
    """
    Executes the deterministic 5-rule risk engine on eligible local trade records.
    Persists rule-by-rule inputs, calculations, and combined anomaly scores.
    """
    service = RiskEngineService(db)
    analyses = service.run_analysis_batch(
        trade_record_id=payload.trade_record_id,
        commodity_code=payload.commodity_code,
        reporter_country_code=payload.reporter_country_code,
        period_year=payload.period_year,
        limit=payload.limit,
        entity_name=payload.entity_name,
    )

    if not analyses and payload.trade_record_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trade record with ID {payload.trade_record_id} not found in local database.",
        )

    return [serialize_risk_analysis(a) for a in analyses]


@router.get("/results", response_model=RiskAnalysisListResponse)
def list_risk_results(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination page limit"),
    commodity_code: Optional[str] = Query(None, description="Filter by HS commodity code"),
    score_completeness: Optional[str] = Query(None, description="Filter by completeness (COMPLETE, PARTIAL, UNAVAILABLE)"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Filter by minimum anomaly score"),
    sanctions_status: Optional[str] = Query(None, description="Filter by sanctions status (REVIEW_MATCH, NO_IDENTIFIED_MATCH, UNKNOWN)"),
    db: Session = Depends(get_db),
):
    """
    Retrieves stored historical risk analysis results with filtering and pagination.
    Does not recalculate results during retrieval.
    """
    repo = MineTraceRepository(db)
    records, total = repo.list_risk_analyses(
        skip=skip,
        limit=limit,
        commodity_code=commodity_code,
        score_completeness=score_completeness,
        min_score=min_score,
        sanctions_status=sanctions_status,
    )

    return RiskAnalysisListResponse(
        total=total,
        skip=skip,
        limit=limit,
        analyses=[serialize_risk_analysis(a) for a in records],
    )


@router.get("/results/{analysis_id}", response_model=RiskAnalysisResponse)
def get_risk_analysis_detail(
    analysis_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves a single saved analysis with rule-by-rule inputs, calculations,
    explanations, score completeness, and sanctions status.
    """
    repo = MineTraceRepository(db)
    analysis = repo.get_risk_analysis_by_id(analysis_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk analysis with ID '{analysis_id}' not found.",
        )

    return serialize_risk_analysis(analysis)


@router.get("/summary", response_model=RiskSummaryResponse)
def get_risk_summary(db: Session = Depends(get_db)):
    """
    Returns summary statistics from stored analyses, distinguishing complete,
    partial, and unavailable scores without interpreting missing data as zero risk.
    """
    repo = MineTraceRepository(db)
    summary_dict = repo.get_risk_summary()
    return RiskSummaryResponse(**summary_dict)
