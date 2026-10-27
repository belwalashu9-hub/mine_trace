"""Pydantic schemas for trade records."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class TradeRecordBase(BaseModel):
    commodity_code: str
    commodity_description: Optional[str] = None
    mineral_type: str
    flow_type: str  # IMPORT or EXPORT
    reporter_country_code: str
    reporter_country_name: str
    partner_country_code: str
    partner_country_name: str
    period: str
    period_year: int
    period_month: Optional[int] = None
    trade_value_usd: Optional[float] = None
    currency: str = "USD"
    net_weight_kg: Optional[float] = None
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    is_valid: bool = True
    has_warnings: bool = False


class TradeRecordResponse(TradeRecordBase):
    id: int
    source_record_id: Optional[str] = None
    record_hash: str
    retrieval_timestamp: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TradeRecordListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    records: List[TradeRecordResponse]


class MineralSummary(BaseModel):
    commodity_code: str
    description: Optional[str] = None
    mineral_type: str
    record_count: int
