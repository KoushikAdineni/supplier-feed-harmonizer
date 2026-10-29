"""
Deduplication and transformation module for supplier-feed-harmonizer.
Eliminates exact record duplicates within runs, converts currencies to USD,
standardizes weights to kg, resolves reference taxonomy keys, and formats ISO-8601 UTC timestamps.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.harmonizer.config import ReferenceMaps, SupplierConfig
from src.harmonizer.ids import generate_record_hash, generate_supplier_product_key


def normalize_product_name(raw_name: str) -> str:
    """Standardize name: trim, collapse whitespace, preserve readable title casing."""
    if not raw_name:
        return ""
    # Collapse multiple whitespace characters
    collapsed = re.sub(r"\s+", " ", str(raw_name)).strip()
    return collapsed


def deduplicate_records(
    valid_records: List[Dict[str, Any]],
    supplier_cfg: SupplierConfig,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Drops exact duplicate rows within the same run (matching supplier_product_key and record_hash).
    Rows with same SKU but different timestamps or attribute values are preserved.
    Returns:
        (deduplicated_records, duplicate_count)
    """
    seen_hashes: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    duplicate_count = 0

    for rec in valid_records:
        sku = str(rec["supplier_sku"]).strip()
        supp_prod_key = generate_supplier_product_key(supplier_cfg.supplier_id, sku)
        rec["supplier_product_key"] = supp_prod_key

        rec_hash = generate_record_hash(
            supplier_sku=sku,
            name=str(rec.get("name_raw", "")),
            category=str(rec.get("category_code_raw", "")),
            price=str(rec.get("price_raw", "")),
            weight=str(rec.get("weight_raw", "")),
            color=str(rec.get("color_code_raw", "")),
            stock_qty=str(rec.get("stock_qty_raw", "")),
            country=str(rec.get("country_raw", "")),
            gtin=str(rec.get("_clean_gtin", "")),
        )
        rec["record_hash"] = rec_hash

        dedup_key = f"{supp_prod_key}|{rec_hash}"
        if dedup_key in seen_hashes:
            duplicate_count += 1
            if logger:
                logger.info(
                    f"Dropped duplicate record for SKU='{sku}' in file '{rec.get('_source_file')}', row {rec.get('_source_row_number')}"
                )
            continue

        seen_hashes.add(dedup_key)
        deduped.append(rec)

    return deduped, duplicate_count


def transform_and_standardize(
    records: List[Dict[str, Any]],
    supplier_cfg: SupplierConfig,
    references: ReferenceMaps,
    run_id: str,
) -> List[Dict[str, Any]]:
    """
    Transforms validated supplier staging records into standardized version records:
    - Currency -> USD via static conversion
    - Weight -> kg
    - Category -> standardized category_id
    - Color -> standardized color_id
    - Country -> ISO-2 country_code
    - Date -> ISO-8601 UTC string
    - Name -> normalized title string
    """
    standardized: List[Dict[str, Any]] = []

    for rec in records:
        # 1. Normalize Name
        name_std = normalize_product_name(rec.get("name_raw", ""))

        # 2. Currency to USD
        raw_curr = str(rec.get("currency_raw", supplier_cfg.default_currency)).strip().upper()
        rate = references.currency_map.get(raw_curr, 1.0)
        parsed_price = rec["_parsed_price"]
        price_usd = round(parsed_price * rate, 2)

        # 3. Unit to kg
        raw_unit = str(rec.get("weight_unit_raw", supplier_cfg.default_weight_unit)).strip().lower()
        unit_info = references.unit_map.get(raw_unit, {"conversion_factor_to_kg": 1.0})
        factor = unit_info["conversion_factor_to_kg"]
        parsed_weight = rec["_parsed_weight"]
        weight_kg = round(parsed_weight * factor, 4)

        # 4. Category ID
        raw_cat = str(rec.get("category_code_raw", "")).strip().lower()
        cat_info = references.category_map.get(raw_cat, {"category_id": "CAT_UNKNOWN"})
        category_id = cat_info["category_id"]

        # 5. Color ID
        raw_color = str(rec.get("color_code_raw", "")).strip().lower()
        color_info = references.color_map.get(raw_color, {"color_id": "CLR_UNKNOWN"})
        color_id = color_info["color_id"]

        # 6. Country Code ISO-2
        raw_country = str(rec.get("country_raw", "")).strip().lower()
        country_info = references.country_map.get(raw_country, {"country_code": "UNKNOWN"})
        country_code = country_info["country_code"]

        # 7. Date to ISO-8601 UTC
        dt_utc = rec["_parsed_date"]
        source_updated_at = dt_utc.isoformat()

        # 8. GTIN and Stock
        gtin = rec.get("_clean_gtin") or None
        stock_qty = rec["_parsed_stock"]

        version_record: Dict[str, Any] = {
            "supplier_product_key": rec["supplier_product_key"],
            "supplier_id": supplier_cfg.supplier_id,
            "supplier_sku": str(rec["supplier_sku"]).strip(),
            "gtin": gtin,
            "name_std": name_std,
            "category_id": category_id,
            "price_usd": price_usd,
            "weight_kg": weight_kg,
            "color_id": color_id,
            "country_code": country_code,
            "stock_qty": stock_qty,
            "source_updated_at": source_updated_at,
            "run_id": run_id,
            "source_file": rec["_source_file"],
            "source_row_number": rec["_source_row_number"],
            "record_hash": rec["record_hash"],
            # Retain parsed raw values for conflict log/audit
            "_raw_price": parsed_price,
            "_raw_currency": raw_curr,
            "_raw_weight": parsed_weight,
            "_raw_unit": raw_unit,
        }
        standardized.append(version_record)

    return standardized
