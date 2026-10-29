"""
Command Line Interface and pipeline orchestrator for supplier-feed-harmonizer.
Provides subcommands:
  run     - Executes end-to-end multi-supplier feed harmonization
  report  - Generates audit reconciliation markdown and CSV reports
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from src.harmonizer.config import PipelineConfig, SupplierConfig, load_pipeline_config
from src.harmonizer.ids import compute_file_sha256, generate_run_id
from src.harmonizer.ingest import ingest_supplier_file
from src.harmonizer.logging_setup import setup_logger
from src.harmonizer.publish import (
    init_database,
    insert_rejected_records,
    insert_staging_records,
    insert_version_records,
    publish_golden_and_lineage,
)
from src.harmonizer.report import generate_reconciliation_report
from src.harmonizer.resolve import resolve_entities
from src.harmonizer.runlog import (
    check_file_already_processed,
    compute_config_hash,
    record_dq_metric,
    record_pipeline_run,
    record_processed_file,
)
from src.harmonizer.schema_check import check_file_schema
from src.harmonizer.transform import deduplicate_records, transform_and_standardize
from src.harmonizer.validate import validate_records


def match_file_to_supplier(file_name: str, suppliers: Dict[str, SupplierConfig]) -> Optional[SupplierConfig]:
    """Matches a filename to a supplier configuration based on glob patterns."""
    for s_cfg in suppliers.values():
        if fnmatch.fnmatch(file_name.lower(), s_cfg.file_pattern.lower()):
            return s_cfg
    return None


def run_pipeline(
    config_path: str = "config/pipeline.yaml",
    input_dir_override: Optional[str] = None,
    db_path_override: Optional[str] = None,
    run_id_override: Optional[str] = None,
    only_supplier: Optional[str] = None,
    dry_run: bool = False,
    injected_failure_file: Optional[str] = None,
) -> int:
    """
    Executes the 11-stage harmonization pipeline.
    Returns CLI exit code:
      0 = success (or success_with_rejects)
      1 = partial failure (one or more files failed/quarantined)
      2 = fatal failure (unhandled pipeline exception)
    """
    run_id = run_id_override or generate_run_id()
    started_at = datetime.now(timezone.utc).isoformat()

    # Load configuration
    try:
        config: PipelineConfig = load_pipeline_config(config_path)
    except Exception as e:
        print(f"Fatal error loading config from '{config_path}': {e}", file=sys.stderr)
        return 2

    # Override CLI flags
    input_dir = Path(input_dir_override or config.input_dir)
    db_path = Path(db_path_override or config.db_path)
    log_dir = Path(config.log_dir)

    logger = setup_logger(run_id, log_dir=str(log_dir), level="INFO")
    logger.info(f"Starting pipeline execution [run_id={run_id}]")
    logger.info(f"Target DuckDB database: '{db_path}' | Input directory: '{input_dir}'")

    config_hash = compute_config_hash(config.raw_config)

    if not input_dir.exists():
        logger.warning(f"Input directory '{input_dir}' does not exist. Zero files to process.")
        con = init_database(db_path, config, logger)
        ended_at = datetime.now(timezone.utc).isoformat()
        record_pipeline_run(
            con=con, run_id=run_id, started_at=started_at, ended_at=ended_at,
            status="success", input_files=[], rows_read=0, rows_valid=0,
            rows_rejected=0, rows_duplicate=0, rows_published=0, config_hash=config_hash
        )
        con.close()
        return 0

    # Initialize DuckDB tables and reference dimensions
    con = init_database(db_path, config, logger)

    # 1. Stage 1: Discover Files
    discovered_files = sorted([f for f in input_dir.iterdir() if f.is_file()])
    logger.info(f"Stage 1 (Discovery): Found {len(discovered_files)} candidate files in '{input_dir}'")

    # Run counters
    total_rows_read = 0
    total_rows_valid = 0
    total_rows_rejected = 0
    total_rows_duplicate = 0
    total_rows_published = 0
    processed_input_files: List[str] = []
    has_partial_failure = False

    # Check environment variable for injected failure (used in testing)
    fail_hook = injected_failure_file or os.getenv("INJECT_PIPELINE_FAILURE")

    for file_path in discovered_files:
        file_name = file_path.name
        supp_cfg = match_file_to_supplier(file_name, config.suppliers)

        if not supp_cfg:
            logger.warning(f"File '{file_name}' does not match any configured supplier pattern. Skipping.")
            continue

        if only_supplier and supp_cfg.supplier_id != only_supplier:
            logger.info(f"Skipping '{file_name}' (Filter only_supplier='{only_supplier}')")
            continue

        processed_input_files.append(file_name)
        file_hash = compute_file_sha256(str(file_path))

        # Check idempotency: skip if already successfully processed
        if check_file_already_processed(con, file_hash):
            logger.info(f"File '{file_name}' [hash={file_hash[:8]}...] already successfully processed. Skipping rerun.")
            continue

        logger.info(f"Processing '{file_name}' for Supplier '{supp_cfg.supplier_id}' [hash={file_hash[:8]}...]")

        # Stage 2: Schema Check
        schema_res = check_file_schema(file_path, supp_cfg, logger)

        if schema_res.status == "success_empty":
            record_processed_file(con, file_hash, file_name, supp_cfg.supplier_id, run_id, "success_empty", rows_read=0)
            logger.info(f"File '{file_name}' marked as success_empty.")
            continue

        if not schema_res.is_valid:
            # File-level quarantine
            has_partial_failure = True
            record_processed_file(con, file_hash, file_name, supp_cfg.supplier_id, run_id, "failed_schema", rows_read=0)
            record_dq_metric(con, run_id, "file_quarantine_failed_schema", 1.0, supp_cfg.supplier_id)
            logger.warning(f"File '{file_name}' quarantined under failed_schema. Pipeline continues.")
            continue

        if schema_res.extra_columns:
            record_dq_metric(con, run_id, "extra_columns_detected_count", len(schema_res.extra_columns), supp_cfg.supplier_id)

        # Stage 3: Ingest Staging Records & Malformed Lines
        try:
            staging_rows, malformed_rejects = ingest_supplier_file(file_path, supp_cfg, run_id, logger)
        except Exception as e:
            logger.error(f"Error ingesting file '{file_name}': {e}", exc_info=True)
            has_partial_failure = True
            record_processed_file(con, file_hash, file_name, supp_cfg.supplier_id, run_id, "failed", rows_read=0)
            continue

        file_rows_read = len(staging_rows) + len(malformed_rejects)
        total_rows_read += file_rows_read
        total_rows_rejected += len(malformed_rejects)

        # Stage 4: Validate Rows
        valid_rows, validation_rejects = validate_records(staging_rows, supp_cfg, config.references, run_id)
        total_rows_rejected += len(validation_rejects)
        all_rejects = malformed_rejects + validation_rejects

        # Stage 5: Deduplicate Exact Within-Run Duplicates
        deduped_rows, dup_count = deduplicate_records(valid_rows, supp_cfg, logger)
        total_rows_duplicate += dup_count
        total_rows_valid += len(deduped_rows)

        # Stage 6: Transform and Standardize
        version_records = transform_and_standardize(deduped_rows, supp_cfg, config.references, run_id)
        total_rows_published += len(version_records)

        # Injected failure simulation hook for partial-failure and rollback testing
        if fail_hook and fail_hook in file_name:
            logger.warning(f"Simulating injected failure on file '{file_name}' as requested by test hook.")
            raise RuntimeError(f"Simulated injected failure on '{file_name}'")

        if dry_run:
            logger.info(f"Dry-run enabled: skipping database publish for file '{file_name}'.")
            continue

        # Transaction per file
        try:
            con.begin()
            # 1. Staging insert
            insert_staging_records(con, supp_cfg.supplier_id, staging_rows)
            # 2. Rejects insert
            insert_rejected_records(con, all_rejects)
            # 3. Version history insert
            insert_version_records(con, version_records)
            # 4. Mark processed file success
            record_processed_file(con, file_hash, file_name, supp_cfg.supplier_id, run_id, "success", rows_read=file_rows_read)
            con.commit()
            logger.info(
                f"Successfully committed file '{file_name}': read={file_rows_read}, valid={len(deduped_rows)}, "
                f"rejected={len(all_rejects)}, duplicate={dup_count}"
            )
        except Exception as e:
            con.rollback()
            logger.error(f"Transaction rolled back for file '{file_name}' due to error: {e}", exc_info=True)
            has_partial_failure = True
            record_processed_file(con, file_hash, file_name, supp_cfg.supplier_id, run_id, "failed", rows_read=file_rows_read)

    # Stages 7 & 8: Cross-Supplier Entity & Conflict Resolution on Full Historical Fact Table
    if not dry_run and total_rows_published > 0:
        logger.info("Executing Stages 7 & 8: Entity Resolution and Attribute Conflict Resolution across suppliers...")
        # Query all active product versions from fact table to ensure complete cross-supplier resolution
        all_fact_versions = con.execute("""
            SELECT
                supplier_product_key, supplier_id, supplier_sku, gtin, name_std,
                category_id, price_usd, weight_kg, color_id, country_code,
                stock_qty, source_updated_at, run_id, source_file, source_row_number, record_hash
            FROM fact_supplier_product_version
        """).fetchall()

        cols = [
            "supplier_product_key", "supplier_id", "supplier_sku", "gtin", "name_std",
            "category_id", "price_usd", "weight_kg", "color_id", "country_code",
            "stock_qty", "source_updated_at", "run_id", "source_file", "source_row_number", "record_hash"
        ]
        version_objs = [dict(zip(cols, row)) for row in all_fact_versions]

        golden_products, lineage_records, conflict_records = resolve_entities(
            version_objs, config.suppliers, run_id, logger
        )

        # Stage 9: Publish Golden Catalog, Lineage, and Conflicts inside transaction
        con.begin()
        publish_golden_and_lineage(con, golden_products, lineage_records, conflict_records)
        con.commit()
        logger.info(f"Published {len(golden_products)} golden products, {len(lineage_records)} lineage attributes, {len(conflict_records)} conflicts.")

    # Stage 10: Record Run Metrics
    ended_at = datetime.now(timezone.utc).isoformat()
    if has_partial_failure:
        run_status = "partial_failure"
        exit_code = 1
    elif total_rows_rejected > 0:
        run_status = "success_with_rejects"
        exit_code = 0
    else:
        run_status = "success"
        exit_code = 0

    record_pipeline_run(
        con=con,
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        status=run_status,
        input_files=processed_input_files,
        rows_read=total_rows_read,
        rows_valid=total_rows_valid,
        rows_rejected=total_rows_rejected,
        rows_duplicate=total_rows_duplicate,
        rows_published=total_rows_published,
        config_hash=config_hash,
    )

    # Record summary DQ metrics
    record_dq_metric(con, run_id, "total_rows_read", total_rows_read)
    record_dq_metric(con, run_id, "total_rows_valid", total_rows_valid)
    record_dq_metric(con, run_id, "total_rows_rejected", total_rows_rejected)
    record_dq_metric(con, run_id, "total_rows_duplicate", total_rows_duplicate)

    logger.info(
        f"Pipeline finished with status='{run_status}' [exit_code={exit_code}]. "
        f"Totals: read={total_rows_read}, valid={total_rows_valid}, rejected={total_rows_rejected}, "
        f"duplicate={total_rows_duplicate}, published={total_rows_published}"
    )

    con.close()
    return exit_code


def main() -> None:
    """CLI entrypoint supporting 'run' and 'report' commands."""
    parser = argparse.ArgumentParser(
        prog="harmonizer",
        description="Supplier Feed Harmonizer - Multi-supplier feed ingestion, resolution, and lineage tracking"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Execute the feed harmonization pipeline")
    run_parser.add_argument("--config", type=str, default="config/pipeline.yaml", help="Path to pipeline.yaml")
    run_parser.add_argument("--input-dir", type=str, default=None, help="Directory containing feed input files")
    run_parser.add_argument("--db-path", type=str, default=None, help="Path to DuckDB database")
    run_parser.add_argument("--run-id", type=str, default=None, help="Explicit run ID override")
    run_parser.add_argument("--only-supplier", type=str, default=None, help="Filter to only process specified supplier ID")
    run_parser.add_argument("--dry-run", action="store_true", help="Perform ingestion and validation without persisting")

    # Command: report
    report_parser = subparsers.add_parser("report", help="Generate reconciliation and data quality report")
    report_parser.add_argument("--db-path", type=str, default="output/harmonizer.duckdb", help="Path to DuckDB warehouse")
    report_parser.add_argument("--out-markdown", type=str, default="docs/reconciliation_report.md", help="Output Markdown report path")
    report_parser.add_argument("--out-csv", type=str, default="docs/reconciliation_metrics.csv", help="Output CSV metrics path")

    args = parser.parse_args()

    if args.command == "run":
        exit_code = run_pipeline(
            config_path=args.config,
            input_dir_override=args.input_dir,
            db_path_override=args.db_path,
            run_id_override=args.run_id,
            only_supplier=args.only_supplier,
            dry_run=args.dry_run,
        )
        sys.exit(exit_code)

    elif args.command == "report":
        try:
            results = generate_reconciliation_report(
                db_path=args.db_path,
                out_markdown=args.out_markdown,
                out_csv=args.out_csv,
            )
            print(f"Reconciliation report generated: {results['markdown_report']}")
            print(f"Reconciliation metrics CSV: {results['csv_metrics']}")
            print(f"Conservation law check: {'PASS' if results['conservation_pass'] else 'FAIL'}")
            print(f"Referential integrity check: {'PASS' if results['integrity_pass'] else 'FAIL'}")
            sys.exit(0 if results["conservation_pass"] and results["integrity_pass"] else 1)
        except Exception as e:
            print(f"Error generating report: {e}", file=sys.stderr)
            sys.exit(2)

    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
