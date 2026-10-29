# Data Dictionary: Supplier Feed Harmonizer Data Warehouse

This document details every table, view, and column within the DuckDB embedded data warehouse, specifying storage data types, nullability, primary/foreign keys, uniqueness constraints, derived-field calculation logic, and referential integrity guarantees.

---

## 1. Reference & Dimension Tables

### `ref_category`
Standardized product taxonomy catalog. Loaded from `config/mappings/category_map.csv`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `category_id` | `VARCHAR` | No | **PK** | Standardized category identifier (e.g. `CAT_AUDIO`, `CAT_ELECTRONICS`). |
| `category_name` | `VARCHAR` | No | - | Human-readable category title (e.g. `Audio Equipment`). |

### `ref_unit`
Unit of measure conversion factors to standard kilogram (`kg`). Loaded from `config/mappings/unit_map.csv`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `source_unit` | `VARCHAR` | No | **PK** | Raw supplier unit string (e.g. `lb`, `lbs`, `kg`, `g`, `oz`). |
| `standard_unit` | `VARCHAR` | No | - | Unified canonical unit (always `kg`). |
| `conversion_factor_to_kg` | `DOUBLE` | No | - | Multiplier to convert `source_unit` to kilograms (e.g. `0.45359237` for `lb`). |

### `ref_color`
Standardized color vocabulary. Loaded from `config/mappings/color_map.csv`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `color_id` | `VARCHAR` | No | **PK** | Standardized color key (e.g. `CLR_BLACK`, `CLR_RED`, `CLR_WHITE`). |
| `color_name` | `VARCHAR` | No | - | Canonical English color name (e.g. `Black`, `Red`, `White`). |

### `ref_currency`
Static exchange rates to US Dollar (`USD`). Loaded from `config/mappings/currency_map.csv`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `source_currency` | `VARCHAR` | No | **PK** | ISO-4217 raw currency code (e.g. `EUR`, `GBP`, `USD`, `CAD`). |
| `target_currency` | `VARCHAR` | No | - | Canonical target currency (`USD`). |
| `exchange_rate_to_usd` | `DOUBLE` | No | - | Static exchange rate multiplier (e.g. `1.08` for `EUR`). |

### `ref_country`
Country code translation to ISO 3166-1 alpha-2. Loaded from `config/mappings/country_map.csv`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `country_code` | `VARCHAR` | No | **PK** | ISO-2 uppercase country code (e.g. `US`, `DE`, `CN`, `JP`). |
| `country_name` | `VARCHAR` | No | - | Full standard country name (e.g. `United States`, `Germany`). |

### `dim_supplier`
Supplier partner profile, priorities, and trust weights. Loaded from `config/suppliers/*.yaml`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `supplier_id` | `VARCHAR` | No | **PK** | Unique supplier identifier (e.g. `SUP-A`, `SUP-B`, `SUP-C`). |
| `supplier_name` | `VARCHAR` | No | - | Supplier company name. |
| `priority_rank` | `INTEGER` | No | - | Hierarchy rank for conflict arbitration (1 = highest priority). |
| `trust_weight` | `DOUBLE` | No | - | Float weight (0.0 to 1.0) indicating catalog reliability. |

---

## 2. Staging Layer (`stg_supplier_a`, `stg_supplier_b`, `stg_supplier_c`)
Raw ingested strings preserving exact feed payloads with source-level lineage tracking.

| Column | Data Type | Nullable | Description / Origin |
|---|---|---|---|
| `supplier_sku` | `VARCHAR` | Yes | Raw supplier stock keeping unit or item ID. |
| `name_raw` | `VARCHAR` | Yes | Raw product title string. |
| `category_code_raw` | `VARCHAR` | Yes | Raw category code, path, or number. |
| `price_raw` | `VARCHAR` | Yes | Raw price as string (may have commas or currencies). |
| `weight_raw` | `VARCHAR` | Yes | Raw weight string. |
| `color_code_raw` | `VARCHAR` | Yes | Raw color code or free-text color name. |
| `updated_at_raw` | `VARCHAR` | Yes | Raw timestamp string (ISO-8601, epoch, or dd.mm.yyyy). |
| `stock_qty_raw` | `VARCHAR` | Yes | Raw inventory count or boolean flag. |
| `country_raw` | `VARCHAR` | Yes | Raw country name or code. |
| `gtin_raw` | `VARCHAR` | Yes | Raw barcode (EAN-13 / GTIN). |
| `currency_raw` | `VARCHAR` | Yes | Source currency code. |
| `weight_unit_raw` | `VARCHAR` | Yes | Source weight unit. |
| `_run_id` | `VARCHAR` | No | Pipeline execution run ID. |
| `_source_file` | `VARCHAR` | No | Name of input file containing this row. |
| `_source_row_number` | `INTEGER` | No | 1-indexed row number within the source file. |
| `_ingested_at` | `VARCHAR` | No | ISO-8601 UTC timestamp of staging write. |

