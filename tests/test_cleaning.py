"""Tests for data cleaning, normalization, and validation rules."""
from app.ingestion.validators import (
    validate_commodity_code,
    validate_flow_type,
    validate_country,
    validate_period,
    validate_numeric_field,
    resolve_mineral_metadata,
)
from app.ingestion.cleaning import (
    clean_comtrade_record,
    clean_ofac_record,
    compute_trade_record_hash,
)


def test_commodity_code_normalization():
    # HS code with dot notation
    res = validate_commodity_code("2836.91")
    assert res.is_valid is True
    assert res.value == "283691"

    # HS code with spaces and dashes
    res2 = validate_commodity_code(" 2825-20 ")
    assert res2.is_valid is True
    assert res2.value == "282520"

    # 4-digit heading (should be valid but issue warning)
    res3 = validate_commodity_code("2836")
    assert res3.is_valid is True
    assert res3.value == "2836"
    assert len(res3.warnings) > 0

    # Invalid empty or single character
    res4 = validate_commodity_code("")
    assert res4.is_valid is False

    res5 = validate_commodity_code("1")
    assert res5.is_valid is False


def test_resolve_mineral_metadata():
    desc, mtype = resolve_mineral_metadata("283691")
    assert "Lithium Carbonate" in desc
    assert mtype == "Lithium"

    desc2, mtype2 = resolve_mineral_metadata("850760")
    assert "Accumulators" in desc2 or "Batteries" in desc2
    assert mtype2 == "Lithium"


def test_flow_type_validation():
    # Comtrade flow numeric codes
    assert validate_flow_type("1").value == "IMPORT"
    assert validate_flow_type("2").value == "EXPORT"
    
    # Comtrade letter codes
    assert validate_flow_type("M").value == "IMPORT"
    assert validate_flow_type("X").value == "EXPORT"

    # Text
    assert validate_flow_type("Imports").value == "IMPORT"
    assert validate_flow_type("Exports").value == "EXPORT"

    # Invalid
    res = validate_flow_type("INVALID_FLOW")
    assert res.is_valid is False


def test_country_normalization():
    # UN code 842 -> USA
    res = validate_country("842", "United States")
    assert res.is_valid is True
    assert res.value[0] == "USA"

    # ISO3
    res2 = validate_country("CHL")
    assert res2.is_valid is True
    assert res2.value[0] == "CHL"

    # Missing
    res3 = validate_country(None)
    assert res3.is_valid is False


def test_period_validation():
    # Annual
    res = validate_period("2023")
    assert res.is_valid is True
    assert res.value == ("2023", 2023, None)

    # Monthly
    res2 = validate_period("2023-06")
    assert res2.is_valid is True
    assert res2.value == ("2023-06", 2023, 6)

    # Out of range year
    res3 = validate_period("1850")
    assert res3.is_valid is False

    # Invalid string
    res4 = validate_period("not_a_date")
    assert res4.is_valid is False


def test_numeric_field_missing_value_preservation():
    """
    CRITICAL REQUIREMENT:
    Never silently convert missing values into zero. Missing values must stay None.
    """
    res_none = validate_numeric_field(None, "trade_value")
    assert res_none.is_valid is True
    assert res_none.value is None  # Must NOT be 0.0

    res_empty = validate_numeric_field("", "trade_value")
    assert res_empty.is_valid is True
    assert res_empty.value is None

    res_nan = validate_numeric_field("NaN", "trade_value")
    assert res_nan.is_valid is True
    assert res_nan.value is None

    # Valid values
    res_val = validate_numeric_field("1,250,500.50", "trade_value")
    assert res_val.is_valid is True
    assert res_val.value == 1250500.50

    # Negative value should be flagged as error
    res_neg = validate_numeric_field("-500.0", "trade_value")
    assert res_neg.is_valid is False


def test_clean_comtrade_record_valid_and_missing_handling():
    raw = {
        "id": "UN-101",
        "cmdCode": "283691",
        "flowCode": "1",
        "reporterCode": "842",
        "partnerCode": "152",
        "period": "2023",
        "primaryValue": None,  # Missing trade value
        "netWgt": 50000.0,
    }
    cleaned, issues = clean_comtrade_record(raw)
    assert cleaned is not None
    assert cleaned["commodity_code"] == "283691"
    assert cleaned["reporter_country_code"] == "USA"
    assert cleaned["partner_country_code"] == "CHL"
    assert cleaned["flow_type"] == "IMPORT"
    assert cleaned["period_year"] == 2023
    # Ensure None was preserved and not converted to 0
    assert cleaned["trade_value_usd"] is None
    assert cleaned["net_weight_kg"] == 50000.0
    assert cleaned["record_hash"] is not None


def test_clean_ofac_record():
    raw_ofac = {
        "Ent_num": "9999",
        "SDN_Name": "GLOBAL METALS EXTRACTION CO",
        "SDN_Type": "entity",
        "Program": "RUSSIA-EO14024",
        "Remarks": "Tax ID 123456789; Moscow",
    }
    cleaned, issues = clean_ofac_record(raw_ofac)
    assert cleaned is not None
    assert cleaned["source_record_id"] == "9999"
    assert cleaned["primary_name"] == "GLOBAL METALS EXTRACTION CO"
    assert cleaned["programs"] == "RUSSIA-EO14024"

    # Missing Ent_num should be rejected
    invalid_ofac = {"Ent_num": "-0-", "SDN_Name": "ANONYMOUS"}
    cleaned_inv, issues_inv = clean_ofac_record(invalid_ofac)
    assert cleaned_inv is None
    assert any(i["issue_type"] == "MISSING_OFAC_ID" for i in issues_inv)
