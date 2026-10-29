# System Architecture: Supplier Feed Harmonizer

## 1. High-Level Architecture Overview

The `supplier-feed-harmonizer` pipeline processes disparate, heterogeneous supplier feeds (CSV, JSON Lines, ISO-8859-1 semicolon-separated files) into a standardized, unified golden catalog inside an embedded DuckDB database. The architecture is built around two core pillars: **absolute source-level traceability** (every single golden attribute links directly to its source file, row, and run) and **idempotent transactional processing**.

```mermaid
flowchart TD
    subgraph Producers ["Feed Producers (External Suppliers)"]
        A["Supplier A (CSV, UTF-8, Comma, lb, USD)"]
        B["Supplier B (JSON Lines, UTF-8, kg, USD)"]
        C["Supplier C (CSV, ISO-8859-1, Semicolon, EUR)"]
    end

    subgraph Orchestration ["Pipeline Orchestration & Storage Layer"]
        subgraph Stage1to3 ["Ingestion & Quarantine"]
            S1["Stage 1: File Discovery & SHA256 Hashing"]
            S2["Stage 2: Schema Contract Check"]
            S3["Stage 3: Staging Ingestion & Line Traceability"]
            Q["Quarantined Files (failed_schema)"]
        end

        subgraph Stage4to6 ["Data Quality & Standardization"]
            S4["Stage 4: Row Validation & Checksums"]
            S5["Stage 5: Deduplication (Same Key + Hash)"]
            S6["Stage 6: Currency (USD), Unit (kg) & Taxonomy Standardize"]
            R["rejected_records (Audit & Traceability)"]
        end

        subgraph Stage7to9 ["Resolution & Persistence (DuckDB)"]
            S7["Stage 7: Entity Resolution (GTIN-13 / Fallback)"]
            S8["Stage 8: Deterministic Conflict Resolution (Rules a-d)"]
            S9["Stage 9: Transactional Upsert & Lineage Attribution"]
        end
    end

    subgraph Storage ["DuckDB Embedded Data Warehouse"]
        T_STG["stg_supplier_a / b / c"]
        T_FACT["fact_supplier_product_version (Append-Only History)"]
        T_GOLD["dim_product_golden (Single Grain per Product)"]
        T_LIN["product_attribute_lineage (Traceability)"]
        T_CONF["product_conflict_log (Conflict Audits)"]
        T_RUNS["pipeline_runs & dq_metrics"]
    end

    subgraph Consumers ["Analytical Consumers & Operations"]
        REP["Audit & Reconciliation Report (Markdown / CSV)"]
        CLI["Pipeline Operator (Retry / Restart / Backfill)"]
        SQL["Downstream Analytics (Pricing, Stock, Catalog BI)"]
    end

    A --> S1
    B --> S1
    C --> S1
    S1 --> S2
    S2 -- "Contract Mismatch" --> Q
    S2 -- "Conforming Schema" --> S3
    S3 --> T_STG
    S3 -- "Malformed Lines" --> R
    S3 --> S4
    S4 -- "Invalid Rules / Barcodes" --> R
    S4 --> S5
    S5 --> S6
    S6 --> T_FACT
    T_FACT --> S7
    S7 --> S8
    S8 --> T_CONF
    S8 --> S9
    S9 --> T_GOLD
    S9 --> T_LIN
    S9 --> T_RUNS

    T_GOLD --> SQL
    T_LIN --> REP
    T_RUNS --> CLI
```

---

## 2. Pipeline Actors

1. **Data Engineer**: Maintains pipeline code, YAML contracts, taxonomy reference tables, and reconciliation assertion logic.
2. **Supplier File Producers**: Upstream external partners publishing catalog feeds in diverse encodings, formats, and schedules without central coordination.
3. **Storage & Processing Layer (DuckDB)**: Embedded, high-performance columnar engine maintaining ACID transactions, staging tables, immutable version history, and golden catalog views.
4. **Analytical Consumer**: BI analysts, pricing algorithms, and ERP systems querying unified catalog attributes with guaranteed referential integrity.
5. **Pipeline Operator**: Monitors runs, investigates `rejected_records` and `pipeline_runs`, and triggers retries, restarts, or backfills via the CLI.

---

## 3. Data Flow & Transaction Boundaries

Each feed file undergoes transactional boundary protection:
1. **Pre-Ingest Hashing**: Files are hashed (`SHA-256`). If already recorded as `success` in `processed_files`, the file is safely skipped.
2. **Batch Transaction**: Ingestion into `stg_*`, `rejected_records`, and `fact_supplier_product_version` executes inside a single atomic DuckDB transaction (`con.begin()` ... `con.commit()`).
3. **Rollback Guarantee**: Any unhandled exception aborts the file batch (`con.rollback()`), preventing partial data contamination. `processed_files` is only marked `success` after a successful commit.
4. **Cross-Supplier Entity Resolution**: Considers all current versions across suppliers, deterministically arbitrates conflicting values, updates `dim_product_golden`, and records lineage per attribute.
