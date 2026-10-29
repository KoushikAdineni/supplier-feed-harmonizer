"""
Identifier and hashing utilities for supplier-feed-harmonizer.
Provides deterministic ID generation, GTIN validation, and hashing functions.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
import uuid


def generate_run_id() -> str:
    """Generate a run ID in the format: run_YYYYMMDDTHHMMSSZ_<6 hex>."""
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    random_hex = uuid.uuid4().hex[:6]
    return f"run_{now_utc}_{random_hex}"


def normalize_string(val: str | None) -> str:
    """Trim, collapse multiple spaces, and convert to lower case for hashing."""
    if val is None:
        return ""
    # Collapse multiple whitespace characters into a single space
    cleaned = re.sub(r"\s+", " ", str(val)).strip()
    return cleaned.lower()


def validate_gtin13(gtin: str | None) -> bool:
    """
    Validate whether a given string is a valid 13-digit EAN-13/GTIN.
    Requires exactly 13 numeric digits and matching check digit.
    """
    if not gtin:
        return False
    digits = str(gtin).strip()
    if not digits.isdigit() or len(digits) != 13:
        return False

    prefix12 = digits[:12]
    expected_chk = digits[12]

    total = 0
    for idx, char in enumerate(prefix12):
        n = int(char)
        total += n if idx % 2 == 0 else n * 3
    calc_chk = str((10 - (total % 10)) % 10)
    return calc_chk == expected_chk


def generate_product_id(
    gtin: str | None = None,
    supplier_id: str | None = None,
    brand: str | None = None,
    name: str | None = None,
) -> str:
    """
    Generate deterministic product_id:
    'prd_' + first 16 hex of sha256(normalized GTIN) or,
    if no GTIN, sha256(supplier_id|normalized_brand|normalized_name).
    """
    if gtin and validate_gtin13(gtin):
        clean_gtin = str(gtin).strip()
        digest = hashlib.sha256(clean_gtin.encode("utf-8")).hexdigest()[:16]
        return f"prd_{digest}"

    norm_supp = normalize_string(supplier_id)
    norm_brand = normalize_string(brand)
    norm_name = normalize_string(name)
    raw_key = f"{norm_supp}|{norm_brand}|{norm_name}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
    return f"prd_{digest}"


def generate_supplier_product_key(supplier_id: str, supplier_sku: str) -> str:
    """supplier_product_key = sha256(supplier_id|supplier_sku)."""
    raw_key = f"{supplier_id.strip()}|{supplier_sku.strip()}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_record_hash(
    supplier_sku: str,
    name: str,
    category: str,
    price: str,
    weight: str,
    color: str,
    stock_qty: str,
    country: str,
    gtin: str,
) -> str:
    """
    record_hash = sha256 of normalized business fields.
    Used for detecting exact duplicate records across or within runs.
    """
    fields = [
        normalize_string(supplier_sku),
        normalize_string(name),
        normalize_string(category),
        normalize_string(price),
        normalize_string(weight),
        normalize_string(color),
        normalize_string(stock_qty),
        normalize_string(country),
        normalize_string(gtin),
    ]
    raw_payload = "|".join(fields)
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def generate_reject_id(run_id: str, source_file: str, row_number: int) -> str:
    """reject_id = sha256(run_id|source_file|row_number)."""
    raw_key = f"{run_id}|{source_file}|{row_number}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def compute_file_sha256(file_path: str) -> str:
    """Calculate the SHA-256 hash of a file for change detection and idempotent processing."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()
