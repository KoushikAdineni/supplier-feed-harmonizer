# Design Notes & Architectural Trade-Offs

## 1. Why DuckDB?
- **Zero-Dependency Local Embedded Warehouse**: Traditional multi-feed ETL pipelines often rely on PostgreSQL, SQLite, or distributed engines like Apache Spark. PostgreSQL requires a local daemon or Docker container; SQLite lacks robust concurrent analytical SQL, rich date handling, and high-performance columnar execution.
- **Columnar Analytical Power**: DuckDB provides vectorized SIMD query execution, columnar storage, and fast `executemany` batched array insertion. It handles datasets from 100 to 1,000,000+ rows in milliseconds directly on a laptop with zero network serialization overhead.
- **ACID Transaction Guarantees**: Per-file transaction boundaries (`BEGIN TRANSACTION` ... `COMMIT` / `ROLLBACK`) ensure that failures never corrupt the warehouse.

---

## 2. Entity Resolution: Primary Barcode (GTIN-13) vs Fallback
- **Universal Primary Key**: Modern e-commerce and retail ecosystems depend on GTIN/EAN-13 barcodes as universal product identifiers. Matching on GTIN avoids ambiguous string similarity matching errors across languages and formatting conventions.
- **Brand + Normalized Name Fallback**: When GTIN is absent (e.g. unbranded or proprietary SKUs), we fall back to normalized brand and trimmed, space-collapsed title matching.
- **Explicit Confidence Flag**: Golden products record `match_confidence: 'high'` (for GTIN matches) or `'low'` (for brand/title fallback). Downstream pricing models and merchant dashboards can filter or prioritize high-confidence items.

---

## 3. Conflict Resolution Strategy
Catalog feeds inevitably disagree on prices, weights, names, and attributes. Rather than naive "last writer wins" overwrites, we apply domain-tailored deterministic rules:
- **Price and Stock (`latest_source_updated_at`)**: E-commerce pricing and inventory levels fluctuate rapidly. The most recent valid timestamp represents current commercial truth.
- **Name, Category, Color, Country (`supplier_priority`)**: Content attributes are governed by curated catalog trust. Supplier A (primary authorized distributor, rank 1) overrides Supplier B (rank 2) and Supplier C (rank 3).
- **Weight (`majority_vote_then_priority`)**: Physical package weight is an objective measurement. When suppliers report differing values (e.g. 0.5 kg vs 0.52 kg), the majority consensus among suppliers is selected, with ties broken by supplier priority rank.
- **Non-Null Invariance (`null never overrides non-null`)**: Incomplete supplier feeds with missing attributes cannot erase valid existing data.

---

## 4. History vs Overwrite (`fact_supplier_product_version` vs `dim_product_golden`)
- **Immutable Version History**: `fact_supplier_product_version` maintains the full chronological record of every SKU update received across all feeds. Late-arriving and historical feeds are inserted into their proper chronological position and never overwrite or clobber newer data.
- **Single-Grain Golden Catalog**: `dim_product_golden` maintains exactly one row per real-world product, representing the currently resolved state.
- **Traceability via `product_attribute_lineage`**: Rather than opaque golden values, every single attribute records its winning supplier ID, source file, row number, run ID, and competing alternatives.

---

## 5. Deliberately Left Out (Scope & Simplicity)
- **No Heavy Distributed Frameworks (Airflow, Celery, Spark)**: For single-machine local feeds, heavyweight orchestrators introduce container overhead, JVM memory bloat, and operational complexity. Standard library modular Python + DuckDB provides a clean, maintainable architecture.
- **No Cloud Secrets or External APIs**: Dynamic currency conversion uses a committed reference rates table (`currency_map.csv`), ensuring tests and pipelines run completely offline without API rate limits or network failures.
- **No Lossy Probabilistic Matching**: Fuzzy Levenshtein or embedding-based vector clustering without human review leads to catastrophic SKU merges (e.g. merging iPhone 13 with iPhone 14). Strict GTIN with deterministic fallback was chosen for correctness and auditable explainability.

---

## 6. Requirement Deviations & Assumptions
- **Assumption on Decimal Separators**: Supplier C uses German formatting with comma decimals (e.g. `199,99`). The pipeline handles both dot and comma decimals dynamically based on supplier configuration contracts.
- **Assumption on Empty / Header-Only Files**: Empty (0 bytes) and header-only (0 data rows) files are treated as normal operational conditions and marked `success_empty`, logging zero rows read without triggering pipeline failures.
