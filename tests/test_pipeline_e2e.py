"""End-to-end integration tests for supplier-feed-harmonizer pipeline."""

import json
import os
import shutil
from pathlib import Path
import duckdb
import pytest

from src.harmonizer.cli import run_pipeline
from src.harmonizer.report import generate_reconciliation_report


def test_empty_input_directory(tmp_path):
    empty_dir = tmp_path / "empty_input"
    empty_dir.mkdir()
    db_file = tmp_path / "test.duckdb"

    exit_code = run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override=str(empty_dir),
        db_path_override=str(db_file),
    )
    assert exit_code == 0
    con = duckdb.connect(str(db_file))
    runs = con.execute("SELECT status, rows_read FROM pipeline_runs").fetchall()
    assert len(runs) == 1
    assert runs[0][0] == "success"
    assert runs[0][1] == 0
    con.close()


def test_happy_path_and_ground_truth_reconciliation(tmp_path):
    db_file = tmp_path / "harmonizer.duckdb"

    # Run on committed sample data
    exit_code = run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override="sample_data/input",
        db_path_override=str(db_file),
    )
    # Status is partial_failure (exit code 1) because sample_data/input includes intentional quarantine file supplier_a_invalid_schema.csv
    assert exit_code == 1

    con = duckdb.connect(str(db_file))

    # Verify golden product count matches expected labels
    with open("sample_data/expected/labels.json", "r", encoding="utf-8") as f:
        labels = json.load(f)
    expected_golden = labels["expected_golden_products_count"]

    golden_count = con.execute("SELECT COUNT(*) FROM dim_product_golden").fetchone()[0]
    assert golden_count == expected_golden

    # Verify no duplicate product_id in golden
    dup_pids = con.execute(
        "SELECT product_id, COUNT(*) FROM dim_product_golden GROUP BY product_id HAVING COUNT(*) > 1"
    ).fetchall()
    assert len(dup_pids) == 0

    # Verify lineage exists for every golden product attribute
    orphan_lineage = con.execute("""
        SELECT COUNT(*) FROM product_attribute_lineage l
        LEFT JOIN dim_product_golden g ON l.product_id = g.product_id
        WHERE g.product_id IS NULL
    """).fetchone()[0]
    assert orphan_lineage == 0

    # Verify rejects are traceable to file and row
    untraceable_rejects = con.execute("""
        SELECT COUNT(*) FROM rejected_records
        WHERE source_file IS NULL OR source_row_number <= 0 OR error_code IS NULL
    """).fetchone()[0]
    assert untraceable_rejects == 0

    # Verify conservation law: rows_read = rows_valid + rows_rejected + rows_duplicate
    sums = con.execute("""
        SELECT SUM(rows_read), SUM(rows_valid), SUM(rows_rejected), SUM(rows_duplicate)
        FROM pipeline_runs
    """).fetchone()
    assert sums[0] == (sums[1] + sums[2] + sums[3])

    con.close()

    # Generate report and verify assertion checks
    md_report = tmp_path / "report.md"
    csv_report = tmp_path / "metrics.csv"
    res = generate_reconciliation_report(
        db_path=str(db_file),
        out_markdown=str(md_report),
        out_csv=str(csv_report),
    )
    assert res["conservation_pass"] is True
    assert res["integrity_pass"] is True


def test_idempotent_rerun(tmp_path):
    db_file = tmp_path / "idempotent.duckdb"

    # First run
    run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override="sample_data/input",
        db_path_override=str(db_file),
    )

    con = duckdb.connect(str(db_file))
    first_golden_count = con.execute("SELECT COUNT(*) FROM dim_product_golden").fetchone()[0]
    first_version_count = con.execute("SELECT COUNT(*) FROM fact_supplier_product_version").fetchone()[0]
    con.close()

    # Second run with exact same input
    exit_code_rerun = run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override="sample_data/input",
        db_path_override=str(db_file),
    )
    assert exit_code_rerun == 1  # quarantined file is still quarantined

    con = duckdb.connect(str(db_file))
    second_golden_count = con.execute("SELECT COUNT(*) FROM dim_product_golden").fetchone()[0]
    second_version_count = con.execute("SELECT COUNT(*) FROM fact_supplier_product_version").fetchone()[0]

    # Verify zero duplicate rows created
    assert second_golden_count == first_golden_count
    assert second_version_count == first_version_count

    # Second run processed 0 new rows because files were skipped
    second_run_read = con.execute("SELECT rows_read FROM pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
    assert second_run_read == 0
    con.close()


def test_modified_file_with_same_name_processed_as_new(tmp_path):
    test_input = tmp_path / "input"
    test_input.mkdir()
    db_file = tmp_path / "modified.duckdb"

    file_a = test_input / "supplier_a_feed.csv"
    headers = "sku,product_name,cat_code,price,weight_lb,color_code,updated_at,stock_qty,country,gtin\n"
    row1 = "SKU-TEST-1,Test Product 1,EL-01,10.00,1.0,BLK,2026-01-01T00:00:00Z,10,US,4006381333931\n"
    file_a.write_text(headers + row1, encoding="utf-8")

    # First run
    run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override=str(test_input),
        db_path_override=str(db_file),
    )

    con = duckdb.connect(str(db_file))
    assert con.execute("SELECT COUNT(*) FROM dim_product_golden").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM fact_supplier_product_version").fetchone()[0] == 1
    con.close()

    # Modify file content (add a second row) -> changes SHA256 hash
    row2 = "SKU-TEST-2,Test Product 2,EL-01,20.00,2.0,BLK,2026-01-01T00:00:00Z,20,US,9780201379624\n"
    file_a.write_text(headers + row1 + row2, encoding="utf-8")

    # Second run: file should NOT be skipped because hash changed
    run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override=str(test_input),
        db_path_override=str(db_file),
    )

    con = duckdb.connect(str(db_file))
    assert con.execute("SELECT COUNT(*) FROM dim_product_golden").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM fact_supplier_product_version").fetchone()[0] == 2
    con.close()


