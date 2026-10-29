"""
Row-level validation module for supplier-feed-harmonizer.
Validates required business fields, numeric constraints, date parsing,
GTIN-13 checksums, and reference table lookups against stable error codes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.harmonizer.config import ReferenceMaps, SupplierConfig
from src.harmonizer.ids import generate_reject_id, validate_gtin13


def parse_numeric(val: Any, decimal_sep: str = ".") -> Optional[float]:
    """Parse string or number into float, handling European comma decimals."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if decimal_sep == ",":
        # Replace dot if used as thousands sep and comma as decimal
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_date_to_utc(val: Any, date_format: str = "iso8601") -> Optional[datetime]:
    """Parse date/time values from ISO-8601, epoch seconds, or dd.mm.yyyy into UTC datetime."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None

    # Epoch timestamp
    if date_format == "epoch_seconds" or s.isdigit():
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except Exception:
            return None

    # German dd.mm.yyyy format
    if date_format == "dd.mm.yyyy" or ("." in s and len(s) == 10):
        try:
            dt = datetime.strptime(s, "%d.%m.%Y")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Standard ISO-8601
    try:
        # Normalize trailing Z
        clean_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    return None


def validate_records(
    records: List[Dict[str, Any]],
    supplier_cfg: SupplierConfig,
    references: ReferenceMaps,
    run_id: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Validates a list of staging records against business rules and reference lookups.
    Returns:
        (valid_records, rejected_records)
    """
    valid: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc).isoformat()

    for rec in records:
        source_file = rec.get("_source_file", "unknown")
        row_num = rec.get("_source_row_number", 0)
        sku = str(rec.get("supplier_sku", "")).strip()
        name = str(rec.get("name_raw", "")).strip()

        # 1. Missing Required Fields
        if not sku or not name:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            missing_f = "supplier_sku" if not sku else "product_name"
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "MISSING_REQUIRED",
                "error_message": f"Required field '{missing_f}' is empty",
                "rejected_at": now_utc,
            })
            continue

        # 2. Numeric Price Parse and Positive Price Check
        price_val = parse_numeric(rec.get("price_raw"), supplier_cfg.decimal_separator)
        if price_val is None:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "BAD_NUMERIC",
                "error_message": f"Non-numeric price value: '{rec.get('price_raw')}'",
                "rejected_at": now_utc,
            })
            continue

        if price_val <= 0:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "NEGATIVE_PRICE",
                "error_message": f"Price must be strictly positive (> 0), got: {price_val}",
                "rejected_at": now_utc,
            })
            continue

        # 3. Numeric Weight Parse and Non-negative Check
        weight_val = parse_numeric(rec.get("weight_raw"), supplier_cfg.decimal_separator)
        if weight_val is None or weight_val < 0:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "BAD_NUMERIC",
                "error_message": f"Weight must be numeric and non-negative, got: '{rec.get('weight_raw')}'",
                "rejected_at": now_utc,
            })
            continue

        # 4. Date Parse
        dt_val = parse_date_to_utc(rec.get("updated_at_raw"), supplier_cfg.date_format)
        if dt_val is None:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "BAD_DATE",
                "error_message": f"Invalid date/time format: '{rec.get('updated_at_raw')}'",
                "rejected_at": now_utc,
            })
            continue

        # 5. GTIN Checksum Check (Only if GTIN is present)
        gtin_raw = str(rec.get("gtin_raw", "")).strip()
        if gtin_raw and not validate_gtin13(gtin_raw):
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "BAD_GTIN",
                "error_message": f"Invalid GTIN-13 checksum or format: '{gtin_raw}'",
                "rejected_at": now_utc,
            })
            continue

        # 6. Reference Map Checks
        # Category lookup
        cat_key = str(rec.get("category_code_raw", "")).strip().lower()
        if cat_key not in references.category_map:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "REF_KEY_INVALID",
                "error_message": f"Category code '{rec.get('category_code_raw')}' not found in category_map",
                "rejected_at": now_utc,
            })
            continue

        # Unit lookup
        unit_key = str(rec.get("weight_unit_raw", "")).strip().lower()
        if unit_key not in references.unit_map:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "REF_KEY_INVALID",
                "error_message": f"Weight unit '{rec.get('weight_unit_raw')}' not found in unit_map",
                "rejected_at": now_utc,
            })
            continue

        # Color lookup
        color_key = str(rec.get("color_code_raw", "")).strip().lower()
        if color_key not in references.color_map:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "REF_KEY_INVALID",
                "error_message": f"Color code '{rec.get('color_code_raw')}' not found in color_map",
                "rejected_at": now_utc,
            })
            continue

        # Currency lookup
        curr_key = str(rec.get("currency_raw", "")).strip().upper()
        if curr_key not in references.currency_map:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "REF_KEY_INVALID",
                "error_message": f"Currency code '{rec.get('currency_raw')}' not found in currency_map",
                "rejected_at": now_utc,
            })
            continue

        # Country lookup
        country_key = str(rec.get("country_raw", "")).strip().lower()
        if country_key not in references.country_map:
            rej_id = generate_reject_id(run_id, source_file, row_num)
            rejected.append({
                "reject_id": rej_id,
                "run_id": run_id,
                "supplier_id": supplier_cfg.supplier_id,
                "source_file": source_file,
                "source_row_number": row_num,
                "raw_record": json.dumps(rec),
                "error_code": "REF_KEY_INVALID",
                "error_message": f"Country code/name '{rec.get('country_raw')}' not found in country_map",
                "rejected_at": now_utc,
            })
            continue

        # Stock quantity parsing (non-negative integer, default 0 if invalid or empty)
        stock_str = str(rec.get("stock_qty_raw", "0")).strip()
        stock_val = 0
        if stock_str.isdigit():
            stock_val = int(stock_str)
        elif stock_str.lower() in ("true", "yes", "in_stock"):
            stock_val = 1
        elif stock_str.lower() in ("false", "no", "out_of_stock"):
            stock_val = 0

        # Store parsed typed representations in rec
        rec["_parsed_price"] = price_val
        rec["_parsed_weight"] = weight_val
        rec["_parsed_date"] = dt_val
        rec["_parsed_stock"] = stock_val
        rec["_clean_gtin"] = gtin_raw

        valid.append(rec)

    return valid, rejected
