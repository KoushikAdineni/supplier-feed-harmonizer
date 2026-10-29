"""
Entity and conflict resolution module for supplier-feed-harmonizer.
Groups product versions across suppliers by GTIN-13 (high confidence) or brand/name
fallback (low confidence), resolves attribute conflicts deterministically, logs
conflict history, and tracks end-to-end attribute lineage.
"""

from __future__ import annotations

import collections
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.harmonizer.config import PipelineConfig, SupplierConfig
from src.harmonizer.ids import generate_product_id


def resolve_entities(
    versions: List[Dict[str, Any]],
    supplier_configs: Dict[str, SupplierConfig],
    run_id: str,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Performs cross-supplier entity grouping and deterministic attribute conflict resolution.
    Returns:
        (golden_products, lineage_records, conflict_records)
    """
    now_utc = datetime.now(timezone.utc).isoformat()

    # 1. Group records by matching key
    # If GTIN present: key is ('gtin', gtin_val) -> High confidence
    # If GTIN missing: key is ('brand_name', normalized_name) -> Low confidence
    grouped_products: Dict[Tuple[str, str], List[Dict[str, Any]]] = collections.defaultdict(list)

    for v in versions:
        gtin = v.get("gtin")
        if gtin:
            group_key = ("gtin", str(gtin).strip())
        else:
            # Fallback to normalized name
            group_key = ("brand_name", str(v.get("name_std", "")).strip().lower())
        grouped_products[group_key].append(v)

    golden_products: List[Dict[str, Any]] = []
    lineage_records: List[Dict[str, Any]] = []
    conflict_records: List[Dict[str, Any]] = []

    for (match_type, key_val), candidates in grouped_products.items():
        # Derive deterministic product_id
        if match_type == "gtin":
            prod_id = generate_product_id(gtin=key_val)
            match_conf = "high"
            gtin_val = key_val
        else:
            first_cand = candidates[0]
            prod_id = generate_product_id(
                gtin=None,
                supplier_id=first_cand["supplier_id"],
                brand="",
                name=first_cand["name_std"]
            )
            match_conf = "low"
            gtin_val = None

        # For each supplier, take their latest version by source_updated_at
        supplier_latest: Dict[str, Dict[str, Any]] = {}
        for c in candidates:
            sid = c["supplier_id"]
            if sid not in supplier_latest:
                supplier_latest[sid] = c
            else:
                if c["source_updated_at"] > supplier_latest[sid]["source_updated_at"]:
                    supplier_latest[sid] = c

        active_candidates = list(supplier_latest.values())
        source_count = len(active_candidates)

        # Helper to get priority rank (lower number = higher priority)
        def get_rank(item: Dict[str, Any]) -> int:
            cfg = supplier_configs.get(item["supplier_id"])
            return cfg.priority_rank if cfg else 999

        # -------------------------------------------------------------
        # Attribute 1 & 2: Price (USD) and Stock Qty
        # Rule (a): Most recent valid source_updated_at wins
        # -------------------------------------------------------------
        # Sort by source_updated_at desc, then priority rank asc
        price_cands = [c for c in active_candidates if c.get("price_usd") is not None]
        price_cands.sort(key=lambda x: (x["source_updated_at"], -get_rank(x)), reverse=True)
        chosen_price_cand = price_cands[0]
        chosen_price = chosen_price_cand["price_usd"]

        # Conflict check for price
        distinct_prices = {c["supplier_id"]: c["price_usd"] for c in price_cands}
        if len(set(distinct_prices.values())) > 1:
            conflict_records.append({
                "product_id": prod_id,
                "attribute_name": "price_usd",
                "supplier_values_json": json.dumps(distinct_prices),
                "resolution_rule": "latest_source_updated_at",
                "run_id": run_id,
            })

        # Price Lineage
        alt_prices = [
            {"supplier_id": c["supplier_id"], "value": c["price_usd"], "source_updated_at": c["source_updated_at"]}
            for c in price_cands if c["supplier_id"] != chosen_price_cand["supplier_id"]
        ]
        lineage_records.append({
            "product_id": prod_id,
            "attribute_name": "price_usd",
            "chosen_value": str(chosen_price),
            "chosen_supplier_id": chosen_price_cand["supplier_id"],
            "chosen_source_file": chosen_price_cand["source_file"],
            "chosen_source_row_number": chosen_price_cand["source_row_number"],
            "chosen_run_id": chosen_price_cand["run_id"],
            "rule_applied": "latest_source_updated_at",
            "alternatives_json": json.dumps(alt_prices),
        })

        # Stock Qty
        stock_cands = [c for c in active_candidates if c.get("stock_qty") is not None]
        stock_cands.sort(key=lambda x: (x["source_updated_at"], -get_rank(x)), reverse=True)
        chosen_stock_cand = stock_cands[0]
        chosen_stock = chosen_stock_cand["stock_qty"]

        # Total stock: can be latest winner or sum across active suppliers
        # We record winning latest stock as the chosen attribute
        distinct_stocks = {c["supplier_id"]: c["stock_qty"] for c in stock_cands}
        if len(set(distinct_stocks.values())) > 1:
            conflict_records.append({
                "product_id": prod_id,
                "attribute_name": "total_stock",
                "supplier_values_json": json.dumps(distinct_stocks),
                "resolution_rule": "latest_source_updated_at",
                "run_id": run_id,
            })

        alt_stocks = [
            {"supplier_id": c["supplier_id"], "value": c["stock_qty"], "source_updated_at": c["source_updated_at"]}
            for c in stock_cands if c["supplier_id"] != chosen_stock_cand["supplier_id"]
        ]
        lineage_records.append({
            "product_id": prod_id,
            "attribute_name": "total_stock",
            "chosen_value": str(chosen_stock),
            "chosen_supplier_id": chosen_stock_cand["supplier_id"],
            "chosen_source_file": chosen_stock_cand["source_file"],
            "chosen_source_row_number": chosen_stock_cand["source_row_number"],
            "chosen_run_id": chosen_stock_cand["run_id"],
            "rule_applied": "latest_source_updated_at",
            "alternatives_json": json.dumps(alt_stocks),
        })

        # -------------------------------------------------------------
        # Attribute 3: Weight (kg)
        # Rule (c): Majority value among suppliers, tie broken by priority
        # -------------------------------------------------------------
        weight_cands = [c for c in active_candidates if c.get("weight_kg") is not None]
        weight_counts: Dict[float, int] = collections.Counter([c["weight_kg"] for c in weight_cands])
        max_count = max(weight_counts.values())
        top_weights = [w for w, count in weight_counts.items() if count == max_count]

        if len(top_weights) == 1:
            winning_weight = top_weights[0]
            # Pick candidate with that weight and lowest priority rank
            matching_cands = [c for c in weight_cands if c["weight_kg"] == winning_weight]
            matching_cands.sort(key=get_rank)
            chosen_weight_cand = matching_cands[0]
            weight_rule = "majority_vote"
        else:
            # Tie: broken by supplier priority rank
            tied_cands = [c for c in weight_cands if c["weight_kg"] in top_weights]
            tied_cands.sort(key=get_rank)
            chosen_weight_cand = tied_cands[0]
            winning_weight = chosen_weight_cand["weight_kg"]
            weight_rule = "majority_vote_then_priority"

        distinct_weights = {c["supplier_id"]: c["weight_kg"] for c in weight_cands}
        if len(set(distinct_weights.values())) > 1:
            conflict_records.append({
                "product_id": prod_id,
                "attribute_name": "weight_kg",
                "supplier_values_json": json.dumps(distinct_weights),
                "resolution_rule": weight_rule,
                "run_id": run_id,
            })

        alt_weights = [
            {"supplier_id": c["supplier_id"], "value": c["weight_kg"]}
            for c in weight_cands if c["supplier_id"] != chosen_weight_cand["supplier_id"]
        ]
        lineage_records.append({
            "product_id": prod_id,
            "attribute_name": "weight_kg",
            "chosen_value": str(winning_weight),
            "chosen_supplier_id": chosen_weight_cand["supplier_id"],
            "chosen_source_file": chosen_weight_cand["source_file"],
            "chosen_source_row_number": chosen_weight_cand["source_row_number"],
            "chosen_run_id": chosen_weight_cand["run_id"],
            "rule_applied": weight_rule,
            "alternatives_json": json.dumps(alt_weights),
        })

        # -------------------------------------------------------------
        # Attributes 4, 5, 6, 7: Name, Category, Color, Country
        # Rule (b): Supplier priority_rank wins when values differ
        # Rule (d): Null never overrides a non-null
        # -------------------------------------------------------------
        for attr in ["name_std", "category_id", "color_id", "country_code"]:
            non_null_cands = [c for c in active_candidates if c.get(attr)]
            if not non_null_cands:
                non_null_cands = active_candidates
            non_null_cands.sort(key=get_rank)
            chosen_cand = non_null_cands[0]
            chosen_val = str(chosen_cand.get(attr, ""))

            distinct_vals = {c["supplier_id"]: str(c.get(attr, "")) for c in non_null_cands}
            if len(set(distinct_vals.values())) > 1:
                conflict_records.append({
                    "product_id": prod_id,
                    "attribute_name": attr,
                    "supplier_values_json": json.dumps(distinct_vals),
                    "resolution_rule": "supplier_priority",
                    "run_id": run_id,
                })

            alt_vals = [
                {"supplier_id": c["supplier_id"], "value": str(c.get(attr, ""))}
                for c in non_null_cands if c["supplier_id"] != chosen_cand["supplier_id"]
            ]
            lineage_records.append({
                "product_id": prod_id,
                "attribute_name": attr,
                "chosen_value": chosen_val,
                "chosen_supplier_id": chosen_cand["supplier_id"],
                "chosen_source_file": chosen_cand["source_file"],
                "chosen_source_row_number": chosen_cand["source_row_number"],
                "chosen_run_id": chosen_cand["run_id"],
                "rule_applied": "supplier_priority",
                "alternatives_json": json.dumps(alt_vals),
            })

            if attr == "name_std":
                chosen_name = chosen_val
            elif attr == "category_id":
                chosen_category = chosen_val
            elif attr == "color_id":
                chosen_color = chosen_val
            elif attr == "country_code":
                chosen_country = chosen_val

        # Assemble golden product record
        golden_products.append({
            "product_id": prod_id,
            "gtin": gtin_val,
            "name_std": chosen_name,
            "category_id": chosen_category,
            "price_usd": chosen_price,
            "weight_kg": winning_weight,
            "color_id": chosen_color,
            "country_code": chosen_country,
            "total_stock": chosen_stock,
            "match_confidence": match_conf,
            "source_count": source_count,
            "last_resolved_run_id": run_id,
            "updated_at": now_utc,
        })

    return golden_products, lineage_records, conflict_records
