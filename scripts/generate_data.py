#!/usr/bin/env python3
"""
Synthetic data generator for supplier-feed-harmonizer.
Generates realistic multi-supplier catalog data with intentional edge cases,
corrupted records, schema violations, duplicates, and ground-truth labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple


def calculate_gtin13_checksum(digits12: str) -> str:
    """Calculate the 13th check digit for a 12-digit GTIN/EAN prefix."""
    total = 0
    for idx, char in enumerate(digits12):
        n = int(char)
        total += n if idx % 2 == 0 else n * 3
    checksum = (10 - (total % 10)) % 10
    return str(checksum)


def generate_valid_gtin13(rng: random.Random) -> str:
    """Generate a mathematically valid 13-digit EAN-13/GTIN."""
    prefix12 = "".join([str(rng.randint(0, 9)) for _ in range(12)])
    return prefix12 + calculate_gtin13_checksum(prefix12)


def generate_invalid_gtin13(rng: random.Random) -> str:
    """Generate an invalid GTIN (wrong checksum)."""
    prefix12 = "".join([str(rng.randint(0, 9)) for _ in range(12)])
    correct_chk = int(calculate_gtin13_checksum(prefix12))
    bad_chk = (correct_chk + rng.randint(1, 9)) % 10
    return prefix12 + str(bad_chk)


# Canonical catalog reference pool
PRODUCT_TEMPLATES = [
    {
        "brand": "TechCorp",
        "name": "Wireless Noise Cancelling Headphones",
        "cat_a": "EL-03", "cat_b": "Electronics > Audio", "cat_c": "103",
        "price_usd": 199.99, "weight_kg": 0.35, "color_a": "BLK", "color_b": "Black", "color_c": "Schwarz",
        "country_a": "US", "country_b": "United States", "country_c": "Vereinigte Staaten",
    },
    {
        "brand": "UltraSound",
        "name": "Bluetooth Portable Speaker",
        "cat_a": "EL-03", "cat_b": "Electronics > Audio", "cat_c": "103",
        "price_usd": 79.50, "weight_kg": 0.65, "color_a": "BLU", "color_b": "Blue", "color_c": "Blau",
        "country_a": "DE", "country_b": "Germany", "country_c": "Deutschland",
    },
    {
        "brand": "SmartLife",
        "name": "Pro Smartphone 128GB",
        "cat_a": "EL-02", "cat_b": "Electronics > Phones", "cat_c": "102",
        "price_usd": 699.00, "weight_kg": 0.18, "color_a": "SLV", "color_b": "Silver", "color_c": "Silber",
        "country_a": "CN", "country_b": "China", "country_c": "China",
    },
    {
        "brand": "PixelGear",
        "name": "4K Ultra HD Action Camera",
        "cat_a": "EL-01", "cat_b": "Electronics", "cat_c": "101",
        "price_usd": 249.99, "weight_kg": 0.15, "color_a": "BLK", "color_b": "Black", "color_c": "Schwarz",
        "country_a": "JP", "country_b": "Japan", "country_c": "Japan",
    },
    {
        "brand": "ChefMaster",
        "name": "Stainless Steel Kitchen Knife Set",
        "cat_a": "HOME-01", "cat_b": "Home > Kitchen", "cat_c": "201",
        "price_usd": 89.95, "weight_kg": 1.20, "color_a": "SLV", "color_b": "Silver", "color_c": "Silber",
        "country_a": "DE", "country_b": "Germany", "country_c": "Deutschland",
    },
    {
        "brand": "HomeComfort",
        "name": "Electric Smart Kettle 1.7L",
        "cat_a": "HOME-02", "cat_b": "Home > Appliances", "cat_c": "202",
        "price_usd": 45.00, "weight_kg": 0.95, "color_a": "WHT", "color_b": "White", "color_c": "Weiß",
        "country_a": "FR", "country_b": "France", "country_c": "Frankreich",
    },
    {
        "brand": "ErgoOffice",
        "name": "Ergonomic Mesh Swivel Chair",
        "cat_a": "OFFICE-01", "cat_b": "Office > Supplies", "cat_c": "301",
        "price_usd": 180.00, "weight_kg": 11.50, "color_a": "GRY", "color_b": "Grey", "color_c": "Grau",
        "country_a": "US", "country_b": "United States", "country_c": "USA",
    },
    {
        "brand": "PeakTrek",
        "name": "Lightweight Camping Tent 2-Person",
        "cat_a": "OUTDOOR-01", "cat_b": "Sports > Outdoors", "cat_c": "401",
        "price_usd": 129.99, "weight_kg": 2.40, "color_a": "GRN", "color_b": "Green", "color_c": "Grün",
        "country_a": "CA", "country_b": "Canada", "country_c": "Canada",
    },
]


def generate_dataset(
    target_rows: int,
    seed: int = 42,
    out_dir: str = "sample_data/input",
    expected_labels_path: str = "sample_data/expected/labels.json",
) -> Dict[str, Any]:
    """Generates synthetic data files across suppliers A, B, and C."""
    rng = random.Random(seed)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    exp_path = Path(expected_labels_path)
    exp_path.parent.mkdir(parents=True, exist_ok=True)

    base_date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Estimate partition per supplier
    supplier_target = max(20, target_rows // 3)

    labels: Dict[str, Any] = {
        "metadata": {
            "target_rows": target_rows,
            "seed": seed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "intentional_invalid_records": [],
        "intentional_duplicates": [],
        "expected_golden_products_count": 0,
        "files_summary": {},
    }

    # Generate shared core products pool
    # We will generate canonical products that might appear across multiple suppliers
    num_products = max(10, supplier_target // 2)
    products_pool: List[Dict[str, Any]] = []

    for i in range(num_products):
        template = PRODUCT_TEMPLATES[i % len(PRODUCT_TEMPLATES)]
        has_gtin = (i % 8 != 0)  # 1 in 8 has NO GTIN, falls back to brand/name matching
        gtin = generate_valid_gtin13(rng) if has_gtin else ""
        brand = template["brand"]
        name_suffix = f" Model-{i+1}" if i >= len(PRODUCT_TEMPLATES) else ""
        prod_name = template["name"] + name_suffix

        products_pool.append({
            "product_index": i,
            "gtin": gtin,
            "brand": brand,
            "name": prod_name,
            "template": template,
            "price_usd": round(template["price_usd"] * rng.uniform(0.9, 1.1), 2),
            "weight_kg": round(template["weight_kg"] * rng.uniform(0.95, 1.05), 3),
        })

    # Track golden product keys
    golden_gtins = set()
    golden_brand_names = set()

    # Data containers for suppliers
    records_a: List[List[Any]] = []
    records_b: List[Dict[str, Any]] = []
    records_c: List[List[Any]] = []
    records_a_late: List[List[Any]] = []

    # -------------------------------------------------------------
    # 1. Supplier A: CSV (sku, product_name, cat_code, price, weight_lb, color_code, updated_at, stock_qty, country, gtin)
    # -------------------------------------------------------------
    file_a_name = "supplier_a_feed.csv"
    headers_a = ["sku", "product_name", "cat_code", "price", "weight_lb", "color_code", "updated_at", "stock_qty", "country", "gtin"]

    for idx in range(supplier_target):
        p = products_pool[idx % len(products_pool)]
        if p["gtin"]:
            golden_gtins.add(p["gtin"])
        else:
            golden_brand_names.add(f"{p['brand']}|{p['name']}")

        sku = f"SKU-A-{p['product_index']:05d}"
        price_val = round(p["price_usd"], 2)
        weight_lb = round(p["weight_kg"] * 2.20462, 2)
        up_date = (base_date + timedelta(days=idx % 30)).isoformat()
        stock = rng.randint(0, 500)
        gtin = p["gtin"]

        rec = [
            sku,
            f"{p['brand']} {p['name']}",
            p["template"]["cat_a"],
            f"{price_val:.2f}",
            f"{weight_lb:.2f}",
            p["template"]["color_a"],
            up_date,
            str(stock),
            p["template"]["country_a"],
            gtin,
        ]
        records_a.append(rec)

    # -------------------------------------------------------------
    # 2. Supplier B: JSONL (item_id, title, category, unit_price, weight, colour, last_modified, available, origin_country, gtin)
    # -------------------------------------------------------------
    file_b_name = "supplier_b_feed.jsonl"
    for idx in range(supplier_target):
        p = products_pool[idx % len(products_pool)]
        if p["gtin"]:
            golden_gtins.add(p["gtin"])
        else:
            golden_brand_names.add(f"{p['brand']}|{p['name']}")

        item_id = f"ITEM-B-{p['product_index']:05d}"
        # Intentional conflict variations for price & weight & color
        price_amt = round(p["price_usd"] * 1.05, 2)
        weight_val = round(p["weight_kg"], 3)
        # Epoch seconds
        m_epoch = int((base_date + timedelta(days=(idx % 30) + 1, hours=2)).timestamp())
        avail = rng.randint(0, 300)
        gtin = p["gtin"]

        rec_b = {
            "item_id": item_id,
            "title": f"  {p['brand']}   {p['name']}  ",  # tests string trimming / space collapsing
            "category": p["template"]["cat_b"],
            "unit_price": {"amount": price_amt, "currency": "USD"},
            "weight": {"value": weight_val, "unit": "kg"},
            "colour": p["template"]["color_b"],
            "last_modified": m_epoch,
            "available": avail,
            "origin_country": p["template"]["country_b"],
            "gtin": gtin,
        }
        records_b.append(rec_b)

    # -------------------------------------------------------------
    # 3. Supplier C: CSV (semicolon, ISO-8859-1, decimal comma)
    # art_nr;bezeichnung;warengruppe;preis_eur;gewicht_kg;farbe;stand;lager;herkunft;gtin
    # -------------------------------------------------------------
    file_c_name = "supplier_c_feed.csv"
    headers_c = ["art_nr", "bezeichnung", "warengruppe", "preis_eur", "gewicht_kg", "farbe", "stand", "lager", "herkunft", "gtin"]

    for idx in range(supplier_target):
        p = products_pool[idx % len(products_pool)]
        if p["gtin"]:
            golden_gtins.add(p["gtin"])
        else:
            golden_brand_names.add(f"{p['brand']}|{p['name']}")

        art_nr = f"ART-C-{p['product_index']:05d}"
        # Price in EUR (approx USD / 1.08)
        price_eur = round(p["price_usd"] / 1.08, 2)
        price_eur_str = f"{price_eur:.2f}".replace(".", ",")
        weight_kg_str = f"{p['weight_kg']:.3f}".replace(".", ",")
        # stand date format: dd.mm.yyyy
        stand_dt = base_date + timedelta(days=(idx % 30) - 2)
        stand_str = stand_dt.strftime("%d.%m.%Y")
        lager = rng.randint(0, 150)
        gtin = p["gtin"]

        rec_c = [
            art_nr,
            f"{p['brand']} {p['name']} Sonderedition",
            p["template"]["cat_c"],
            price_eur_str,
            weight_kg_str,
            p["template"]["color_c"],
            stand_str,
            str(lager),
            p["template"]["country_c"],
            gtin,
        ]
        records_c.append(rec_c)

    # -------------------------------------------------------------
    # Add Edge Cases and Corrupted Records
    # -------------------------------------------------------------

    # A. Exact Duplicates within file A
    if records_a:
        dup_row = list(records_a[0])
        records_a.append(dup_row)
        labels["intentional_duplicates"].append({
            "file": file_a_name,
            "sku": dup_row[0],
            "description": "Exact duplicate row in Supplier A"
        })

    # B. Boundary Values (price 0.01, large price 99999.99, weight 0, very long name, unicode)
    records_a.append([
        "SKU-A-BOUND-1",
        "TechCorp Micro Cable 0.01 Special",
        "EL-01",
        "0.01",
        "0.00",  # weight 0
        "BLK",
        base_date.isoformat(),
        "50",
        "US",
        generate_valid_gtin13(rng),
    ])
    records_a.append([
        "SKU-A-BOUND-2",
        "Enterprise Super Server " + ("Ultra " * 50) + "Edition",  # long name
        "EL-01",
        "99999.99",  # large price
        "250.00",
        "SLV",
        base_date.isoformat(),
        "2",
        "US",
        generate_valid_gtin13(rng),
    ])
    # Add to expected golden products
    golden_gtins.add(records_a[-2][9])
    golden_gtins.add(records_a[-1][9])

    # C. Intentional Malformed Records (Supplier A)
    # 1. Negative Price
    row_num = len(records_a) + 2  # 1-indexed including header
    records_a.append([
        "SKU-A-ERR-NEGPRICE",
        "Faulty Widget Negative",
        "EL-01",
        "-19.99",
        "1.5",
        "BLK",
        base_date.isoformat(),
        "10",
        "US",
        generate_valid_gtin13(rng),
    ])
    labels["intentional_invalid_records"].append({
        "file": file_a_name,
        "row_number": row_num,
        "sku": "SKU-A-ERR-NEGPRICE",
        "error_code": "NEGATIVE_PRICE",
        "reason": "Price is negative (-19.99)",
    })

    # 2. Bad GTIN Checksum
    bad_gtin = generate_invalid_gtin13(rng)
    row_num = len(records_a) + 2
    records_a.append([
        "SKU-A-ERR-BADGTIN",
        "Faulty GTIN Widget",
        "EL-01",
        "29.99",
        "1.0",
        "BLK",
        base_date.isoformat(),
        "10",
        "US",
        bad_gtin,
    ])
    labels["intentional_invalid_records"].append({
        "file": file_a_name,
        "row_number": row_num,
        "sku": "SKU-A-ERR-BADGTIN",
        "error_code": "BAD_GTIN",
        "reason": f"GTIN checksum mismatch ({bad_gtin})",
    })

    # 3. Invalid Reference Category Key
    row_num = len(records_a) + 2
    records_a.append([
        "SKU-A-ERR-BADCATEGORY",
        "Unknown Category Widget",
        "INVALID-CAT-999",
        "49.99",
        "2.0",
        "RED",
        base_date.isoformat(),
        "15",
        "US",
        generate_valid_gtin13(rng),
    ])
    labels["intentional_invalid_records"].append({
        "file": file_a_name,
        "row_number": row_num,
        "sku": "SKU-A-ERR-BADCATEGORY",
        "error_code": "REF_KEY_INVALID",
        "reason": "Category code 'INVALID-CAT-999' not in category_map.csv",
    })

    # 4. Missing Required Field (empty product_name)
    row_num = len(records_a) + 2
    records_a.append([
        "SKU-A-ERR-MISSINGNAME",
        "",  # missing name
        "EL-01",
        "15.00",
        "0.5",
        "BLK",
        base_date.isoformat(),
        "5",
        "US",
        generate_valid_gtin13(rng),
    ])
    labels["intentional_invalid_records"].append({
        "file": file_a_name,
        "row_number": row_num,
        "sku": "SKU-A-ERR-MISSINGNAME",
        "error_code": "MISSING_REQUIRED",
        "reason": "Required field product_name is empty",
    })

    # 5. Bad Date
    row_num = len(records_a) + 2
    records_a.append([
        "SKU-A-ERR-BADDATE",
        "Bad Date Widget",
        "EL-01",
        "25.00",
        "0.8",
        "BLK",
        "not-a-valid-date-32/13/2026",
        "8",
        "US",
        generate_valid_gtin13(rng),
    ])
    labels["intentional_invalid_records"].append({
        "file": file_a_name,
        "row_number": row_num,
        "sku": "SKU-A-ERR-BADDATE",
        "error_code": "BAD_DATE",
        "reason": "Date string is unparseable",
    })

    # 6. Malformed CSV Row (Wrong column count)
    records_a_raw_lines = [",".join(headers_a)]
    for r in records_a:
        # Quote any field with comma
        quoted = ['"' + str(x).replace('"', '""') + '"' if ',' in str(x) else str(x) for x in r]
        records_a_raw_lines.append(",".join(quoted))

    bad_col_line_num = len(records_a_raw_lines) + 1
    records_a_raw_lines.append("SKU-A-ERR-WRONGCOL,Incomplete Column Record,EL-01,9.99")  # only 4 columns
    labels["intentional_invalid_records"].append({
        "file": file_a_name,
        "row_number": bad_col_line_num,
        "sku": "SKU-A-ERR-WRONGCOL",
        "error_code": "MALFORMED_RECORD",
        "reason": "Wrong column count in CSV line",
    })

    # D. Intentional Malformed JSON Lines in Supplier B
    # 1. Broken JSON line
    # 2. Negative price
    # 3. Invalid reference country
    records_b_raw_lines = [json.dumps(r) for r in records_b]

    # Broken JSON
    bad_json_line_num = len(records_b_raw_lines) + 1
    records_b_raw_lines.append('{"item_id": "ITEM-B-ERR-BROKENJSON", "title": "Broken Json Line", "unit_price": ')  # syntax error
    labels["intentional_invalid_records"].append({
        "file": file_b_name,
        "row_number": bad_json_line_num,
        "sku": "ITEM-B-ERR-BROKENJSON",
        "error_code": "MALFORMED_RECORD",
        "reason": "Malformed JSON syntax",
    })

    # Bad numeric price
    bad_num_line_num = len(records_b_raw_lines) + 1
    records_b_raw_lines.append(json.dumps({
        "item_id": "ITEM-B-ERR-NONNUMPRICE",
        "title": "Non Numeric Price Widget",
        "category": "Electronics",
        "unit_price": {"amount": "INVALID_PRICE_ABC", "currency": "USD"},
        "weight": {"value": 1.0, "unit": "kg"},
        "colour": "Black",
        "last_modified": 1767225600,
        "available": 10,
        "origin_country": "United States",
        "gtin": generate_valid_gtin13(rng),
    }))
    labels["intentional_invalid_records"].append({
        "file": file_b_name,
        "row_number": bad_num_line_num,
        "sku": "ITEM-B-ERR-NONNUMPRICE",
        "error_code": "BAD_NUMERIC",
        "reason": "Non-numeric unit_price.amount string",
    })

    # Invalid Reference Country
    bad_country_line_num = len(records_b_raw_lines) + 1
    records_b_raw_lines.append(json.dumps({
        "item_id": "ITEM-B-ERR-BADCOUNTRY",
        "title": "Atlantis Gadget",
        "category": "Electronics",
        "unit_price": {"amount": 39.99, "currency": "USD"},
        "weight": {"value": 1.0, "unit": "kg"},
        "colour": "Black",
        "last_modified": 1767225600,
        "available": 10,
        "origin_country": "Atlantis Kingdom",  # Unknown country
        "gtin": generate_valid_gtin13(rng),
    }))
    labels["intentional_invalid_records"].append({
        "file": file_b_name,
        "row_number": bad_country_line_num,
        "sku": "ITEM-B-ERR-BADCOUNTRY",
        "error_code": "REF_KEY_INVALID",
        "reason": "Origin country 'Atlantis Kingdom' not in country_map.csv",
    })

    # E. Out-of-order & Late-arriving versions (Supplier A Late File)
    # Take the first 3 products from Supplier A and produce an older update timestamp
    file_late_name = "supplier_a_late_arriving.csv"
    records_late_raw = [",".join(headers_a)]
    for idx in range(min(3, len(records_a))):
        orig = records_a[idx]
        older_date = (base_date - timedelta(days=15)).isoformat()
        older_price = "999.00"  # higher price, but older timestamp so golden should NOT pick it
        late_row = [
            orig[0],  # same sku
            orig[1],
            orig[2],
            older_price,
            orig[4],
            orig[5],
            older_date,  # older date
            "999",
            orig[8],
            orig[9],
        ]
        records_late_raw.append(",".join(late_row))

    # F. Schema Corrupted File (renamed / missing required column)
    file_corrupt_schema = "supplier_a_invalid_schema.csv"
    bad_headers_a = ["product_code_renamed", "product_name", "cat_code", "price", "weight_lb", "color_code", "updated_at", "stock_qty", "country"]
    bad_schema_lines = [
        ",".join(bad_headers_a),
        "BAD-SKU-001,Some Product,EL-01,10.00,1.0,BLK,2026-01-01T00:00:00Z,10,US",
    ]

    # G. Empty file (0 bytes)
    file_empty_name = "supplier_a_empty.csv"

    # H. Header-only file (0 data rows)
    file_header_only_name = "supplier_a_header_only.csv"
    header_only_lines = [",".join(headers_a)]

    # -------------------------------------------------------------
    # Write all files to disk
    # -------------------------------------------------------------

    # 1. supplier_a_feed.csv
    with open(out_path / file_a_name, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(records_a_raw_lines) + "\n")

    # 2. supplier_b_feed.jsonl
    with open(out_path / file_b_name, "w", encoding="utf-8") as f:
        f.write("\n".join(records_b_raw_lines) + "\n")

    # 3. supplier_c_feed.csv (ISO-8859-1, semicolon)
    with open(out_path / file_c_name, "w", encoding="iso-8859-1", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers_c)
        for r in records_c:
            writer.writerow(r)

    # 4. supplier_a_late_arriving.csv
    with open(out_path / file_late_name, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(records_late_raw) + "\n")

    # 5. supplier_a_invalid_schema.csv
    with open(out_path / file_corrupt_schema, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(bad_schema_lines) + "\n")

    # 6. supplier_a_empty.csv
    with open(out_path / file_empty_name, "wb") as f:
        pass  # 0 bytes

    # 7. supplier_a_header_only.csv
    with open(out_path / file_header_only_name, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(header_only_lines) + "\n")

    # Calculate expected golden count
    # Each unique GTIN represents 1 golden product.
    # Products without GTIN are matched by brand|name.
    labels["expected_golden_products_count"] = len(golden_gtins) + len(golden_brand_names)
    labels["unique_gtin_count"] = len(golden_gtins)
    labels["unique_brand_name_fallback_count"] = len(golden_brand_names)

    labels["files_summary"] = {
        file_a_name: {"total_lines": len(records_a_raw_lines)},
        file_b_name: {"total_lines": len(records_b_raw_lines)},
        file_c_name: {"total_lines": len(records_c) + 1},
        file_late_name: {"total_lines": len(records_late_raw)},
        file_corrupt_schema: {"total_lines": len(bad_schema_lines), "quarantine_expected": True},
        file_empty_name: {"total_bytes": 0, "status_expected": "success_empty"},
        file_header_only_name: {"total_lines": 1, "status_expected": "success_empty"},
    }

    with open(exp_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2)

    print(f"Generated test feeds in '{out_dir}' with {labels['expected_golden_products_count']} expected golden products.")
    print(f"Expected labels written to '{expected_labels_path}'.")
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic feeds for supplier-feed-harmonizer")
    parser.add_argument("--rows", type=int, default=300, help="Approximate number of rows to generate (default: 300)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible feeds (default: 42)")
    parser.add_argument("--out", type=str, default="sample_data/input", help="Output directory for feed files")
    parser.add_argument("--labels", type=str, default="sample_data/expected/labels.json", help="Path for labels.json")
    args = parser.parse_args()

    generate_dataset(
        target_rows=args.rows,
        seed=args.seed,
        out_dir=args.out,
        expected_labels_path=args.labels,
    )


if __name__ == "__main__":
    main()
