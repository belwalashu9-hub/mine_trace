"""FastAPI endpoints for Phase 3 Risk Classification."""
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from app.database.connection import get_db
from app.database.models import RiskAnalysis
from app.classification.rules import (
    CLASSIFICATION_THRESHOLDS_METADATA,
    PROTOTYPE_DISCLAIMER,
)
from app.classification.service import ClassificationService
from app.schemas.classification import (
    ClassificationThresholdsResponse,
    ClassifyRequest,
    ClassificationResultResponse,
    ClassifiedAnalysisListResponse,
    ClassificationSummaryResponse,
)

router = APIRouter(prefix="/api/v1/classification", tags=["Risk Classification Engine"])


def serialize_classified_analysis(a: RiskAnalysis) -> Dict[str, Any]:
    return {
        "analysis_id": a.analysis_id,
        "commodity_code": a.commodity_code,
        "period": a.period,
        "reporter_country_code": a.reporter_country_code,
        "partner_country_code": a.partner_country_code,
        "anomaly_score": a.combined_anomaly_score,
        "score_completeness": a.score_completeness,
        "classification": a.classification or "INSUFFICIENT_DATA",
        "flag_status": a.flag_status or "NOT_FLAGGED",
        "explanation": a.classification_explanation or "Analysis awaiting classification.",
        "warnings": [],
        "disclaimer": PROTOTYPE_DISCLAIMER,
    }


@router.get("/thresholds", response_model=ClassificationThresholdsResponse)
def get_classification_thresholds():
    """
    Returns configured prototype classification thresholds (0–19 GREEN, 20–49 AMBER,
    50–100 RED, and data sufficiency rules) with statistical disclaimer.
    """
    return CLASSIFICATION_THRESHOLDS_METADATA


@router.post("/classify", response_model=List[ClassificationResultResponse], status_code=status.HTTP_200_OK)
def classify_analyses(
    payload: ClassifyRequest = ClassifyRequest(),
    db: Session = Depends(get_db),
):
    """
    Classifies saved Phase 2 risk analyses into GREEN, AMBER, RED, or INSUFFICIENT_DATA.
    Persists classification, flag status, and explanation to local database.
    """
    service = ClassificationService(db)
    classified_items = service.classify_batch(
        analysis_id=payload.analysis_id,
        commodity_code=payload.commodity_code,
        only_unclassified=payload.only_unclassified,
        limit=payload.limit,
    )

    if not classified_items and payload.analysis_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk analysis with ID '{payload.analysis_id}' not found.",
        )

    responses = []
    for analysis, result in classified_items:
        responses.append({
            "analysis_id": analysis.analysis_id,
            "commodity_code": analysis.commodity_code,
            "period": analysis.period,
            "reporter_country_code": analysis.reporter_country_code,
            "partner_country_code": analysis.partner_country_code,
            "anomaly_score": result.anomaly_score,
            "score_completeness": result.score_completeness,
            "classification": result.classification,
            "flag_status": result.flag_status,
            "explanation": result.explanation,
            "warnings": result.warnings,
            "disclaimer": result.disclaimer,
        })
    return responses


@router.get("/results", response_model=ClassifiedAnalysisListResponse)
def list_classified_results(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
    classification: Optional[str] = Query(None, description="Filter by classification (GREEN, AMBER, RED, INSUFFICIENT_DATA)"),
    flag_status: Optional[str] = Query(None, description="Filter by flag status (FLAGGED, NOT_FLAGGED)"),
    commodity_code: Optional[str] = Query(None, description="Filter by commodity code"),
    score_completeness: Optional[str] = Query(None, description="Filter by score completeness"),
    db: Session = Depends(get_db),
):
    """Retrieves paginated classified analyses from local storage with optional filters."""
    query = db.query(RiskAnalysis)
    conditions = []

    if classification:
        conditions.append(RiskAnalysis.classification == classification.strip().upper())
    if flag_status:
        conditions.append(RiskAnalysis.flag_status == flag_status.strip().upper())
    if commodity_code:
        conditions.append(RiskAnalysis.commodity_code == commodity_code.strip())
    if score_completeness:
        conditions.append(RiskAnalysis.score_completeness == score_completeness.strip().upper())

    if conditions:
        query = query.filter(and_(*conditions))

    total = query.count()
    records = query.order_by(desc(RiskAnalysis.created_at), desc(RiskAnalysis.id)).offset(skip).limit(limit).all()

    return ClassifiedAnalysisListResponse(
        total=total,
        skip=skip,
        limit=limit,
        analyses=[serialize_classified_analysis(a) for a in records],
    )


@router.get("/results/{analysis_id}", response_model=ClassificationResultResponse)
def get_classified_result_detail(
    analysis_id: str,
    db: Session = Depends(get_db),
):
    """Retrieves classification details and explanation for a specific analysis run."""
    analysis = db.query(RiskAnalysis).filter(RiskAnalysis.analysis_id == analysis_id.strip()).first()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk analysis with ID '{analysis_id}' not found.",
        )

    # Ensure classified if not already
    if not analysis.classification:
        service = ClassificationService(db)
        analysis, _ = service.classify_analysis(analysis)

    return serialize_classified_analysis(analysis)


@router.get("/summary", response_model=ClassificationSummaryResponse)
def get_classification_summary(db: Session = Depends(get_db)):
    """Returns summary distribution across GREEN, AMBER, RED, INSUFFICIENT_DATA, and flag statuses."""
    service = ClassificationService(db)
    summary_data = service.get_classification_summary()
    return ClassificationSummaryResponse(**summary_data)