def test_out_of_order_and_late_arriving_versions(tmp_path):
    test_input = tmp_path / "input"
    test_input.mkdir()
    db_file = tmp_path / "late.duckdb"

    headers = "sku,product_name,cat_code,price,weight_lb,color_code,updated_at,stock_qty,country,gtin\n"

    # Step 1: Ingest newer record first (Price = $50.00 on 2026-01-10)
    file_newer = test_input / "supplier_a_feed.csv"
    newer_row = "SKU-LATE-1,Late Test Product,EL-01,50.00,1.0,BLK,2026-01-10T12:00:00Z,100,US,4006381333931\n"
    file_newer.write_text(headers + newer_row, encoding="utf-8")

    run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override=str(test_input),
        db_path_override=str(db_file),
    )

    con = duckdb.connect(str(db_file))
    g_price1 = con.execute("SELECT price_usd FROM dim_product_golden WHERE gtin = '4006381333931'").fetchone()[0]
    assert g_price1 == 50.00
    con.close()

    # Step 2: An older version arrives later (Price = $999.00 on 2025-12-01)
    file_older = test_input / "supplier_a_older_late.csv"
    older_row = "SKU-LATE-1,Late Test Product,EL-01,999.00,1.0,BLK,2025-12-01T12:00:00Z,50,US,4006381333931\n"
    file_older.write_text(headers + older_row, encoding="utf-8")

    run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override=str(test_input),
        db_path_override=str(db_file),
    )

    con = duckdb.connect(str(db_file))
    # Golden price MUST remain 50.00 (the newer version) - older late-arriving data does NOT clobber newer golden values
    g_price2 = con.execute("SELECT price_usd FROM dim_product_golden WHERE gtin = '4006381333931'").fetchone()[0]
    assert g_price2 == 50.00

    # Fact table MUST contain BOTH versions in history
    versions = con.execute(
        "SELECT price_usd, source_updated_at FROM fact_supplier_product_version WHERE gtin = '4006381333931' ORDER BY source_updated_at"
    ).fetchall()
    assert len(versions) == 2
    assert versions[0][0] == 999.00  # older version preserved in history
    assert versions[1][0] == 50.00   # newer version preserved in history
    con.close()


def test_partial_failure_rollback_and_retry(tmp_path):
    test_input = tmp_path / "input"
    test_input.mkdir()
    db_file = tmp_path / "fail_retry.duckdb"

    headers = "sku,product_name,cat_code,price,weight_lb,color_code,updated_at,stock_qty,country,gtin\n"
    file_a = test_input / "supplier_a_part1.csv"
    file_a.write_text(headers + "SKU-1,Prod 1,EL-01,10.00,1.0,BLK,2026-01-01T00:00:00Z,10,US,4006381333931\n", encoding="utf-8")

    file_b = test_input / "supplier_a_part2_fail.csv"
    file_b.write_text(headers + "SKU-2,Prod 2,EL-01,20.00,2.0,BLK,2026-01-01T00:00:00Z,20,US,9780201379624\n", encoding="utf-8")

    # First run: Inject failure on file_b
    with pytest.raises(RuntimeError):
        run_pipeline(
            config_path="config/pipeline.yaml",
            input_dir_override=str(test_input),
            db_path_override=str(db_file),
            injected_failure_file="fail",
        )

    con = duckdb.connect(str(db_file))
    # file_a should have been committed
    assert con.execute("SELECT COUNT(*) FROM processed_files WHERE status = 'success'").fetchone()[0] == 1
    # file_b should NOT be marked success
    assert con.execute("SELECT COUNT(*) FROM processed_files WHERE source_file LIKE '%fail%'").fetchone()[0] == 0
    con.close()

    # Second run without injected failure: should process file_b and skip file_a
    exit_code = run_pipeline(
        config_path="config/pipeline.yaml",
        input_dir_override=str(test_input),
        db_path_override=str(db_file),
        injected_failure_file=None,
    )
    assert exit_code == 0

    con = duckdb.connect(str(db_file))
    # Both files now successfully processed
    assert con.execute("SELECT COUNT(*) FROM processed_files WHERE status = 'success'").fetchone()[0] == 2
    # Exactly 2 golden products, no duplicates
    assert con.execute("SELECT COUNT(*) FROM dim_product_golden").fetchone()[0] == 2
    con.close()
