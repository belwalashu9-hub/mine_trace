"""Validation functions for trade and sanctions data fields."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, List, Tuple

# Mineral mapping for common critical minerals
COMMODITY_MINERAL_MAP = {
    # Lithium
    "283691": ("Lithium Carbonate", "Lithium"),
    "282520": ("Lithium Hydroxide and Oxide", "Lithium"),
    "253090": ("Mineral Substances NES (Spodumene / Lepidolite)", "Lithium"),
    "850760": ("Lithium-ion Accumulators (Batteries)", "Lithium"),
    # Cobalt
    "260500": ("Cobalt Ores and Concentrates", "Cobalt"),
    "810520": ("Cobalt Mattes and Intermediate Products", "Cobalt"),
    # Nickel
    "260400": ("Nickel Ores and Concentrates", "Nickel"),
    "750110": ("Nickel Mattes", "Nickel"),
    # Graphite
    "250410": ("Natural Graphite in Powder or Flakes", "Graphite"),
    # Rare Earth Elements
    "280530": ("Rare-Earth Metals, Scandium and Yttrium", "Rare Earths"),
}

# Standard UN / ISO country mappings (commonly occurring codes in Comtrade)
COUNTRY_MAP = {
    # UN codes
    "0": ("WLD", "World"),
    "36": ("AUS", "Australia"),
    "76": ("BRA", "Brazil"),
    "124": ("CAN", "Canada"),
    "152": ("CHL", "Chile"),
    "156": ("CHN", "China"),
    "180": ("COD", "Democratic Republic of the Congo"),
    "276": ("DEU", "Germany"),
    "356": ("IND", "India"),
    "360": ("IDN", "Indonesia"),
    "392": ("JPN", "Japan"),
    "410": ("KOR", "Republic of Korea"),
    "643": ("RUS", "Russian Federation"),
    "702": ("SGP", "Singapore"),
    "710": ("ZAF", "South Africa"),
    "842": ("USA", "United States"),
    "858": ("URY", "Uruguay"),
    "862": ("VEN", "Venezuela"),
    "716": ("ZWE", "Zimbabwe"),
    # ISO-3 aliases
    "AUS": ("AUS", "Australia"),
    "CHL": ("CHL", "Chile"),
    "CHN": ("CHN", "China"),
    "USA": ("USA", "United States"),
    "ARG": ("ARG", "Argentina"),
    "COD": ("COD", "Democratic Republic of the Congo"),
    "DEU": ("DEU", "Germany"),
    "JPN": ("JPN", "Japan"),
    "KOR": ("KOR", "Republic of Korea"),
    "IDN": ("IDN", "Indonesia"),
    "ZWE": ("ZWE", "Zimbabwe"),
    "CAN": ("CAN", "Canada"),
    "BRA": ("BRA", "Brazil"),
    "RUS": ("RUS", "Russian Federation"),
    "IND": ("IND", "India"),
}


@dataclass
class FieldValidationResult:
    value: Any
    is_valid: bool = True
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def validate_commodity_code(raw_code: Any) -> FieldValidationResult:
    """Normalizes and validates HS commodity code."""
    if raw_code is None or str(raw_code).strip() == "":
        return FieldValidationResult(
            value=None,
            is_valid=False,
            errors=["Missing commodity code"],
        )
    
    # Strip dots, spaces, dashes (e.g. 2836.91 -> 283691)
    clean_code = re.sub(r"[^\d]", "", str(raw_code).strip())
    
    if len(clean_code) < 2:
        return FieldValidationResult(
            value=clean_code,
            is_valid=False,
            errors=[f"Commodity code '{raw_code}' is too short"],
        )
        
    warnings = []
    if len(clean_code) < 6:
        warnings.append(f"Commodity code '{clean_code}' is a 2 or 4-digit HS chapter/heading, not 6-digit subheading.")
        
    return FieldValidationResult(value=clean_code, is_valid=True, warnings=warnings)


def resolve_mineral_metadata(clean_commodity_code: str) -> Tuple[str, str]:
    """Returns (commodity_description, mineral_type) for a given code."""
    if clean_commodity_code in COMMODITY_MINERAL_MAP:
        desc, mtype = COMMODITY_MINERAL_MAP[clean_commodity_code]
        return desc, mtype
    
    # Prefix match (e.g. 2836 -> Lithium Carbonates family)
    for code_prefix, (desc, mtype) in COMMODITY_MINERAL_MAP.items():
        if clean_commodity_code.startswith(code_prefix[:4]):
            return desc, mtype
            
    return f"HS Code {clean_commodity_code}", "Critical Mineral"


def validate_flow_type(raw_flow: Any) -> FieldValidationResult:
    """Normalizes trade flow strictly to 'IMPORT' or 'EXPORT'."""
    if raw_flow is None:
        return FieldValidationResult(
            value=None,
            is_valid=False,
            errors=["Missing trade flow type"],
        )
        
    flow_str = str(raw_flow).strip().upper()
    
    # UN Comtrade flow codes: 1=Imports, 2=Exports, M=Imports, X=Exports
    if flow_str in ("1", "M", "IMPORT", "IMPORTS", "M - IMPORT"):
        return FieldValidationResult(value="IMPORT", is_valid=True)
    elif flow_str in ("2", "X", "EXPORT", "EXPORTS", "X - EXPORT"):
        return FieldValidationResult(value="EXPORT", is_valid=True)
    elif flow_str in ("RE-IMPORT", "RE-EXPORT"):
        # Re-imports/re-exports preserve direction with a warning
        flow = "IMPORT" if "IMPORT" in flow_str else "EXPORT"
        return FieldValidationResult(
            value=flow,
            is_valid=True,
            warnings=[f"Re-trade flow '{flow_str}' mapped to '{flow}'"],
        )
        
    return FieldValidationResult(
        value=flow_str,
        is_valid=False,
        errors=[f"Unrecognized trade flow: '{raw_flow}'. Must be Import or Export."],
    )


def validate_country(raw_country: Any, raw_name: Optional[Any] = None) -> FieldValidationResult:
    """Normalizes country code and name."""
    if raw_country is None or str(raw_country).strip() == "":
        return FieldValidationResult(
            value=("UNKNOWN", "Unknown Country"),
            is_valid=False,
            errors=["Missing country identifier"],
        )
        
    clean_code = str(raw_country).strip()
    clean_name = str(raw_name).strip() if raw_name else None
    
    # Lookup in known country dictionary
    if clean_code in COUNTRY_MAP:
        iso_code, name = COUNTRY_MAP[clean_code]
        return FieldValidationResult(value=(iso_code, clean_name or name), is_valid=True)
        
    # Check if code looks like ISO 2 or 3 letter alphabetic code
    if clean_code.isalpha() and 2 <= len(clean_code) <= 3:
        iso = clean_code.upper()
        return FieldValidationResult(
            value=(iso, clean_name or iso),
            is_valid=True,
            warnings=[f"Unmapped ISO country code: {iso}"],
        )
        
    # Numeric UN M49 code fallback
    if clean_code.isdigit():
        return FieldValidationResult(
            value=(f"UN_{clean_code}", clean_name or f"Country {clean_code}"),
            is_valid=True,
            warnings=[f"Numeric country code {clean_code} used without ISO3 mapping"],
        )
        
    return FieldValidationResult(
        value=(clean_code[:16].upper(), clean_name or clean_code),
        is_valid=True,
        warnings=[f"Custom country identifier: {clean_code}"],
    )


def validate_period(raw_period: Any) -> FieldValidationResult:
    """Validates period and extracts period_string, year, and optional month."""
    if raw_period is None or str(raw_period).strip() == "":
        return FieldValidationResult(
            value=(None, None, None),
            is_valid=False,
            errors=["Missing period"],
        )
        
    period_str = str(raw_period).strip()
    # Normalize formats like 2023, 202301, 2023-01
    match_ym = re.match(r"^(\d{4})[-/]?(\d{2})$", period_str)
    match_y = re.match(r"^(\d{4})$", period_str)
    
    if match_ym:
        year = int(match_ym.group(1))
        month = int(match_ym.group(2))
        if not (1 <= month <= 12):
            return FieldValidationResult(
                value=(period_str, year, None),
                is_valid=False,
                errors=[f"Invalid month in period: '{period_str}'"],
            )
        formatted = f"{year}-{month:02d}"
        return FieldValidationResult(value=(formatted, year, month), is_valid=True)
        
    elif match_y:
        year = int(match_y.group(1))
        if not (1990 <= year <= 2035):
            return FieldValidationResult(
                value=(str(year), year, None),
                is_valid=False,
                errors=[f"Period year {year} is out of realistic trade data range (1990-2035)"],
            )
        return FieldValidationResult(value=(str(year), year, None), is_valid=True)
        
    return FieldValidationResult(
        value=(period_str, None, None),
        is_valid=False,
        errors=[f"Unrecognized date/period format: '{period_str}'"],
    )


def validate_numeric_field(
    raw_val: Any,
    field_name: str,
    allow_null: bool = True,
) -> FieldValidationResult:
    """
    Validates numeric values (trade_value, weight, quantity).
    Crucial rule: NEVER convert missing/null into 0.0! Missing stays None.
    """
    if raw_val is None or str(raw_val).strip() == "" or str(raw_val).strip().lower() in ("nan", "null", "none"):
        if allow_null:
            return FieldValidationResult(value=None, is_valid=True)
        return FieldValidationResult(
            value=None,
            is_valid=False,
            errors=[f"Field '{field_name}' cannot be null"],
        )
        
    try:
        # Strip currency symbols, commas
        clean_str = re.sub(r"[\$,\s]", "", str(raw_val).strip())
        val = float(clean_str)
        
        if val < 0:
            return FieldValidationResult(
                value=None,
                is_valid=False,
                errors=[f"Field '{field_name}' cannot be negative ({val})"],
            )
            
        warnings = []
        if val == 0.0:
            warnings.append(f"Field '{field_name}' reported explicitly as 0.0")
            
        return FieldValidationResult(value=val, is_valid=True, warnings=warnings)
    except (ValueError, TypeError):
        return FieldValidationResult(
            value=None,
            is_valid=False,
            errors=[f"Invalid numeric value '{raw_val}' for field '{field_name}'"],
        )
