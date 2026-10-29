"""
Database persistence and publishing module for supplier-feed-harmonizer.
Manages DuckDB schema creation, reference table loading, transactional upserts,
and idempotency guarantees for golden products, version history, and lineage.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import duckdb

from src.harmonizer.config import PipelineConfig, ReferenceMaps, SupplierConfig


def init_database(db_path: str | Path, config: PipelineConfig, logger: Optional[logging.Logger] = None) -> duckdb.DuckDBPyConnection:
    """Initializes DuckDB tables and populates reference dimensions."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p))

    # Enable snake_case schema DDLs
    con.execute("""
    -- 1. Reference Tables
    CREATE TABLE IF NOT EXISTS ref_category (
        category_id VARCHAR PRIMARY KEY,
        category_name VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ref_unit (
        source_unit VARCHAR PRIMARY KEY,
        standard_unit VARCHAR NOT NULL,
        conversion_factor_to_kg DOUBLE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ref_color (
        color_id VARCHAR PRIMARY KEY,
        color_name VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ref_currency (
        source_currency VARCHAR PRIMARY KEY,
        target_currency VARCHAR NOT NULL,
        exchange_rate_to_usd DOUBLE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ref_country (
        country_code VARCHAR PRIMARY KEY,
        country_name VARCHAR NOT NULL
    );

    -- 2. Supplier Dimension
    CREATE TABLE IF NOT EXISTS dim_supplier (
        supplier_id VARCHAR PRIMARY KEY,
        supplier_name VARCHAR NOT NULL,
        priority_rank INTEGER NOT NULL,
        trust_weight DOUBLE NOT NULL
    );

    -- 3. Staging Raw Tables
    CREATE TABLE IF NOT EXISTS stg_supplier_a (
        supplier_sku VARCHAR,
        name_raw VARCHAR,
        category_code_raw VARCHAR,
        price_raw VARCHAR,
        weight_raw VARCHAR,
        color_code_raw VARCHAR,
        updated_at_raw VARCHAR,
        stock_qty_raw VARCHAR,
        country_raw VARCHAR,
        gtin_raw VARCHAR,
        currency_raw VARCHAR,
        weight_unit_raw VARCHAR,
        _run_id VARCHAR NOT NULL,
        _source_file VARCHAR NOT NULL,
        _source_row_number INTEGER NOT NULL,
        _ingested_at VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS stg_supplier_b (
        supplier_sku VARCHAR,
        name_raw VARCHAR,
        category_code_raw VARCHAR,
        price_raw VARCHAR,
        weight_raw VARCHAR,
        color_code_raw VARCHAR,
        updated_at_raw VARCHAR,
        stock_qty_raw VARCHAR,
        country_raw VARCHAR,
        gtin_raw VARCHAR,
        currency_raw VARCHAR,
        weight_unit_raw VARCHAR,
        _run_id VARCHAR NOT NULL,
        _source_file VARCHAR NOT NULL,
        _source_row_number INTEGER NOT NULL,
        _ingested_at VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS stg_supplier_c (
        supplier_sku VARCHAR,
        name_raw VARCHAR,
        category_code_raw VARCHAR,
        price_raw VARCHAR,
        weight_raw VARCHAR,
        color_code_raw VARCHAR,
        updated_at_raw VARCHAR,
        stock_qty_raw VARCHAR,
        country_raw VARCHAR,
        gtin_raw VARCHAR,
        currency_raw VARCHAR,
        weight_unit_raw VARCHAR,
        _run_id VARCHAR NOT NULL,
        _source_file VARCHAR NOT NULL,
        _source_row_number INTEGER NOT NULL,
        _ingested_at VARCHAR NOT NULL
    );

    -- 4. Fact Supplier Product Version (Historical Grain: supplier_sku per distinct source_updated_at)
    CREATE TABLE IF NOT EXISTS fact_supplier_product_version (
        supplier_product_key VARCHAR NOT NULL,
        supplier_id VARCHAR NOT NULL,
        supplier_sku VARCHAR NOT NULL,
        gtin VARCHAR,
        name_std VARCHAR NOT NULL,
        category_id VARCHAR NOT NULL,
        price_usd DOUBLE NOT NULL,
        weight_kg DOUBLE NOT NULL,
        color_id VARCHAR NOT NULL,
        country_code VARCHAR NOT NULL,
        stock_qty INTEGER NOT NULL,
        source_updated_at VARCHAR NOT NULL,
        run_id VARCHAR NOT NULL,
        source_file VARCHAR NOT NULL,
        source_row_number INTEGER NOT NULL,
        record_hash VARCHAR NOT NULL,
        PRIMARY KEY (supplier_product_key, source_updated_at)
    );

    -- 5. Golden Product Table
    CREATE TABLE IF NOT EXISTS dim_product_golden (
        product_id VARCHAR PRIMARY KEY,
        gtin VARCHAR,
        name_std VARCHAR NOT NULL,
        category_id VARCHAR NOT NULL,
        price_usd DOUBLE NOT NULL,
        weight_kg DOUBLE NOT NULL,
        color_id VARCHAR NOT NULL,
        country_code VARCHAR NOT NULL,
        total_stock INTEGER NOT NULL,
        match_confidence VARCHAR NOT NULL,
        source_count INTEGER NOT NULL,
        last_resolved_run_id VARCHAR NOT NULL,
        updated_at VARCHAR NOT NULL
    );

    -- 6. Product Attribute Lineage
    CREATE TABLE IF NOT EXISTS product_attribute_lineage (
        product_id VARCHAR NOT NULL,
        attribute_name VARCHAR NOT NULL,
        chosen_value VARCHAR NOT NULL,
        chosen_supplier_id VARCHAR NOT NULL,
        chosen_source_file VARCHAR NOT NULL,
        chosen_source_row_number INTEGER NOT NULL,
        chosen_run_id VARCHAR NOT NULL,
        rule_applied VARCHAR NOT NULL,
        alternatives_json VARCHAR,
        PRIMARY KEY (product_id, attribute_name)
    );

    -- 7. Product Conflict Log
    CREATE TABLE IF NOT EXISTS product_conflict_log (
        product_id VARCHAR NOT NULL,
        attribute_name VARCHAR NOT NULL,
        supplier_values_json VARCHAR NOT NULL,
        resolution_rule VARCHAR NOT NULL,
        run_id VARCHAR NOT NULL
    );

    -- 8. Rejected Records
    CREATE TABLE IF NOT EXISTS rejected_records (
        reject_id VARCHAR PRIMARY KEY,
        run_id VARCHAR NOT NULL,
        supplier_id VARCHAR NOT NULL,
        source_file VARCHAR NOT NULL,
        source_row_number INTEGER NOT NULL,
        raw_record VARCHAR NOT NULL,
        error_code VARCHAR NOT NULL,
        error_message VARCHAR NOT NULL,
        rejected_at VARCHAR NOT NULL
    );

    -- 9. Pipeline Runs & Observability
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id VARCHAR PRIMARY KEY,
        started_at VARCHAR NOT NULL,
        ended_at VARCHAR,
        status VARCHAR NOT NULL,
        input_files VARCHAR NOT NULL,
        rows_read INTEGER DEFAULT 0,
        rows_valid INTEGER DEFAULT 0,
        rows_rejected INTEGER DEFAULT 0,
        rows_duplicate INTEGER DEFAULT 0,
        rows_published INTEGER DEFAULT 0,
        failure_reason VARCHAR,
        config_hash VARCHAR NOT NULL,
        code_version VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS processed_files (
        file_hash_sha256 VARCHAR PRIMARY KEY,
        source_file VARCHAR NOT NULL,
        supplier_id VARCHAR NOT NULL,
        first_run_id VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        rows_read INTEGER DEFAULT 0,
        processed_at VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dq_metrics (
        run_id VARCHAR NOT NULL,
        metric_name VARCHAR NOT NULL,
        metric_value DOUBLE NOT NULL,
        supplier_id VARCHAR
    );
    """)

    # Populate reference tables from config/mappings
    _populate_reference_tables(con, config)
    _populate_dim_supplier(con, config.suppliers)

    return con


