"""Pydantic schemas for Phase 7 Printable PDF Evidence Reports."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class GeneratePDFReportRequest(BaseModel):
    """Request payload for generating a printable PDF evidence report."""
    analysis_id: str = Field(
        ...,
        description="Target risk analysis ID to generate the PDF report for.",
        examples=["ANALYSIS-CHL-USA-2023-LITHIUM"],
    )
    include_ai_explanation: bool = Field(
        default=True,
        description="Whether to include a validated Phase 6 AI explanation if available.",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional analyst notes or scope annotations to display on the report cover.",
    )


class PDFReportSummary(BaseModel):
    """Summary of a generated PDF evidence report."""
    report_id: str = Field(..., description="Unique UUID for this generated report.")
    analysis_id: str = Field(..., description="Associated risk analysis identifier.")
    evidence_snapshot_id: Optional[str] = Field(default=None, description="Frozen Phase 5 evidence snapshot ID.")
    template_version: str = Field(default="1.0", description="Report template schema version.")
    report_title: str = Field(default="Critical Mineral Supply-Chain Risk Assessment", description="Report document title.")
    file_path: str = Field(..., description="Sanitized relative or internal storage reference.")
    file_size_bytes: Optional[int] = Field(default=None, description="Size of generated PDF in bytes.")
    content_hash: Optional[str] = Field(default=None, description="SHA-256 integrity hash of PDF file.")
    report_status: str = Field(default="COMPLETED", description="Report generation status: COMPLETED, FAILED, WARNING.")
    has_evidence_snapshot: bool = Field(default=True, description="True if based on a frozen Phase 5 evidence snapshot.")
    has_validated_ai_explanation: bool = Field(default=False, description="True if a validated AI explanation was included.")
    notes: Optional[str] = Field(default=None, description="Optional analyst notes included in the report.")
    download_url: str = Field(..., description="API endpoint to download the generated PDF file.")
    created_at: datetime = Field(..., description="Timestamp when report PDF was generated.")

    model_config = ConfigDict(from_attributes=True)


class PDFReportListResponse(BaseModel):
    """Paginated list of generated PDF reports."""
    total: int = Field(..., description="Total number of reports matching query.")
    page: int = Field(..., description="Current page number.")
    page_size: int = Field(..., description="Items per page.")
    total_pages: int = Field(..., description="Total pages available.")
    reports: List[PDFReportSummary] = Field(default_factory=list, description="List of report summaries.")


class ReportMetadataResponse(BaseModel):
    """Detailed metadata and audit information for a specific generated report."""
    report_id: str
    analysis_id: str
    evidence_snapshot_id: Optional[str]
    template_version: str
    report_title: str
    file_size_bytes: Optional[int]
    content_hash: Optional[str]
    report_status: str
    has_evidence_snapshot: bool
    has_validated_ai_explanation: bool
    notes: Optional[str]
    download_url: str
    created_at: datetime
    metadata_snapshot: Optional[Dict[str, Any]] = None
