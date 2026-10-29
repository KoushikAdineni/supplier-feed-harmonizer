"""
Schema validation stage for supplier-feed-harmonizer.
Validates input file schemas against supplier contracts prior to staging ingestion.
Enforces quarantine rules and handles empty/header-only files cleanly.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.harmonizer.config import SupplierConfig


@dataclass
class SchemaCheckResult:
    is_valid: bool
    status: str  # "valid", "failed_schema", "success_empty"
    file_path: str
    supplier_id: str
    missing_columns: List[str] = field(default_factory=list)
    extra_columns: List[str] = field(default_factory=list)
    detected_columns: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    data_row_count_estimate: int = 0


def check_file_schema(
    file_path: str | Path,
    supplier_cfg: SupplierConfig,
    logger: Optional[logging.Logger] = None,
) -> SchemaCheckResult:
    """
    Checks whether a supplier feed conforms to the contract defined in supplier_cfg.
    - Empty file (0 bytes) -> success_empty
    - Header-only file -> success_empty
    - Missing required columns -> failed_schema (quarantined)
    - Extra columns -> valid (warning logged)
    """
    path = Path(file_path)
    file_name = path.name

    # 1. Check for 0 bytes file
    if path.stat().st_size == 0:
        if logger:
            logger.info(f"File '{file_name}' is empty (0 bytes). Marking as success_empty.")
        return SchemaCheckResult(
            is_valid=True,
            status="success_empty",
            file_path=str(path),
            supplier_id=supplier_cfg.supplier_id,
            error_message="Empty file (0 bytes)",
            data_row_count_estimate=0,
        )

    # 2. Inspect CSV format
    if supplier_cfg.format.lower() == "csv":
        detected_cols: List[str] = []
        data_rows = 0
        try:
            with open(path, "r", encoding=supplier_cfg.encoding, errors="replace") as f:
                reader = csv.reader(f, delimiter=supplier_cfg.delimiter)
                try:
                    header = next(reader)
                    detected_cols = [c.strip() for c in header]
                except StopIteration:
                    # Empty file
                    return SchemaCheckResult(
                        is_valid=True,
                        status="success_empty",
                        file_path=str(path),
                        supplier_id=supplier_cfg.supplier_id,
                        error_message="Header-only or empty file",
                        data_row_count_estimate=0,
                    )

                # Check if there is at least one data row
                for _ in reader:
                    data_rows += 1
                    break
        except Exception as e:
            if logger:
                logger.error(f"Error reading header of file '{file_name}': {e}")
            return SchemaCheckResult(
                is_valid=False,
                status="failed_schema",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                error_message=f"Failed to read CSV header: {e}",
            )

        if data_rows == 0:
            if logger:
                logger.info(f"File '{file_name}' contains header only (0 data rows). Marking as success_empty.")
            return SchemaCheckResult(
                is_valid=True,
                status="success_empty",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                detected_columns=detected_cols,
                error_message="Header-only file (0 data rows)",
                data_row_count_estimate=0,
            )

        # Check required columns
        req_set = set(supplier_cfg.required_columns)
        det_set = set(detected_cols)
        missing = sorted(list(req_set - det_set))
        allowed_set = req_set.union(set(supplier_cfg.optional_columns))
        extra = sorted(list(det_set - allowed_set))

        if missing:
            msg = f"Quarantine file '{file_name}': Missing required contract columns: {missing}"
            if logger:
                logger.warning(msg)
            return SchemaCheckResult(
                is_valid=False,
                status="failed_schema",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                missing_columns=missing,
                extra_columns=extra,
                detected_columns=detected_cols,
                error_message=msg,
            )

        if extra and logger:
            logger.warning(f"File '{file_name}' contains extra unknown columns: {extra}. Will ignore them.")

        return SchemaCheckResult(
            is_valid=True,
            status="valid",
            file_path=str(path),
            supplier_id=supplier_cfg.supplier_id,
            missing_columns=[],
            extra_columns=extra,
            detected_columns=detected_cols,
            data_row_count_estimate=data_rows,
        )

    # 3. Inspect JSON Lines format
    elif supplier_cfg.format.lower() == "jsonl":
        detected_keys: Set[str] = set()
        first_valid_row = None
        has_lines = False
        try:
            with open(path, "r", encoding=supplier_cfg.encoding, errors="replace") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    has_lines = True
                    try:
                        obj = json.loads(line_str)
                        if isinstance(obj, dict):
                            first_valid_row = obj
                            detected_keys = set(obj.keys())
                            break
                    except Exception:
                        continue
        except Exception as e:
            if logger:
                logger.error(f"Error reading JSONL file '{file_name}': {e}")
            return SchemaCheckResult(
                is_valid=False,
                status="failed_schema",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                error_message=f"Failed to read JSONL file: {e}",
            )

        if not has_lines:
            return SchemaCheckResult(
                is_valid=True,
                status="success_empty",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                error_message="Empty JSONL file",
                data_row_count_estimate=0,
            )

        if first_valid_row is None:
            # File has lines but none could be parsed into JSON dict
            return SchemaCheckResult(
                is_valid=False,
                status="failed_schema",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                error_message="No valid JSON lines found in file",
            )

        req_set = set(supplier_cfg.required_columns)
        missing = sorted(list(req_set - detected_keys))
        allowed_set = req_set.union(set(supplier_cfg.optional_columns))
        extra = sorted(list(detected_keys - allowed_set))

        if missing:
            msg = f"Quarantine file '{file_name}': Missing required JSON fields: {missing}"
            if logger:
                logger.warning(msg)
            return SchemaCheckResult(
                is_valid=False,
                status="failed_schema",
                file_path=str(path),
                supplier_id=supplier_cfg.supplier_id,
                missing_columns=missing,
                extra_columns=extra,
                detected_columns=sorted(list(detected_keys)),
                error_message=msg,
            )

        if extra and logger:
            logger.warning(f"File '{file_name}' contains extra unknown JSON fields: {extra}. Will ignore them.")

        return SchemaCheckResult(
            is_valid=True,
            status="valid",
            file_path=str(path),
            supplier_id=supplier_cfg.supplier_id,
            missing_columns=[],
            extra_columns=extra,
            detected_columns=sorted(list(detected_keys)),
            data_row_count_estimate=1,
        )

    # Unknown format
    return SchemaCheckResult(
        is_valid=False,
        status="failed_schema",
        file_path=str(path),
        supplier_id=supplier_cfg.supplier_id,
        error_message=f"Unsupported format '{supplier_cfg.format}'",
    )
