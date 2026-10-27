"""Cleaning and normalization functions for UN Comtrade and OFAC Sanctions data."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List, Optional

from app.ingestion.validators import (
    validate_commodity_code,
    resolve_mineral_metadata,
    validate_flow_type,
    validate_country,
    validate_period,
    validate_numeric_field,
)


def compute_trade_record_hash(
    reporter_code: str,
    partner_code: str,
    commodity_code: str,
    flow_type: str,
    period: str,
    trade_value: Optional[float] = None,
    net_weight: Optional[float] = None,
) -> str:
    """
    Computes a deterministic SHA-256 hash across canonical trade attributes
    to reliably detect duplicate records and prevent duplicate ingestion.
    """
    canonical_repr = (
        f"{reporter_code.strip().upper()}|"
        f"{partner_code.strip().upper()}|"
        f"{commodity_code.strip()}|"
        f"{flow_type.strip().upper()}|"
        f"{period.strip()}|"
        f"{trade_value if trade_value is not None else 'NULL'}|"
        f"{net_weight if net_weight is not None else 'NULL'}"
    )
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


def compute_ofac_record_hash(
    source_record_id: str,
    primary_name: str,
    entity_type: Optional[str] = None,
    country: Optional[str] = None,
) -> str:
    """Computes a deterministic hash for OFAC sanction entries."""
    canonical_repr = (
        f"{source_record_id.strip()}|"
        f"{primary_name.strip().upper()}|"
        f"{(entity_type or '').strip().upper()}|"
        f"{(country or '').strip().upper()}"
    )
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


def clean_comtrade_record(
    raw: Dict[str, Any],
    retrieval_timestamp: Optional[datetime] = None,
    source_record_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Cleans, validates, and normalizes a single raw record from UN Comtrade API or fixture.
    
    Returns:
        (normalized_dict, quality_issues)
    """
    issues: List[Dict[str, Any]] = []
    timestamp = retrieval_timestamp or datetime.now(timezone.utc)
    
    # Check if raw input is a valid dictionary
    if not isinstance(raw, dict) or not raw:
        issues.append({
            "severity": "ERROR",
            "issue_type": "MALFORMED_RECORD",
            "column_name": None,
            "raw_value": str(raw)[:100],
            "message": "Raw trade record is empty or not a valid JSON object.",
        })
        return None, issues

    # Extract source record identifier if available
    rec_id = (
        source_record_id
        or str(raw.get("id") or raw.get("refId") or raw.get("source_id") or "")
        or None
    )

    # 1. Commodity code
    raw_cmd = raw.get("cmdCode") or raw.get("cmd_code") or raw.get("commodity_code") or raw.get("commodityCode")
    cmd_res = validate_commodity_code(raw_cmd)
    for err in cmd_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_COMMODITY_CODE",
            "column_name": "cmdCode",
            "raw_value": str(raw_cmd),
            "message": err,
        })
    for warn in cmd_res.warnings:
        issues.append({
            "severity": "WARNING",
            "issue_type": "COMMODITY_CODE_FORMAT",
            "column_name": "cmdCode",
            "raw_value": str(raw_cmd),
            "message": warn,
        })

    # 2. Trade Flow
    raw_flow = raw.get("flowCode") or raw.get("flow_code") or raw.get("flow_type") or raw.get("flowDesc")
    flow_res = validate_flow_type(raw_flow)
    for err in flow_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_FLOW_TYPE",
            "column_name": "flowCode",
            "raw_value": str(raw_flow),
            "message": err,
        })
    for warn in flow_res.warnings:
        issues.append({
            "severity": "WARNING",
            "issue_type": "FLOW_TYPE_NORMALIZATION",
            "column_name": "flowCode",
            "raw_value": str(raw_flow),
            "message": warn,
        })

    # 3. Reporter country
    raw_rep = raw.get("reporterCode") or raw.get("reporter_code") or raw.get("reporterISO")
    raw_rep_name = raw.get("reporterDesc") or raw.get("reporter_name")
    rep_res = validate_country(raw_rep, raw_rep_name)
    for err in rep_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_REPORTER_COUNTRY",
            "column_name": "reporterCode",
            "raw_value": str(raw_rep),
            "message": err,
        })
    for warn in rep_res.warnings:
        issues.append({
            "severity": "WARNING",
            "issue_type": "COUNTRY_NORMALIZATION",
            "column_name": "reporterCode",
            "raw_value": str(raw_rep),
            "message": warn,
        })

    # 4. Partner country
    raw_prt = raw.get("partnerCode") or raw.get("partner_code") or raw.get("partnerISO")
    raw_prt_name = raw.get("partnerDesc") or raw.get("partner_name")
    prt_res = validate_country(raw_prt, raw_prt_name)
    for err in prt_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_PARTNER_COUNTRY",
            "column_name": "partnerCode",
            "raw_value": str(raw_prt),
            "message": err,
        })
    for warn in prt_res.warnings:
        issues.append({
            "severity": "WARNING",
            "issue_type": "COUNTRY_NORMALIZATION",
            "column_name": "partnerCode",
            "raw_value": str(raw_prt),
            "message": warn,
        })

    # 5. Period
    raw_prd = raw.get("period") or raw.get("period_str") or raw.get("refYear") or raw.get("period_year")
    prd_res = validate_period(raw_prd)
    for err in prd_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_PERIOD",
            "column_name": "period",
            "raw_value": str(raw_prd),
            "message": err,
        })

    # 6. Trade Value (USD)
    raw_val = raw.get("primaryValue") or raw.get("trade_value_usd") or raw.get("cifvalue") or raw.get("fobvalue") or raw.get("tradeValue")
    val_res = validate_numeric_field(raw_val, "trade_value_usd", allow_null=True)
    for err in val_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_NUMERIC_VALUE",
            "column_name": "primaryValue",
            "raw_value": str(raw_val),
            "message": err,
        })
    for warn in val_res.warnings:
        issues.append({
            "severity": "WARNING",
            "issue_type": "TRADE_VALUE_WARNING",
            "column_name": "primaryValue",
            "raw_value": str(raw_val),
            "message": warn,
        })

    # 7. Net weight (kg)
    raw_wt = raw.get("netWgt") or raw.get("net_weight_kg") or raw.get("netWeight")
    wt_res = validate_numeric_field(raw_wt, "net_weight_kg", allow_null=True)
    for err in wt_res.errors:
        issues.append({
            "severity": "ERROR",
            "issue_type": "INVALID_NUMERIC_WEIGHT",
            "column_name": "netWgt",
            "raw_value": str(raw_wt),
            "message": err,
        })

    # 8. Quantity
    raw_qty = raw.get("qty") or raw.get("quantity")
    qty_res = validate_numeric_field(raw_qty, "quantity", allow_null=True)
    raw_qty_unit = raw.get("qtyUnitAbbr") or raw.get("quantity_unit") or raw.get("qtyUnitDesc")

    # Critical fatal errors disqualify the record from normalized insertion
    has_critical_error = not (
        cmd_res.is_valid
        and flow_res.is_valid
        and rep_res.is_valid
        and prt_res.is_valid
        and prd_res.is_valid
    )
    if has_critical_error:
        return None, issues

    # Description and mineral category
    clean_cmd = cmd_res.value
    desc, mtype = resolve_mineral_metadata(clean_cmd)
    custom_desc = raw.get("cmdDesc") or raw.get("commodity_description")
    if custom_desc:
        desc = str(custom_desc).strip()

    rep_iso, rep_name = rep_res.value
    prt_iso, prt_name = prt_res.value
    period_str, year, month = prd_res.value

    # Compute deduplication hash
    record_hash = compute_trade_record_hash(
        reporter_code=rep_iso,
        partner_code=prt_iso,
        commodity_code=clean_cmd,
        flow_type=flow_res.value,
        period=period_str,
        trade_value=val_res.value,
        net_weight=wt_res.value,
    )

    has_warnings = any(i["severity"] == "WARNING" for i in issues)

    normalized = {
        "source_record_id": rec_id,
        "record_hash": record_hash,
        "commodity_code": clean_cmd,
        "commodity_description": desc,
        "mineral_type": mtype,
        "flow_type": flow_res.value,
        "reporter_country_code": rep_iso,
        "reporter_country_name": rep_name,
        "partner_country_code": prt_iso,
        "partner_country_name": prt_name,
        "period": period_str,
        "period_year": year,
        "period_month": month,
        "trade_value_usd": val_res.value,  # preserves None if missing
        "currency": "USD",
        "net_weight_kg": wt_res.value,     # preserves None if missing
        "quantity": qty_res.value,         # preserves None if missing
        "quantity_unit": str(raw_qty_unit).strip() if raw_qty_unit else None,
        "is_valid": True,
        "has_warnings": has_warnings,
        "retrieval_timestamp": timestamp,
    }

    return normalized, issues


