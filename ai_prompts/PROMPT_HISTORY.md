# AI Prompt History

This file logs the engineering directives and design prompts used during the development of `supplier-feed-harmonizer`.

## Prompt 1: Initial Architecture & Specification
```text
Build a complete, tested, locally runnable vertical slice for supplier-feed-harmonizer.
Combine product feeds from multiple suppliers that have different schemas and code systems.
Standardize attributes, resolve conflicts between suppliers, and expose source-level traceability.
Tech Stack: Python 3.11+, DuckDB (embedded, file-based warehouse), pandas only where convenient,
PyYAML for config, pytest, argparse CLI. No cloud services, no secrets, no API keys.
```

## Prompt 2: Schema Contract, Ingestion, and Quarantine
```text
Implement schema validation against YAML contracts:
- Supplier A: CSV UTF-8 comma (sku, product_name, cat_code, price, weight_lb, color_code, updated_at, stock_qty, country, gtin)
- Supplier B: JSON Lines (item_id, title, category, unit_price, weight, colour, last_modified, available, origin_country, gtin)
- Supplier C: CSV ISO-8859-1 semicolon decimal comma (art_nr, bezeichnung, warengruppe, preis_eur, gewicht_kg, farbe, stand, lager, herkunft, gtin)
Quarantine invalid schema files (failed_schema) while continuing pipeline on valid files.
Route malformed lines and bad records to rejected_records with error codes and source traceability.
```

## Prompt 3: Deterministic Entity & Conflict Resolution
```text
Resolve cross-supplier products by GTIN-13 barcode, fallback to brand/name.
Arbitrate conflicting attributes:
(a) Most recent valid source_updated_at wins for price and stock
(b) Supplier priority rank wins for name, category, color, country
(c) Weight uses majority vote among suppliers, tie broken by priority
(d) Null never overrides a non-null
Track lineage for every golden attribute and log every conflict.
```

## Prompt 4: Testing, Performance, and Reconciliation
```text
Create pytest suite covering all 26 edge cases. Save test output to docs/test_evidence.txt.
Create benchmark script processing 120,000+ rows and outputting docs/performance.md.
Generate automated reconciliation report docs/reconciliation_report.md verifying conservation
rows_read = rows_valid + rows_rejected + rows_duplicate.
```