---

## 3. Core Harmonized Warehouse Layer

### `fact_supplier_product_version`
Preserved historical record of every supplier product version. **Append-only**; never clobbers historical data.
**Grain:** One row per supplier SKU per distinct `source_updated_at`.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `supplier_product_key` | `VARCHAR` | No | **PK (1/2)** | `sha256(supplier_id \| supplier_sku)` |
| `supplier_id` | `VARCHAR` | No | **FK** -> `dim_supplier` | Source supplier identifier. |
| `supplier_sku` | `VARCHAR` | No | - | Supplier SKU. |
| `gtin` | `VARCHAR` | Yes | - | Verified 13-digit EAN-13 barcode, or NULL if missing. |
| `name_std` | `VARCHAR` | No | - | Trimmed, multi-space collapsed title. |
| `category_id` | `VARCHAR` | No | **FK** -> `ref_category` | Standardized category identifier. |
| `price_usd` | `DOUBLE` | No | - | Converted price in USD (`price_raw * exchange_rate`). |
| `weight_kg` | `DOUBLE` | No | - | Converted weight in kg (`weight_raw * conversion_factor`). |
| `color_id` | `VARCHAR` | No | **FK** -> `ref_color` | Standardized color code. |
| `country_code` | `VARCHAR` | No | **FK** -> `ref_country` | Standardized ISO-2 country code. |
| `stock_qty` | `INTEGER` | No | - | Available stock count. |
| `source_updated_at` | `VARCHAR` | No | **PK (2/2)** | Normalized ISO-8601 UTC timestamp from feed. |
| `run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Run ID that ingested this version. |
| `source_file` | `VARCHAR` | No | - | File name where version was found. |
| `source_row_number` | `INTEGER` | No | - | Row number within source file. |
| `record_hash` | `VARCHAR` | No | - | `sha256` of normalized business values. |

### `dim_product_golden`
Unified catalog view representing canonical real-world products.
**Grain:** One row per unified product entity.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `product_id` | `VARCHAR` | No | **PK** | `prd_` + first 16 hex of `sha256(normalized GTIN)` or `sha256(supplier_id \| brand \| name)`. |
| `gtin` | `VARCHAR` | Yes | - | Barcode (if resolved via GTIN). |
| `name_std` | `VARCHAR` | No | - | Winner from conflict rule (b) [supplier priority]. |
| `category_id` | `VARCHAR` | No | **FK** -> `ref_category` | Winner from conflict rule (b) [supplier priority]. |
| `price_usd` | `DOUBLE` | No | - | Winner from conflict rule (a) [latest `source_updated_at`]. |
| `weight_kg` | `DOUBLE` | No | - | Winner from conflict rule (c) [majority vote then priority]. |
| `color_id` | `VARCHAR` | No | **FK** -> `ref_color` | Winner from conflict rule (b) [supplier priority]. |
| `country_code` | `VARCHAR` | No | **FK** -> `ref_country` | Winner from conflict rule (b) [supplier priority]. |
| `total_stock` | `INTEGER` | No | - | Winner from conflict rule (a) [latest `source_updated_at`]. |
| `match_confidence` | `VARCHAR` | No | - | `high` (matched on GTIN) or `low` (fallback name match). |
| `source_count` | `INTEGER` | No | - | Number of distinct suppliers offering this product. |
| `last_resolved_run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Run ID of the most recent resolution. |
| `updated_at` | `VARCHAR` | No | - | ISO-8601 UTC timestamp of resolution. |

### `product_attribute_lineage`
Auditable provenance explaining why each golden attribute holds its current value.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `product_id` | `VARCHAR` | No | **PK (1/2)** | Links to `dim_product_golden.product_id`. |
| `attribute_name` | `VARCHAR` | No | **PK (2/2)** | Attribute evaluated (`price_usd`, `weight_kg`, etc.). |
| `chosen_value` | `VARCHAR` | No | - | The stringified winning value. |
| `chosen_supplier_id` | `VARCHAR` | No | **FK** -> `dim_supplier` | Winning supplier ID. |
| `chosen_source_file` | `VARCHAR` | No | - | Source file that produced the winning value. |
| `chosen_source_row_number` | `INTEGER` | No | - | Source row number of winning value. |
| `chosen_run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Pipeline run ID that processed winning value. |
| `rule_applied` | `VARCHAR` | No | - | Conflict arbitration rule (e.g. `latest_source_updated_at`, `supplier_priority`, `majority_vote`). |
| `alternatives_json` | `VARCHAR` | Yes | - | JSON serialized list of candidate values from other suppliers. |

### `product_conflict_log`
Historical audit trail of all detected cross-supplier disagreements.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `product_id` | `VARCHAR` | No | **FK** -> `dim_product_golden` | Golden product identifier. |
| `attribute_name` | `VARCHAR` | No | - | Attribute with conflicting values. |
| `supplier_values_json` | `VARCHAR` | No | - | JSON map of `{supplier_id: value}` across suppliers. |
| `resolution_rule` | `VARCHAR` | No | - | Rule used to break the conflict. |
| `run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Run ID during which conflict occurred. |

