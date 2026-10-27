"""Integration tests for Phase 7 Printable PDF Evidence Reports API routes."""
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.database.models import GeneratedReport
from app.api.routes.reports import (
    generate_pdf_report,
    list_reports,
    get_report_metadata,
    download_pdf_report,
)
from app.schemas.reports import GeneratePDFReportRequest
from tests.test_report_engine import seed_analysis_with_snapshot


def test_generate_pdf_report_endpoint(test_db):
    """POST /api/v1/reports/pdf generates a PDF evidence report and returns its summary."""
    seed_analysis_with_snapshot(test_db, "API-REP-1")

    payload = GeneratePDFReportRequest(
        analysis_id="API-REP-1",
        include_ai_explanation=False,
        notes="FastAPI integration test report.",
    )
    data = generate_pdf_report(payload, db=test_db)

    assert data.report_id.startswith("REP-")
    assert data.analysis_id == "API-REP-1"
    assert data.report_status == "COMPLETED"
    assert data.file_size_bytes > 0
    assert len(data.content_hash) == 64
    assert data.download_url == f"/api/v1/reports/{data.report_id}/download"


def test_generate_pdf_report_nonexistent_analysis_returns_404(test_db):
    """POST /api/v1/reports/pdf returns 404 when target analysis_id does not exist."""
    payload = GeneratePDFReportRequest(analysis_id="DOES-NOT-EXIST-999")
    with pytest.raises(HTTPException) as exc_info:
        generate_pdf_report(payload, db=test_db)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_list_and_get_reports_workflow(test_db):
    """Verify listing generated reports with pagination and retrieving individual metadata."""
    seed_analysis_with_snapshot(test_db, "LIST-REP-1")

    # Generate two reports
    rep1 = generate_pdf_report(
        GeneratePDFReportRequest(analysis_id="LIST-REP-1", include_ai_explanation=False),
        db=test_db,
    )
    rep2 = generate_pdf_report(
        GeneratePDFReportRequest(analysis_id="LIST-REP-1", include_ai_explanation=False),
        db=test_db,
    )

    # List all reports
    list_data = list_reports(page=1, page_size=10, db=test_db)
    assert list_data.total >= 2
    report_ids = [r.report_id for r in list_data.reports]
    assert rep1.report_id in report_ids
    assert rep2.report_id in report_ids

    # List filtered by analysis_id
    filter_data = list_reports(analysis_id="LIST-REP-1", page=1, page_size=10, db=test_db)
    assert filter_data.total >= 2

    # Get single report metadata
    meta_data = get_report_metadata(rep1.report_id, db=test_db)
    assert meta_data.report_id == rep1.report_id
    assert meta_data.analysis_id == "LIST-REP-1"
    assert meta_data.report_status == "COMPLETED"
    assert meta_data.file_size_bytes > 0


def test_download_pdf_report_success(test_db):
    """GET /api/v1/reports/{report_id}/download serves the actual PDF file with valid headers."""
    seed_analysis_with_snapshot(test_db, "DOWNLOAD-1")

    created = generate_pdf_report(
        GeneratePDFReportRequest(analysis_id="DOWNLOAD-1", include_ai_explanation=False),
        db=test_db,
    )

    # Download report
    response = download_pdf_report(created.report_id, db=test_db)
    assert isinstance(response, FileResponse)
    assert response.media_type == "application/pdf"
    assert f'filename="{created.report_id}.pdf"' in response.headers["Content-Disposition"]

    with open(response.path, "rb") as f:
        pdf_bytes = f.read()

    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert pdf_bytes.strip().endswith(b"%%EOF")


def test_download_report_security_and_error_handling(test_db):
    """Verify security guards against path traversal, invalid IDs, and missing files."""
    # 1. Invalid report ID format
    with pytest.raises(HTTPException) as exc_info:
        download_pdf_report("../../etc/passwd", db=test_db)
    assert exc_info.value.status_code in [400, 404]

    # 2. Non-existent report ID
    with pytest.raises(HTTPException) as exc_info:
        download_pdf_report("REP-UNKNOWN-9999", db=test_db)
    assert exc_info.value.status_code == 404

    # 3. Path traversal attack via DB record tampering
    seed_analysis_with_snapshot(test_db, "SEC-ATTACK-1")
    malicious_record = GeneratedReport(
        report_id="REP-ATTACK-001",
        analysis_id="SEC-ATTACK-1",
        file_path="C:\\Windows\\System32\\calc.exe",  # Path outside data/reports
        report_status="COMPLETED",
        created_at=datetime.now(timezone.utc),
    )
    test_db.add(malicious_record)
    test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        download_pdf_report("REP-ATTACK-001", db=test_db)
    assert exc_info.value.status_code == 403
    assert "access denied" in exc_info.value.detail.lower()
