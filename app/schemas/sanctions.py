"""Pydantic schemas for OFAC Sanctions records."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class SanctionsRecordResponse(BaseModel):
    id: int
    source_record_id: str
    source_name: str
    record_hash: str
    entity_type: Optional[str] = None
    primary_name: str
    aliases: Optional[str] = None
    programs: Optional[str] = None
    country: Optional[str] = None
    id_numbers: Optional[str] = None
    remarks: Optional[str] = None
    retrieval_timestamp: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SanctionsRecordListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    records: List[SanctionsRecordResponse]
