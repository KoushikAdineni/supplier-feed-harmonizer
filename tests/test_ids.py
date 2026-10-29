"""Tests for deterministic IDs, GTIN validation, and hashing functions."""

import pytest
from src.harmonizer.ids import (
    compute_file_sha256,
    generate_product_id,
    generate_record_hash,
    generate_reject_id,
    generate_run_id,
    generate_supplier_product_key,
    normalize_string,
    validate_gtin13,
)


def test_gtin13_validation():
    # Valid EAN-13 barcodes
    assert validate_gtin13("4006381333931") is True
    assert validate_gtin13("9780201379624") is True
    assert validate_gtin13("  4006381333931  ") is True  # with whitespace

    # Invalid EAN-13 barcodes
    assert validate_gtin13("4006381333930") is False  # wrong check digit
    assert validate_gtin13("12345") is False  # too short
    assert validate_gtin13("40063813339311") is False  # too long
    assert validate_gtin13("400638133393A") is False  # non-numeric
    assert validate_gtin13(None) is False
    assert validate_gtin13("") is False


def test_deterministic_product_id():
    gtin = "4006381333931"
    pid1 = generate_product_id(gtin=gtin)
    pid2 = generate_product_id(gtin=gtin)
    assert pid1 == pid2
    assert pid1.startswith("prd_")
    assert len(pid1) == 20  # "prd_" (4) + 16 hex = 20

    # Fallback without GTIN
    fallback_pid1 = generate_product_id(gtin=None, supplier_id="SUP-A", brand="Acme", name="Widget Pro")
    fallback_pid2 = generate_product_id(gtin=None, supplier_id="SUP-A", brand="Acme", name="Widget Pro")
    assert fallback_pid1 == fallback_pid2
    assert fallback_pid1.startswith("prd_")

    # Name normalization ensures space/case insensitivity for ID generation
    fallback_pid3 = generate_product_id(gtin=None, supplier_id="SUP-A", brand="ACME", name="Widget  Pro  ")
    assert fallback_pid1 == fallback_pid3


def test_deterministic_supplier_product_key():
    k1 = generate_supplier_product_key("SUP-A", "SKU-1001")
    k2 = generate_supplier_product_key("SUP-A", "SKU-1001")
    assert k1 == k2
    assert len(k1) == 64  # sha256


def test_deterministic_record_hash():
    h1 = generate_record_hash("SKU-1", "Name", "CAT1", "10.00", "1.0", "BLK", "10", "US", "1234567890128")
    h2 = generate_record_hash("SKU-1", "Name", "CAT1", "10.00", "1.0", "BLK", "10", "US", "1234567890128")
    assert h1 == h2

    # Different attribute produces different hash
    h3 = generate_record_hash("SKU-1", "Name", "CAT1", "15.00", "1.0", "BLK", "10", "US", "1234567890128")
    assert h1 != h3


def test_reject_id_traceability():
    r1 = generate_reject_id("run_1", "file.csv", 42)
    r2 = generate_reject_id("run_1", "file.csv", 42)
    r3 = generate_reject_id("run_1", "file.csv", 43)
    assert r1 == r2
    assert r1 != r3


def test_run_id_format():
    rid = generate_run_id()
    assert rid.startswith("run_")
    parts = rid.split("_")
    assert len(parts) == 3
    assert len(parts[2]) == 6  # 6 hex chars
