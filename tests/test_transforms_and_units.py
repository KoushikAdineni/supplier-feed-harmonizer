"""Unit tests for transformations, unit conversions, decimal comma parsing, and deduplication."""

from datetime import datetime, timezone
import pytest

from src.harmonizer.config import ReferenceMaps, SupplierConfig, load_reference_maps
from src.harmonizer.transform import deduplicate_records, transform_and_standardize
from src.harmonizer.validate import parse_numeric


@pytest.fixture
def references():
    return load_reference_maps("config/mappings")


@pytest.fixture
def supplier_a_config():
    return SupplierConfig(
        supplier_id="SUP-A",
        supplier_name="Supplier Alpha",
        priority_rank=1,
        trust_weight=0.95,
        file_pattern="*supplier_a*.csv",
        format="csv",
        default_currency="USD",
        default_weight_unit="lb",
    )


@pytest.fixture
def supplier_c_config():
    return SupplierConfig(
        supplier_id="SUP-C",
        supplier_name="Supplier Gamma",
        priority_rank=3,
        trust_weight=0.75,
        file_pattern="*supplier_c*.csv",
        format="csv",
        delimiter=";",
        decimal_separator=",",
        encoding="iso-8859-1",
        default_currency="EUR",
        default_weight_unit="kg",
    )


def test_decimal_comma_numeric_parsing():
    assert parse_numeric("12,50", decimal_sep=",") == 12.50
    assert parse_numeric("1.250,99", decimal_sep=",") == 1250.99
    assert parse_numeric("19.99", decimal_sep=".") == 19.99
    assert parse_numeric("0,00", decimal_sep=",") == 0.00
    assert parse_numeric("invalid", decimal_sep=",") is None


def test_unit_conversion_lb_to_kg(supplier_a_config, references):
    records = [{
        "supplier_sku": "SKU-LB",
        "name_raw": "Weight Test Item",
        "category_code_raw": "EL-01",
        "price_raw": "100.00",
        "weight_raw": "10.0",
        "color_code_raw": "BLK",
        "stock_qty_raw": "5",
        "country_raw": "US",
        "gtin_raw": "4006381333931",
        "_parsed_price": 100.00,
        "_parsed_weight": 10.0,
        "_parsed_date": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "_parsed_stock": 5,
        "_clean_gtin": "4006381333931",
        "_source_file": "file_a.csv",
        "_source_row_number": 2,
        "currency_raw": "USD",
        "weight_unit_raw": "lb",
    }]
    deduped, _ = deduplicate_records(records, supplier_a_config)
    transformed = transform_and_standardize(deduped, supplier_a_config, references, "run_test")
    assert len(transformed) == 1
    # 10 lb * 0.45359237 = 4.5359 kg
    assert transformed[0]["weight_kg"] == 4.5359
    assert transformed[0]["price_usd"] == 100.00


def test_unit_conversion_edge_weight_zero(supplier_a_config, references):
    records = [{
        "supplier_sku": "SKU-ZERO",
        "name_raw": "Zero Weight Item",
        "category_code_raw": "EL-01",
        "price_raw": "50.00",
        "weight_raw": "0.0",
        "color_code_raw": "BLK",
        "stock_qty_raw": "1",
        "country_raw": "US",
        "gtin_raw": "4006381333931",
        "_parsed_price": 50.00,
        "_parsed_weight": 0.0,
        "_parsed_date": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "_parsed_stock": 1,
        "_clean_gtin": "4006381333931",
        "_source_file": "file_a.csv",
        "_source_row_number": 2,
        "currency_raw": "USD",
        "weight_unit_raw": "lb",
    }]
    deduped, _ = deduplicate_records(records, supplier_a_config)
    transformed = transform_and_standardize(deduped, supplier_a_config, references, "run_test")
    assert transformed[0]["weight_kg"] == 0.0


def test_currency_conversion_eur_to_usd(supplier_c_config, references):
    # 100 EUR * 1.08 = 108.00 USD
    records = [{
        "supplier_sku": "ART-EUR",
        "name_raw": "Kopfhörer Weiß",
        "category_code_raw": "103",
        "price_raw": "100,00",
        "weight_raw": "1,5",
        "color_code_raw": "Weiß",
        "stock_qty_raw": "10",
        "country_raw": "Deutschland",
        "gtin_raw": "4006381333931",
        "_parsed_price": 100.00,
        "_parsed_weight": 1.5,
        "_parsed_date": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "_parsed_stock": 10,
        "_clean_gtin": "4006381333931",
        "_source_file": "file_c.csv",
        "_source_row_number": 2,
        "currency_raw": "EUR",
        "weight_unit_raw": "kg",
    }]
    deduped, _ = deduplicate_records(records, supplier_c_config)
    transformed = transform_and_standardize(deduped, supplier_c_config, references, "run_test")
    assert transformed[0]["price_usd"] == 108.00
    assert transformed[0]["color_id"] == "CLR_WHITE"
    assert transformed[0]["country_code"] == "DE"
    assert transformed[0]["category_id"] == "CAT_AUDIO"


def test_deduplication_exact_vs_versions(supplier_a_config):
    records = [
        # First row
        {
            "supplier_sku": "SKU-DUP", "name_raw": "Widget", "category_code_raw": "EL-01",
            "price_raw": "10.00", "weight_raw": "1.0", "color_code_raw": "BLK",
            "stock_qty_raw": "5", "country_raw": "US", "gtin_raw": "4006381333931",
            "_clean_gtin": "4006381333931", "_source_file": "f.csv", "_source_row_number": 2,
        },
        # Exact duplicate row (same fields)
        {
            "supplier_sku": "SKU-DUP", "name_raw": "Widget", "category_code_raw": "EL-01",
            "price_raw": "10.00", "weight_raw": "1.0", "color_code_raw": "BLK",
            "stock_qty_raw": "5", "country_raw": "US", "gtin_raw": "4006381333931",
            "_clean_gtin": "4006381333931", "_source_file": "f.csv", "_source_row_number": 3,
        },
        # Same SKU but updated price (separate version)
        {
            "supplier_sku": "SKU-DUP", "name_raw": "Widget", "category_code_raw": "EL-01",
            "price_raw": "15.00", "weight_raw": "1.0", "color_code_raw": "BLK",
            "stock_qty_raw": "5", "country_raw": "US", "gtin_raw": "4006381333931",
            "_clean_gtin": "4006381333931", "_source_file": "f.csv", "_source_row_number": 4,
        },
    ]
    deduped, dup_count = deduplicate_records(records, supplier_a_config)
    assert dup_count == 1
    assert len(deduped) == 2