### `rejected_records`
Quarantined records failing ingestion, parsing, or business validation rules.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `reject_id` | `VARCHAR` | No | **PK** | `sha256(run_id \| source_file \| row_number)`. |
| `run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Execution run ID. |
| `supplier_id` | `VARCHAR` | No | **FK** -> `dim_supplier` | Associated supplier ID. |
| `source_file` | `VARCHAR` | No | - | Input file name. |
| `source_row_number` | `INTEGER` | No | - | 1-indexed row number where violation occurred. |
| `raw_record` | `VARCHAR` | No | - | Complete raw record string or JSON text. |
| `error_code` | `VARCHAR` | No | - | Stable rejection code (`BAD_NUMERIC`, `BAD_DATE`, `BAD_GTIN`, `REF_KEY_INVALID`, `NEGATIVE_PRICE`, `MISSING_REQUIRED`, `MALFORMED_RECORD`). |
| `error_message` | `VARCHAR` | No | - | Explanatory message of failure cause. |
| `rejected_at` | `VARCHAR` | No | - | ISO-8601 UTC timestamp of rejection. |

---

## 4. Pipeline Execution & Observability

### `pipeline_runs`
Execution summaries and status flags for each pipeline invocation.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `run_id` | `VARCHAR` | No | **PK** | `run_YYYYMMDDTHHMMSSZ_<6 hex>`. |
| `started_at` | `VARCHAR` | No | - | ISO-8601 UTC execution start timestamp. |
| `ended_at` | `VARCHAR` | Yes | - | ISO-8601 UTC execution completion timestamp. |
| `status` | `VARCHAR` | No | - | `success`, `success_with_rejects`, `partial_failure`, `failed`. |
| `input_files` | `VARCHAR` | No | - | JSON array of input filenames processed. |
| `rows_read` | `INTEGER` | No | - | Total rows read across input files. |
| `rows_valid` | `INTEGER` | No | - | Rows passing schema and business validation. |
| `rows_rejected` | `INTEGER` | No | - | Rows sent to `rejected_records`. |
| `rows_duplicate` | `INTEGER` | No | - | Exact duplicate rows dropped within run. |
| `rows_published` | `INTEGER` | No | - | Versions stored in `fact_supplier_product_version`. |
| `failure_reason` | `VARCHAR` | Yes | - | Stack trace or failure description if failed. |
| `config_hash` | `VARCHAR` | No | - | SHA256 digest of active pipeline configuration. |
| `code_version` | `VARCHAR` | No | - | Application code version (e.g. `1.0.0`). |

### `processed_files`
Tracks file content hashes to enforce idempotency and safe reruns.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `file_hash_sha256` | `VARCHAR` | No | **PK** | SHA-256 hash of entire file contents. |
| `source_file` | `VARCHAR` | No | - | Name of input file. |
| `supplier_id` | `VARCHAR` | No | **FK** -> `dim_supplier` | Target supplier identifier. |
| `first_run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Run ID that first processed this file content. |
| `status` | `VARCHAR` | No | - | `success`, `success_empty`, `failed_schema`, `failed`. |
| `rows_read` | `INTEGER` | No | - | Total rows read from file. |
| `processed_at` | `VARCHAR` | No | - | ISO-8601 UTC timestamp of processing. |

### `dq_metrics`
Time-series metrics capturing data quality and schema health over time.

| Column | Data Type | Nullable | Key / Constraint | Description / Derivation Logic |
|---|---|---|---|---|
| `run_id` | `VARCHAR` | No | **FK** -> `pipeline_runs` | Pipeline run ID. |
| `metric_name` | `VARCHAR` | No | - | Metric key (`total_rows_read`, `extra_columns_detected_count`, etc.). |
| `metric_value` | `DOUBLE` | No | - | Metric numerical value. |
| `supplier_id` | `VARCHAR` | Yes | - | Supplier ID if supplier-scoped metric. |
