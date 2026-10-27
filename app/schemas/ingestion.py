"""Pydantic schemas for data ingestion endpoints."""
from typing import Optional, List
from pydantic import BaseModel, Field


class TradeIngestionRequest(BaseModel):
    """Parameters for triggering UN Comtrade trade data ingestion."""
    commodity_codes: Optional[List[str]] = Field(
        default=None,
        description="List of HS commodity codes. Defaults to configured critical minerals if empty.",
    )
    periods: Optional[List[str]] = Field(
        default=None,
        description="Periods to fetch, e.g. ['2023', '2024']. Defaults to recent years.",
    )
    fixture_path: Optional[str] = Field(
        default=None,
        description="Optional local fixture file path for testing or offline loading.",
    )


class SanctionsIngestionRequest(BaseModel):
    """Parameters for triggering OFAC Sanctions data ingestion."""
    fixture_path: Optional[str] = Field(
        default=None,
        description="Optional local fixture file path for testing or offline loading.",
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Optional custom URL for OFAC SDN CSV download.",
    )


class IngestionResponse(BaseModel):
    """Response returned upon completion of an ingestion run."""
    run_id: int
    source_name: str
    status: str
    raw_records_count: int
    clean_records_count: int
    error_count: int
    warning_count: int
    message: str
