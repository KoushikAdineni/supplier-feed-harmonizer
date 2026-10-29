"""Unit tests for entity resolution, conflict rules (a-d), lineage, and conflict logging."""

import json
import pytest

from src.harmonizer.config import SupplierConfig
from src.harmonizer.resolve import resolve_entities


@pytest.fixture
def supplier_configs():
    return {
        "SUP-A": SupplierConfig(supplier_id="SUP-A", supplier_name="Alpha", priority_rank=1, trust_weight=0.95, file_pattern="*", format="csv"),
        "SUP-B": SupplierConfig(supplier_id="SUP-B", supplier_name="Beta", priority_rank=2, trust_weight=0.85, file_pattern="*", format="jsonl"),
        "SUP-C": SupplierConfig(supplier_id="SUP-C", supplier_name="Gamma", priority_rank=3, trust_weight=0.75, file_pattern="*", format="csv"),
    }



def test_conflict_rule_a_latest_timestamp_wins_price_and_stock(supplier_configs):
    # SUP-B has newer timestamp than SUP-A, so SUP-B price and stock should win even though SUP-A has higher priority
    versions = [
        {
            "supplier_id": "SUP-A",
            "supplier_sku": "SKU-A",
            "gtin": "4006381333931",
            "name_std": "Headphones Alpha",
            "category_id": "CAT_AUDIO",
            "price_usd": 100.00,
            "weight_kg": 0.5,
            "color_id": "CLR_BLACK",
            "country_code": "US",
            "stock_qty": 50,
            "source_updated_at": "2026-01-01T10:00:00+00:00",
            "run_id": "run_1",
            "source_file": "sup_a.csv",
            "source_row_number": 10,
            "record_hash": "hash_a",
        },
        {
            "supplier_id": "SUP-B",
            "supplier_sku": "ITEM-B",
            "gtin": "4006381333931",
            "name_std": "Headphones Beta",
            "category_id": "CAT_AUDIO",
            "price_usd": 120.00,  # Newer price
            "weight_kg": 0.5,
            "color_id": "CLR_BLACK",
            "country_code": "US",
            "stock_qty": 90,      # Newer stock
            "source_updated_at": "2026-01-02T10:00:00+00:00",  # 1 day newer
            "run_id": "run_1",
            "source_file": "sup_b.jsonl",
            "source_row_number": 20,
            "record_hash": "hash_b",
        },
    ]

    golden, lineage, conflicts = resolve_entities(versions, supplier_configs, "run_1")
    assert len(golden) == 1
    g = golden[0]
    # Rule (a): Latest timestamp wins
    assert g["price_usd"] == 120.00
    assert g["total_stock"] == 90

    # Lineage verifies chosen supplier is SUP-B
    price_lin = next(l for l in lineage if l["attribute_name"] == "price_usd")
    assert price_lin["chosen_supplier_id"] == "SUP-B"
    assert price_lin["rule_applied"] == "latest_source_updated_at"


def test_conflict_rule_b_priority_wins_for_name_category_color_country(supplier_configs):
    # SUP-A has priority_rank 1, SUP-B has priority_rank 2
    # Even if SUP-B is newer, SUP-A wins for name, category, color, country
    versions = [
        {
            "supplier_id": "SUP-A",
            "supplier_sku": "SKU-A",
            "gtin": "4006381333931",
            "name_std": "Official Alpha Name",
            "category_id": "CAT_AUDIO",
            "price_usd": 100.00,
            "weight_kg": 0.5,
            "color_id": "CLR_BLACK",
            "country_code": "US",
            "stock_qty": 50,
            "source_updated_at": "2026-01-01T10:00:00+00:00",
            "run_id": "run_1",
            "source_file": "sup_a.csv",
            "source_row_number": 10,
            "record_hash": "hash_a",
        },
        {
            "supplier_id": "SUP-B",
            "supplier_sku": "ITEM-B",
            "gtin": "4006381333931",
            "name_std": "Alternative Beta Name",
            "category_id": "CAT_ELECTRONICS",
            "price_usd": 100.00,
            "weight_kg": 0.5,
            "color_id": "CLR_WHITE",
            "country_code": "DE",
            "stock_qty": 50,
            "source_updated_at": "2026-01-02T10:00:00+00:00",
            "run_id": "run_1",
            "source_file": "sup_b.jsonl",
            "source_row_number": 20,
            "record_hash": "hash_b",
        },
    ]

    golden, lineage, conflicts = resolve_entities(versions, supplier_configs, "run_1")
    g = golden[0]
    # Rule (b): Priority rank wins
    assert g["name_std"] == "Official Alpha Name"
    assert g["category_id"] == "CAT_AUDIO"
    assert g["color_id"] == "CLR_BLACK"
    assert g["country_code"] == "US"


