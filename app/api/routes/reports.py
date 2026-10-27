"""FastAPI routes for Phase 7 Printable PDF Evidence Reports."""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.reports.service import PDFReportService
from app.schemas.reports import (
    GeneratePDFReportRequest,
    PDFReportSummary,
    PDFReportListResponse,
    ReportMetadataResponse,
)

router = APIRouter(prefix="/api/v1/reports", tags=["Printable PDF Reports"])


@router.post(
    "/pdf",
    response_model=PDFReportSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a printable PDF evidence report for a saved risk analysis",
    description=(
        "Retrieves authoritative saved risk analysis records and Phase 5 evidence snapshots, "
        "compiles verified rule details, classifications, sanctions screening, and audit events, "
        "and renders a multi-page PDF document stored in controlled local storage."
    ),
)
def generate_pdf_report(
    payload: GeneratePDFReportRequest,
    db: Session = Depends(get_db),
):
    service = PDFReportService(db)
    return service.generate_report(payload)


@router.get(
    "",
    response_model=PDFReportListResponse,
    summary="List generated PDF evidence reports",
    description="Returns a paginated list of generated report metadata records with optional analysis_id filtering.",
)
def list_reports(
    analysis_id: Optional[str] = Query(default=None, description="Filter reports by target risk analysis ID."),
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    db: Session = Depends(get_db),
):
    service = PDFReportService(db)
    return service.list_reports(analysis_id=analysis_id, page=page, page_size=page_size)


@router.get(
    "/{report_id}",
    response_model=ReportMetadataResponse,
    summary="Get report metadata",
    description="Retrieves metadata, file size, SHA-256 hash, and status for a specific report.",
)
def get_report_metadata(
    report_id: str,
    db: Session = Depends(get_db),
):
    service = PDFReportService(db)
    return service.get_report_metadata(report_id)


@router.get(
    "/{report_id}/download",
    summary="Download generated PDF report",
    description=(
        "Safely serves the generated PDF evidence report as an application/pdf attachment. "
        "Verifies that the target file exists within the authorized report storage directory "
        "to prevent path traversal."
    ),
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Returns the generated PDF file stream.",
        },
        400: {"description": "Invalid report ID format."},
        403: {"description": "Access denied: path traversal attempt detected."},
        404: {"description": "Report not found or missing from disk."},
    },
)
def download_pdf_report(
    report_id: str,
    db: Session = Depends(get_db),
):
    service = PDFReportService(db)
    file_path, filename = service.get_report_file_path(report_id)

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