def clean_ofac_record(
    raw_row: Dict[str, Any],
    retrieval_timestamp: Optional[datetime] = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Cleans and normalizes an OFAC Specially Designated Nationals (SDN) record.
    Standard OFAC SDN CSV columns:
    Ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage, GRT, Vess_flag, Vess_owner, Remarks
    """
    issues: List[Dict[str, Any]] = []
    timestamp = retrieval_timestamp or datetime.now(timezone.utc)

    # Ent_num is the official unique identifier
    ent_num = str(
        raw_row.get("Ent_num")
        or raw_row.get("ent_num")
        or raw_row.get("uid")
        or raw_row.get("source_record_id")
        or ""
    ).strip()

    if not ent_num or ent_num in ("-0-", "null", "none"):
        issues.append({
            "severity": "ERROR",
            "issue_type": "MISSING_OFAC_ID",
            "column_name": "Ent_num",
            "raw_value": str(ent_num),
            "message": "OFAC record is missing Ent_num unique identifier.",
        })
        return None, issues

    raw_name = str(
        raw_row.get("SDN_Name")
        or raw_row.get("name")
        or raw_row.get("primary_name")
        or ""
    ).strip()

    if not raw_name or raw_name == "-0-":
        issues.append({
            "severity": "ERROR",
            "issue_type": "MISSING_OFAC_NAME",
            "column_name": "SDN_Name",
            "raw_value": str(raw_name),
            "message": "OFAC record is missing primary name.",
        })
        return None, issues

    entity_type = str(
        raw_row.get("SDN_Type") or raw_row.get("entity_type") or "entity"
    ).strip().lower()
    if entity_type == "-0-":
        entity_type = "entity"

    program = str(raw_row.get("Program") or raw_row.get("programs") or "").strip()
    if program == "-0-":
        program = None

    remarks = str(raw_row.get("Remarks") or raw_row.get("remarks") or "").strip()
    if remarks == "-0-":
        remarks = None

    country = str(raw_row.get("country") or raw_row.get("Country") or "").strip()
    if country == "-0-":
        country = None

    aliases = str(raw_row.get("aliases") or raw_row.get("alt_names") or "").strip()
    if aliases == "-0-":
        aliases = None

    id_numbers = str(raw_row.get("id_numbers") or raw_row.get("ids") or "").strip()
    if id_numbers == "-0-":
        id_numbers = None

    record_hash = compute_ofac_record_hash(
        source_record_id=ent_num,
        primary_name=raw_name,
        entity_type=entity_type,
        country=country,
    )

    normalized = {
        "source_record_id": ent_num,
        "source_name": "OFAC_SDN",
        "record_hash": record_hash,
        "entity_type": entity_type,
        "primary_name": raw_name,
        "aliases": aliases,
        "programs": program,
        "country": country,
        "id_numbers": id_numbers,
        "remarks": remarks,
        "retrieval_timestamp": timestamp,
    }

    return normalized, issues
