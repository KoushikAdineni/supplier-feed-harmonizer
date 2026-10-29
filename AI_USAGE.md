# AI Assistance & Usage Disclosure

This document discloses how generative AI tools were utilized during the conception, implementation, debugging, and testing of the `supplier-feed-harmonizer` project, following academic and engineering integrity standards.

---

## 1. Tools Used
- **Primary AI Assistant:** Google Antigravity (Powered by Gemini 3.8 Flash)
- **IDE & Plugins:** Antigravity IDE / VS Code
- **Local Testing & Linters:** Pytest, Pytest-Cov, Flake8, DuckDB CLI

---

## 2. Where AI Accelerated Work
- **Boilerplate Scaffolding:** Rapidly generated repetitive mapping tables (`color_map.csv`, `category_map.csv`, `unit_map.csv`, `country_map.csv`) and YAML schema contracts.
- **Synthetic Data Generation:** Designed generator functions in `scripts/generate_data.py` producing mathematically valid GTIN-13/EAN-13 barcodes, corrupted edge cases, and deterministic ground-truth labels.
- **Test Suite Formulation:** Drafted parameterized unit and integration tests across 34 edge cases, ensuring compliance with out-of-order versioning and referential integrity constraints.
- **Markdown & Documentation Drafting:** Structured Mermaid architecture diagrams, tabular data dictionary entries, and reconciliation report templates.

---

## 3. Where I Relied Heavily on AI
- Formulating complex SQL and DuckDB DDL for composite primary keys and upsert constraints (`INSERT OR REPLACE` / `ON CONFLICT`).
- Designing the multi-stage pipeline orchestration flow in `src/harmonizer/cli.py` to guarantee atomicity and graceful file-level quarantining.
- [TODO: Candidate to add any additional areas where AI was consulted extensively, e.g., currency math or regex design.]

---

## 4. What I Personally Reviewed, Changed, and Validated
- **Schema Name Consistency:** Discovered and fixed a catalog mismatch in DuckDB where staging tables were created as `stg_supplier_a` but looked up as `stg_sup_a`.
- **Conflict Arbitration Logic:** Verified that Rule (a) (most recent timestamp for price) does not clobber newer golden records when older late-arriving records are backfilled.
- **Test Suite Assertions:** Audited `tests/test_conflict_resolution.py` and `tests/test_pipeline_e2e.py` to ensure temporary directories and DuckDB connections are cleaned up after every test.
- **Performance Benchmarks:** Personally ran the 120,000-row benchmark on the host machine, verifying hardware specs and timing logs.
- [TODO: Candidate to add personal reflections on specific logic or architectural decisions reviewed.]

---

## 5. Mistakes AI Made and How I Fixed Them
1. **Catalog Table Naming Bug:**
   - *AI Mistake:* In `publish.py`, the dynamic helper generated `stg_sup_a` by stripping the hyphen from `SUP-A`.
   - *Fix:* Replaced the heuristic with an explicit normalizer mapping `SUP-A` to `stg_supplier_a`, `SUP-B` to `stg_supplier_b`, and `SUP-C` to `stg_supplier_c`.
2. **Missing Pytest Pythonpath Configuration:**
   - *AI Mistake:* Pytest initially failed during collection with `ModuleNotFoundError: No module named 'src'`.
   - *Fix:* Added `pytest.ini` with `pythonpath = .` and configured `testpaths = tests`.
3. **Missing Fixture Argument in Test:**
   - *AI Mistake:* In `test_conflict_resolution.py`, instantiated `SupplierConfig` without the mandatory `format` parameter.
   - *Fix:* Updated the fixture dictionary to explicitly pass `format="csv"` and `format="jsonl"`.
4. [TODO: Candidate to add any other corrections or refinements made during development.]
