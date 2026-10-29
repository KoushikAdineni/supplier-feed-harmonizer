"""Unit tests for schema contracts, row validations, and error codes."""

from pathlib import Path
import pytest

from src.harmonizer.config import ReferenceMaps, SupplierConfig, load_reference_maps
from src.harmonizer.ingest import ingest_supplier_file
from src.harmonizer.schema_check import check_file_schema
from src.harmonizer.validate import parse_date_to_utc, parse_numeric, validate_records


@pytest.fixture
def supplier_a_config():
    return SupplierConfig(
        supplier_id="SUP-A",
        supplier_name="Supplier Alpha",
        priority_rank=1,
        trust_weight=0.95,
        file_pattern="*supplier_a*.csv",
        format="csv",
        delimiter=",",
        encoding="utf-8",
        required_columns=["sku", "product_name", "cat_code", "price", "weight_lb", "color_code", "updated_at", "stock_qty", "country"],
        optional_columns=["gtin"],
        column_mapping={
            "sku": "supplier_sku",
            "product_name": "name_raw",
            "cat_code": "category_code_raw",
            "price": "price_raw",
            "weight_lb": "weight_raw",
            "color_code": "color_code_raw",
            "updated_at": "updated_at_raw",
            "stock_qty": "stock_qty_raw",
            "country": "country_raw",
            "gtin": "gtin_raw",
        },
        default_currency="USD",
        default_weight_unit="lb",
        date_format="iso8601",
    )


@pytest.fixture
def references():
    return load_reference_maps("config/mappings")


def test_schema_check_empty_file(tmp_path, supplier_a_config):
    empty_f = tmp_path / "empty.csv"
    empty_f.write_bytes(b"")
    res = check_file_schema(empty_f, supplier_a_config)
    assert res.is_valid is True
    assert res.status == "success_empty"


def test_schema_check_header_only(tmp_path, supplier_a_config):
    hdr_f = tmp_path / "header_only.csv"
    hdr_f.write_text(",".join(supplier_a_config.required_columns) + "\n", encoding="utf-8")
    res = check_file_schema(hdr_f, supplier_a_config)
    assert res.is_valid is True
    assert res.status == "success_empty"


def test_schema_check_missing_or_renamed_column(tmp_path, supplier_a_config):
    # 'sku' renamed to 'product_code'
    cols = ["product_code", "product_name", "cat_code", "price", "weight_lb", "color_code", "updated_at", "stock_qty", "country"]
    bad_f = tmp_path / "renamed_col.csv"
    bad_f.write_text(",".join(cols) + "\n101,Widget,EL-01,9.99,1.0,BLK,2026-01-01,5,US\n", encoding="utf-8")
    res = check_file_schema(bad_f, supplier_a_config)
    assert res.is_valid is False
    assert res.status == "failed_schema"
    assert "sku" in res.missing_columns


def test_schema_check_extra_column_allowed(tmp_path, supplier_a_config):
    cols = supplier_a_config.required_columns + ["marketing_campaign"]
    extra_f = tmp_path / "extra_col.csv"
    extra_f.write_text(",".join(cols) + "\nSKU1,Widget,EL-01,9.99,1.0,BLK,2026-01-01T00:00:00Z,5,US,SummerPromo\n", encoding="utf-8")
    res = check_file_schema(extra_f, supplier_a_config)
    assert res.is_valid is True
    assert res.status == "valid"
    assert "marketing_campaign" in res.extra_columns


def test_ingest_malformed_csv_row_count(tmp_path, supplier_a_config):
    csv_f = tmp_path / "malformed.csv"
    # Header has 9 columns, line 2 has 3 columns
    csv_f.write_text("sku,product_name,cat_code,price,weight_lb,color_code,updated_at,stock_qty,country\nSKU1,OnlyThreeCols,EL-01\n", encoding="utf-8")
    staging, rejects = ingest_supplier_file(csv_f, supplier_a_config, "run_test")
    assert len(staging) == 0
    assert len(rejects) == 1
    assert rejects[0]["error_code"] == "MALFORMED_RECORD"
    assert rejects[0]["source_row_number"] == 2


def test_ingest_malformed_json_lines(tmp_path):
    supplier_b_config = SupplierConfig(
        supplier_id="SUP-B",
        supplier_name="Supplier Beta",
        priority_rank=2,
        trust_weight=0.85,
        file_pattern="*.jsonl",
        format="jsonl",
        required_columns=["item_id", "title"],
        column_mapping={"item_id": "supplier_sku", "title": "name_raw"},
    )
    jsonl_f = tmp_path / "corrupt.jsonl"
    jsonl_f.write_text('{"item_id": "ITEM1", "title": "Valid"}\n{broken_json_syntax\n', encoding="utf-8")
    staging, rejects = ingest_supplier_file(jsonl_f, supplier_b_config, "run_test")
    assert len(staging) == 1
    assert len(rejects) == 1
    assert rejects[0]["error_code"] == "MALFORMED_RECORD"
    assert rejects[0]["source_row_number"] == 2