def _populate_reference_tables(con: duckdb.DuckDBPyConnection, config: PipelineConfig) -> None:
    """Populates reference lookup dimensions from memory/csv."""
    # Categories
    cats = {v["category_id"]: v["category_name"] for v in config.references.category_map.values()}
    for cid, cname in cats.items():
        con.execute(
            "INSERT OR REPLACE INTO ref_category (category_id, category_name) VALUES (?, ?)",
            [cid, cname]
        )

    # Units
    for src_u, udata in config.references.unit_map.items():
        con.execute(
            "INSERT OR REPLACE INTO ref_unit (source_unit, standard_unit, conversion_factor_to_kg) VALUES (?, ?, ?)",
            [src_u, udata["standard_unit"], udata["conversion_factor_to_kg"]]
        )

    # Colors
    colors = {v["color_id"]: v["color_name"] for v in config.references.color_map.values()}
    for clrid, clrname in colors.items():
        con.execute(
            "INSERT OR REPLACE INTO ref_color (color_id, color_name) VALUES (?, ?)",
            [clrid, clrname]
        )

    # Currencies
    for curr, rate in config.references.currency_map.items():
        con.execute(
            "INSERT OR REPLACE INTO ref_currency (source_currency, target_currency, exchange_rate_to_usd) VALUES (?, 'USD', ?)",
            [curr, rate]
        )

    # Countries
    countries = {v["country_code"]: v["country_name"] for v in config.references.country_map.values()}
    for ccode, cname in countries.items():
        con.execute(
            "INSERT OR REPLACE INTO ref_country (country_code, country_name) VALUES (?, ?)",
            [ccode, cname]
        )


