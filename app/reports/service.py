"""Service coordinating report data compilation, PDF generation, filesystem storage, and auditing."""
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import GeneratedReport
from app.audit.service import AuditEventService
from app.reports.rules import (
    REPORT_TITLE,
    REPORT_TEMPLATE_VERSION,
    EVENT_REPORT_GENERATED,
    EVENT_REPORT_DOWNLOADED,
)
from app.reports.data_service import ReportDataService
from app.reports.pdf_generator import PDFReportGenerator
from app.schemas.reports import (
    GeneratePDFReportRequest,
    PDFReportSummary,
    PDFReportListResponse,
    ReportMetadataResponse,
)

settings = get_settings()


class PDFReportService:
    """Manages creation, indexing, retrieval, and download of printable PDF evidence reports."""

    def __init__(self, db: Session, reports_dir: Optional[Path] = None):
        self.db = db
        self.reports_dir = (reports_dir or settings.report_output_dir).resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.data_service = ReportDataService(db)
        self.generator = PDFReportGenerator()
        self.audit = AuditEventService(db)

    def generate_report(self, request: GeneratePDFReportRequest) -> PDFReportSummary:
        """
        Compiles authoritative analysis and evidence snapshot, generates a PDF,
        saves to controlled storage, indexes metadata in SQLite, and logs an audit event.
        """
        a_id = request.analysis_id.strip()
        report_id = f"REP-{uuid.uuid4().hex[:12].upper()}"

        # 1. Compile report bundle (raises 404 if analysis not found)
        bundle = self.data_service.compile_report_data(
            analysis_id=a_id,
            include_ai_explanation=request.include_ai_explanation,
            notes=request.notes,
        )

        bundle["metadata"]["report_id"] = report_id

        # 2. Render PDF bytes
        try:
            pdf_bytes = self.generator.generate_pdf(bundle)
        except Exception as exc:
            logger.error(f"Failed to generate PDF for analysis '{a_id}': {exc}", exc_info=True)
            # Log failure in audit
            try:
                self.audit.record_event(
                    event_type=EVENT_REPORT_GENERATED,
                    related_record_id=a_id,
                    operation_status="FAILED",
                    error_details=f"PDF rendering error: {str(exc)}",
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while generating the PDF evidence report.",
            )

        # 3. Calculate SHA-256 and save file safely
        content_hash = hashlib.sha256(pdf_bytes).hexdigest()
        file_size = len(pdf_bytes)

        safe_filename = f"{report_id}.pdf"
        target_path = self.reports_dir / safe_filename

        try:
            with open(target_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as exc:
            logger.error(f"Failed to write PDF to storage {target_path}: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to store generated PDF in configured report storage directory.",
            )

        # 4. Save metadata record in database
        has_snapshot = bundle["metadata"]["has_evidence_snapshot"]
        has_ai = bundle["ai_explanation"]["available"]

        meta_summary = {
            "mineral": bundle["executive_summary"]["mineral_type"],
            "score": bundle["executive_summary"]["combined_anomaly_score"],
            "completeness": bundle["executive_summary"]["score_completeness"],
            "classification": bundle["executive_summary"]["classification"],
            "sanctions_status": bundle["executive_summary"]["sanctions_status"],
        }

        report_record = GeneratedReport(
            report_id=report_id,
            analysis_id=a_id,
            evidence_snapshot_id=bundle["metadata"]["evidence_snapshot_id"],
            template_version=REPORT_TEMPLATE_VERSION,
            report_title=REPORT_TITLE,
            file_path=str(target_path),
            file_size_bytes=file_size,
            content_hash=content_hash,
            report_status="COMPLETED",
            has_evidence_snapshot=has_snapshot,
            has_validated_ai_explanation=has_ai,
            notes=request.notes,
            metadata_snapshot=json.dumps(meta_summary),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(report_record)
        self.db.commit()
        self.db.refresh(report_record)

        # 5. Record Phase 5 audit event
        try:
            self.audit.record_event(
                event_type=EVENT_REPORT_GENERATED,
                related_record_id=report_id,
                operation_status="SUCCESS",
                metadata={
                    "analysis_id": a_id,
                    "evidence_snapshot_id": bundle["metadata"]["evidence_snapshot_id"],
                    "file_size_bytes": file_size,
                    "content_hash": content_hash,
                    "has_evidence_snapshot": has_snapshot,
                    "has_validated_ai_explanation": has_ai,
                },
            )
        except Exception:
            pass

        return self._to_summary(report_record)

    def list_reports(
        self,
        analysis_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PDFReportListResponse:
        """Retrieves paginated list of generated report metadata records."""
        query = self.db.query(GeneratedReport)
        if analysis_id and isinstance(analysis_id, str) and analysis_id.strip():
            query = query.filter(GeneratedReport.analysis_id == analysis_id.strip())

        total = query.count()
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        offset = (page - 1) * page_size

        records = (
            query.order_by(desc(GeneratedReport.created_at))
            .offset(offset)
            .limit(page_size)
            .all()
        )

        summaries = [self._to_summary(r) for r in records]

        return PDFReportListResponse(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            reports=summaries,
        )

    def get_report_metadata(self, report_id: str) -> ReportMetadataResponse:
        """Retrieves metadata for a specific report."""
        record = self._get_record(report_id)
        meta_dict = None
        if record.metadata_snapshot:
            try:
                meta_dict = json.loads(record.metadata_snapshot)
            except Exception:
                meta_dict = {"raw": record.metadata_snapshot}

        return ReportMetadataResponse(
            report_id=record.report_id,
            analysis_id=record.analysis_id,
            evidence_snapshot_id=record.evidence_snapshot_id,
            template_version=record.template_version,
            report_title=record.report_title,
            file_size_bytes=record.file_size_bytes,
            content_hash=record.content_hash,
            report_status=record.report_status,
            has_evidence_snapshot=record.has_evidence_snapshot,
            has_validated_ai_explanation=record.has_validated_ai_explanation,
            notes=record.notes,
            download_url=f"/api/v1/reports/{record.report_id}/download",
            created_at=record.created_at,
            metadata_snapshot=meta_dict,
        )

    def get_report_file_path(self, report_id: str) -> Tuple[Path, str]:
        """
        Retrieves file path for report download with strict path traversal protection.
        Returns (resolved_file_path, download_filename).
        """
        # Validate report_id format to prevent injection
        r_id = report_id.strip()
        if not re.match(r"^REP-[A-Za-z0-9_-]+$", r_id) and not re.match(r"^[0-9a-fA-F-]{36}$", r_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid report ID format.",
            )

        record = self._get_record(r_id)

        # Path traversal guard
        file_path = Path(record.file_path).resolve()
        try:
            file_path.relative_to(self.reports_dir.resolve())
        except ValueError:
            logger.warning(f"Path traversal attempt detected for report {r_id}: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: report file path is outside the authorized storage directory.",
            )

        if not file_path.exists() or not file_path.is_file():
            logger.error(f"Report file missing on disk: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report file for '{r_id}' is missing or corrupted on disk.",
            )

        # Log download in audit
        try:
            self.audit.record_event(
                event_type=EVENT_REPORT_DOWNLOADED,
                related_record_id=r_id,
                operation_status="SUCCESS",
                metadata={"file_size": record.file_size_bytes},
            )
        except Exception:
            pass

        filename = f"{r_id}.pdf"
        return file_path, filename

    def _get_record(self, report_id: str) -> GeneratedReport:
        record: Optional[GeneratedReport] = (
            self.db.query(GeneratedReport)
            .filter(GeneratedReport.report_id == report_id.strip())
            .first()
        )
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID '{report_id}' was not found.",
            )
        return record

    def _to_summary(self, record: GeneratedReport) -> PDFReportSummary:
        return PDFReportSummary(
            report_id=record.report_id,
            analysis_id=record.analysis_id,
            evidence_snapshot_id=record.evidence_snapshot_id,
            template_version=record.template_version,
            report_title=record.report_title,
            file_path=Path(record.file_path).name,  # Sanitize to filename only
            file_size_bytes=record.file_size_bytes,
            content_hash=record.content_hash,
            report_status=record.report_status,
            has_evidence_snapshot=record.has_evidence_snapshot,
            has_validated_ai_explanation=record.has_validated_ai_explanation,
            notes=record.notes,
            download_url=f"/api/v1/reports/{record.report_id}/download",
            created_at=record.created_at,
        )
