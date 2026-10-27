"""FastAPI router for Phase 5 Evidence Generation and Validation."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.evidence.service import EvidenceService, EvidenceValidationService
from app.schemas.evidence import (
    EvidenceSnapshotResponse,
    EvidenceValidationResponse,
)

router = APIRouter(prefix="/api/v1/evidence", tags=["Evidence & Traceability"])


@router.get(
    "/{analysis_id}",
    response_model=EvidenceSnapshotResponse,
    summary="Retrieve immutable evidence snapshot for a risk analysis",
    description=(
        "Returns the complete frozen historical evidence snapshot associated with an analysis, "
        "including source data traceability, exact rule inputs, formulas, thresholds, "
        "score aggregation, classification, ranking context, and data-quality warnings."
    ),
)
def get_analysis_evidence(
    analysis_id: str,
    db: Session = Depends(get_db),
):
    service = EvidenceService(db)
    snapshot = service.get_snapshot_response(analysis_id)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence for risk analysis '{analysis_id}' was not found.",
        )
    return snapshot


@router.get(
    "/{analysis_id}/validate",
    response_model=EvidenceValidationResponse,
    summary="Validate evidence consistency, calculations, and traceability",
    description=(
        "Executes a rigorous deterministic validation pass across the saved evidence snapshot. "
        "Verifies rule IDs, versions, thresholds, input-to-output mathematical consistency, "
        "weighted score sums, completeness statuses, classification mapping, and source integrity. "
        "Preserves original evidence without silent alteration."
    ),
)
def validate_analysis_evidence(
    analysis_id: str,
    db: Session = Depends(get_db),
):
    val_service = EvidenceValidationService(db)
    result = val_service.validate_analysis_evidence(analysis_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cannot validate evidence: risk analysis '{analysis_id}' was not found.",
        )
    return result