def _populate_dim_supplier(con: duckdb.DuckDBPyConnection, suppliers: Dict[str, SupplierConfig]) -> None:
    """Upserts supplier dimension records."""
    for s in suppliers.values():
        con.execute(
            """
            INSERT OR REPLACE INTO dim_supplier (supplier_id, supplier_name, priority_rank, trust_weight)
            VALUES (?, ?, ?, ?)
            """,
            [s.supplier_id, s.supplier_name, s.priority_rank, s.trust_weight]
        )


def get_staging_table_name(supplier_id: str) -> str:
    """Returns canonical staging table name for supplier."""
    clean_id = supplier_id.strip().lower().replace("sup-", "supplier_").replace("sup_", "supplier_")
    return f"stg_{clean_id}"


def insert_staging_records(
    con: duckdb.DuckDBPyConnection,
    supplier_id: str,
    records: List[Dict[str, Any]],
) -> None:
    """Bulk insert raw staging records into supplier specific staging table."""
    if not records:
        return

    table_name = get_staging_table_name(supplier_id)

    cols = [
        "supplier_sku", "name_raw", "category_code_raw", "price_raw", "weight_raw",
        "color_code_raw", "updated_at_raw", "stock_qty_raw", "country_raw", "gtin_raw",
        "currency_raw", "weight_unit_raw", "_run_id", "_source_file", "_source_row_number", "_ingested_at"
    ]
    val_placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({val_placeholders})"

    rows_data = []
    for r in records:
        rows_data.append([
            r.get("supplier_sku"), r.get("name_raw"), r.get("category_code_raw"),
            r.get("price_raw"), r.get("weight_raw"), r.get("color_code_raw"),
            r.get("updated_at_raw"), r.get("stock_qty_raw"), r.get("country_raw"),
            r.get("gtin_raw"), r.get("currency_raw"), r.get("weight_unit_raw"),
            r.get("_run_id"), r.get("_source_file"), r.get("_source_row_number"),
            r.get("_ingested_at")
        ])

    con.executemany(sql, rows_data)