def test_validate_missing_required_fields(supplier_a_config, references):
    records = [
        {"_source_file": "f.csv", "_source_row_number": 2, "supplier_sku": "", "name_raw": "Widget", "price_raw": "10.0"},
        {"_source_file": "f.csv", "_source_row_number": 3, "supplier_sku": "SKU-1", "name_raw": "", "price_raw": "10.0"},
    ]
    valid, rejected = validate_records(records, supplier_a_config, references, "run_test")
    assert len(valid) == 0
    assert len(rejected) == 2
    assert all(r["error_code"] == "MISSING_REQUIRED" for r in rejected)


def test_validate_negative_and_zero_price(supplier_a_config, references):
    records = [
        {"_source_file": "f.csv", "_source_row_number": 2, "supplier_sku": "S1", "name_raw": "W1", "price_raw": "-5.00"},
        {"_source_file": "f.csv", "_source_row_number": 3, "supplier_sku": "S2", "name_raw": "W2", "price_raw": "0.00"},
    ]
    valid, rejected = validate_records(records, supplier_a_config, references, "run_test")
    assert len(valid) == 0
    assert len(rejected) == 2
    assert rejected[0]["error_code"] == "NEGATIVE_PRICE"
    assert rejected[1]["error_code"] == "NEGATIVE_PRICE"


def test_validate_weight_zero_is_valid(supplier_a_config, references):
    # Weight 0 is valid for boundary tests (e.g. digital license or lightweight item)
    records = [{
        "_source_file": "f.csv", "_source_row_number": 2, "supplier_sku": "S1", "name_raw": "Digital Key",
        "price_raw": "19.99", "weight_raw": "0.00", "weight_unit_raw": "lb",
        "category_code_raw": "EL-01", "color_code_raw": "BLK", "country_raw": "US", "currency_raw": "USD",
        "updated_at_raw": "2026-01-01T00:00:00Z", "gtin_raw": "4006381333931"
    }]
    valid, rejected = validate_records(records, supplier_a_config, references, "run_test")
    assert len(valid) == 1
    assert len(rejected) == 0
    assert valid[0]["_parsed_weight"] == 0.0


def test_validate_bad_gtin(supplier_a_config, references):
    records = [{
        "_source_file": "f.csv", "_source_row_number": 2, "supplier_sku": "S1", "name_raw": "Bad GTIN Item",
        "price_raw": "19.99", "weight_raw": "1.0", "weight_unit_raw": "lb",
        "category_code_raw": "EL-01", "color_code_raw": "BLK", "country_raw": "US", "currency_raw": "USD",
        "updated_at_raw": "2026-01-01T00:00:00Z", "gtin_raw": "4006381333930"  # invalid checksum
    }]
    valid, rejected = validate_records(records, supplier_a_config, references, "run_test")
    assert len(valid) == 0
    assert len(rejected) == 1
    assert rejected[0]["error_code"] == "BAD_GTIN"


def test_validate_bad_date(supplier_a_config, references):
    records = [{
        "_source_file": "f.csv", "_source_row_number": 2, "supplier_sku": "S1", "name_raw": "Bad Date Item",
        "price_raw": "19.99", "weight_raw": "1.0", "weight_unit_raw": "lb",
        "category_code_raw": "EL-01", "color_code_raw": "BLK", "country_raw": "US", "currency_raw": "USD",
        "updated_at_raw": "invalid-date-32-13-2026", "gtin_raw": "4006381333931"
    }]
    valid, rejected = validate_records(records, supplier_a_config, references, "run_test")
    assert len(valid) == 0
    assert len(rejected) == 1
    assert rejected[0]["error_code"] == "BAD_DATE"


def test_validate_ref_key_invalid(supplier_a_config, references):
    # Invalid category
    records = [{
        "_source_file": "f.csv", "_source_row_number": 2, "supplier_sku": "S1", "name_raw": "Unknown Cat Item",
        "price_raw": "19.99", "weight_raw": "1.0", "weight_unit_raw": "lb",
        "category_code_raw": "NONEXISTENT_CATEGORY_999", "color_code_raw": "BLK", "country_raw": "US", "currency_raw": "USD",
        "updated_at_raw": "2026-01-01T00:00:00Z", "gtin_raw": "4006381333931"
    }]
    valid, rejected = validate_records(records, supplier_a_config, references, "run_test")
    assert len(valid) == 0
    assert len(rejected) == 1
    assert rejected[0]["error_code"] == "REF_KEY_INVALID"