def test_conflict_rule_c_majority_weight_and_tie_breaking(supplier_configs):
    # Case 1: Clear majority (2 suppliers agree on 0.75 kg, 1 supplier has 0.50 kg)
    v1 = [
        {"supplier_id": "SUP-A", "gtin": "4006381333931", "name_std": "N", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.50, "color_id": "CLR", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f1", "source_row_number": 1, "record_hash": "h1"},
        {"supplier_id": "SUP-B", "gtin": "4006381333931", "name_std": "N", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.75, "color_id": "CLR", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f2", "source_row_number": 1, "record_hash": "h2"},
        {"supplier_id": "SUP-C", "gtin": "4006381333931", "name_std": "N", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.75, "color_id": "CLR", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f3", "source_row_number": 1, "record_hash": "h3"},
    ]
    golden1, _, _ = resolve_entities(v1, supplier_configs, "r")
    assert golden1[0]["weight_kg"] == 0.75  # Majority wins

    # Case 2: Tie (3 different weights: 0.50, 0.75, 1.00) -> broken by priority (SUP-A rank 1 wins)
    v2 = [
        {"supplier_id": "SUP-A", "gtin": "4006381333931", "name_std": "N", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.50, "color_id": "CLR", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f1", "source_row_number": 1, "record_hash": "h1"},
        {"supplier_id": "SUP-B", "gtin": "4006381333931", "name_std": "N", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.75, "color_id": "CLR", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f2", "source_row_number": 1, "record_hash": "h2"},
        {"supplier_id": "SUP-C", "gtin": "4006381333931", "name_std": "N", "category_id": "C", "price_usd": 10.0, "weight_kg": 1.00, "color_id": "CLR", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f3", "source_row_number": 1, "record_hash": "h3"},
    ]
    golden2, _, _ = resolve_entities(v2, supplier_configs, "r")
    assert golden2[0]["weight_kg"] == 0.50  # Priority tie break


def test_conflict_rule_d_null_never_overrides_non_null(supplier_configs):
    # SUP-A has null/empty color, SUP-B has non-null color
    # Even though SUP-A has priority 1, non-null from SUP-B must win
    versions = [
        {"supplier_id": "SUP-A", "gtin": "4006381333931", "name_std": "Widget", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.5, "color_id": "", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f1", "source_row_number": 1, "record_hash": "h1"},
        {"supplier_id": "SUP-B", "gtin": "4006381333931", "name_std": "Widget", "category_id": "C", "price_usd": 10.0, "weight_kg": 0.5, "color_id": "CLR_BLUE", "country_code": "US", "stock_qty": 1, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "r", "source_file": "f2", "source_row_number": 1, "record_hash": "h2"},
    ]
    golden, _, _ = resolve_entities(versions, supplier_configs, "r")
    assert golden[0]["color_id"] == "CLR_BLUE"


def test_complete_attribute_lineage_recorded(supplier_configs):
    versions = [
        {"supplier_id": "SUP-A", "gtin": "4006381333931", "name_std": "Item", "category_id": "CAT_AUDIO", "price_usd": 10.0, "weight_kg": 1.0, "color_id": "CLR_RED", "country_code": "US", "stock_qty": 5, "source_updated_at": "2026-01-01T00:00:00Z", "run_id": "run_test", "source_file": "file1.csv", "source_row_number": 42, "record_hash": "h1"}
    ]
    golden, lineage, _ = resolve_entities(versions, supplier_configs, "run_test")
    # All 7 business attributes must have lineage records
    expected_attrs = {"name_std", "category_id", "price_usd", "weight_kg", "color_id", "country_code", "total_stock"}
    actual_attrs = {l["attribute_name"] for l in lineage}
    assert expected_attrs == actual_attrs
    for l in lineage:
        assert l["chosen_source_file"] == "file1.csv"
        assert l["chosen_source_row_number"] == 42
        assert l["chosen_supplier_id"] == "SUP-A"