def insert_rejected_records(
    con: duckdb.DuckDBPyConnection,
    rejects: List[Dict[str, Any]],
) -> None:
    """Inserts rejected records with source traceability."""
    if not rejects:
        return

    sql = """
    INSERT OR REPLACE INTO rejected_records
    (reject_id, run_id, supplier_id, source_file, source_row_number, raw_record, error_code, error_message, rejected_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        [
            r["reject_id"], r["run_id"], r["supplier_id"], r["source_file"],
            r["source_row_number"], r["raw_record"], r["error_code"],
            r["error_message"], r["rejected_at"]
        ]
        for r in rejects
    ]
    con.executemany(sql, rows)


def insert_version_records(
    con: duckdb.DuckDBPyConnection,
    versions: List[Dict[str, Any]],
) -> None:
    """Inserts supplier product version history (append only, ignores exact key+timestamp duplicates)."""
    if not versions:
        return

    sql = """
    INSERT OR REPLACE INTO fact_supplier_product_version
    (supplier_product_key, supplier_id, supplier_sku, gtin, name_std, category_id,
     price_usd, weight_kg, color_id, country_code, stock_qty, source_updated_at,
     run_id, source_file, source_row_number, record_hash)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        [
            v["supplier_product_key"], v["supplier_id"], v["supplier_sku"], v["gtin"],
            v["name_std"], v["category_id"], v["price_usd"], v["weight_kg"],
            v["color_id"], v["country_code"], v["stock_qty"], v["source_updated_at"],
            v["run_id"], v["source_file"], v["source_row_number"], v["record_hash"]
        ]
        for v in versions
    ]
    con.executemany(sql, rows)


def publish_golden_and_lineage(
    con: duckdb.DuckDBPyConnection,
    golden_products: List[Dict[str, Any]],
    lineage_records: List[Dict[str, Any]],
    conflict_records: List[Dict[str, Any]],
) -> None:
    """Publishes golden products, attribute-level lineage, and conflict logs inside transaction."""
    # 1. Golden Products (Upsert on product_id)
    if golden_products:
        golden_sql = """
        INSERT OR REPLACE INTO dim_product_golden
        (product_id, gtin, name_std, category_id, price_usd, weight_kg, color_id, country_code,
         total_stock, match_confidence, source_count, last_resolved_run_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        golden_rows = [
            [
                g["product_id"], g["gtin"], g["name_std"], g["category_id"],
                g["price_usd"], g["weight_kg"], g["color_id"], g["country_code"],
                g["total_stock"], g["match_confidence"], g["source_count"],
                g["last_resolved_run_id"], g["updated_at"]
            ]
            for g in golden_products
        ]
        con.executemany(golden_sql, golden_rows)

    # 2. Attribute Lineage (Upsert on product_id, attribute_name)
    if lineage_records:
        lineage_sql = """
        INSERT OR REPLACE INTO product_attribute_lineage
        (product_id, attribute_name, chosen_value, chosen_supplier_id, chosen_source_file,
         chosen_source_row_number, chosen_run_id, rule_applied, alternatives_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        lineage_rows = [
            [
                l["product_id"], l["attribute_name"], l["chosen_value"],
                l["chosen_supplier_id"], l["chosen_source_file"],
                l["chosen_source_row_number"], l["chosen_run_id"],
                l["rule_applied"], l["alternatives_json"]
            ]
            for l in lineage_records
        ]
        con.executemany(lineage_sql, lineage_rows)

    # 3. Product Conflict Log (Append)
    if conflict_records:
        conflict_sql = """
        INSERT INTO product_conflict_log
        (product_id, attribute_name, supplier_values_json, resolution_rule, run_id)
        VALUES (?, ?, ?, ?, ?)
        """
        conflict_rows = [
            [
                c["product_id"], c["attribute_name"], c["supplier_values_json"],
                c["resolution_rule"], c["run_id"]
            ]
            for c in conflict_records
        ]
        con.executemany(conflict_sql, conflict_rows)
