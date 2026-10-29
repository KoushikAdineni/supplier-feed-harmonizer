"""
Run metrics and observability tracking module for supplier-feed-harmonizer.
Records execution summaries in pipeline_runs, tracks file processing state in processed_files,
and captures data quality indicators in dq_metrics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import duckdb


def record_pipeline_run(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    started_at: str,
    ended_at: str,
    status: str,
    input_files: List[str],
    rows_read: int,
    rows_valid: int,
    rows_rejected: int,
    rows_duplicate: int,
    rows_published: int,
    config_hash: str,
    code_version: str = "1.0.0",
    failure_reason: Optional[str] = None,
) -> None:
    """Inserts or updates execution summary in pipeline_runs."""
    sql = """
    INSERT OR REPLACE INTO pipeline_runs
    (run_id, started_at, ended_at, status, input_files, rows_read, rows_valid,
     rows_rejected, rows_duplicate, rows_published, failure_reason, config_hash, code_version)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    con.execute(sql, [
        run_id, started_at, ended_at, status, json.dumps(input_files),
        rows_read, rows_valid, rows_rejected, rows_duplicate, rows_published,
        failure_reason, config_hash, code_version
    ])


def record_processed_file(
    con: duckdb.DuckDBPyConnection,
    file_hash_sha256: str,
    source_file: str,
    supplier_id: str,
    run_id: str,
    status: str,
    rows_read: int = 0,
) -> None:
    """Updates processed_files table with file state and status."""
    now_utc = datetime.now(timezone.utc).isoformat()
    sql = """
    INSERT OR REPLACE INTO processed_files
    (file_hash_sha256, source_file, supplier_id, first_run_id, status, rows_read, processed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    con.execute(sql, [
        file_hash_sha256, source_file, supplier_id, run_id, status, rows_read, now_utc
    ])


def record_dq_metric(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    metric_name: str,
    metric_value: float,
    supplier_id: Optional[str] = None,
) -> None:
    """Appends data quality measurement to dq_metrics."""
    sql = """
    INSERT INTO dq_metrics (run_id, metric_name, metric_value, supplier_id)
    VALUES (?, ?, ?, ?)
    """
    con.execute(sql, [run_id, metric_name, float(metric_value), supplier_id])


def check_file_already_processed(
    con: duckdb.DuckDBPyConnection,
    file_hash_sha256: str,
) -> bool:
    """Returns True if the file content hash has already been successfully processed."""
    res = con.execute(
        "SELECT status FROM processed_files WHERE file_hash_sha256 = ?",
        [file_hash_sha256]
    ).fetchone()
    if res and res[0] in ("success", "success_empty"):
        return True
    return False


def compute_config_hash(raw_config: Dict[str, Any]) -> str:
    """Produces SHA256 digest of normalized config dictionary."""
    content = json.dumps(raw_config, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
