"""
Staging ingestion module for supplier-feed-harmonizer.
Extracts supplier feeds into uniform raw staging rows while attaching source-level
traceability metadata (_run_id, _source_file, _source_row_number, _ingested_at)
and intercepting malformed file lines into rejected_records.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.harmonizer.config import SupplierConfig
from src.harmonizer.ids import generate_reject_id


def extract_nested_value(data: Dict[str, Any], path: str) -> Optional[str]:
    """Retrieve dotted-path nested property from dict as string (e.g. 'unit_price.amount')."""
    parts = path.split(".")
    curr = data
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return None
    return str(curr) if curr is not None else None


def ingest_supplier_file(
    file_path: str | Path,
    supplier_cfg: SupplierConfig,
    run_id: str,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Ingests a single file into raw staging records and line-level malformed rejects.
    Returns:
        (staging_records, malformed_rejects)
    """
    path = Path(file_path)
    file_name = path.name
    now_utc = datetime.now(timezone.utc).isoformat()

    staging_records: List[Dict[str, Any]] = []
    reject_records: List[Dict[str, Any]] = []

    # 1. CSV Processing
    if supplier_cfg.format.lower() == "csv":
        try:
            with open(path, "r", encoding=supplier_cfg.encoding, errors="replace") as f:
                reader = csv.reader(f, delimiter=supplier_cfg.delimiter)
                try:
                    headers = next(reader)
                    clean_headers = [h.strip() for h in headers]
                except StopIteration:
                    return [], []

                for row_idx, row in enumerate(reader, start=2):  # 1-indexed, line 1 is header
                    raw_line_repr = supplier_cfg.delimiter.join(row)

                    # Check for column length mismatch against header
                    if len(row) != len(clean_headers):
                        rej_id = generate_reject_id(run_id, file_name, row_idx)
                        reject_records.append({
                            "reject_id": rej_id,
                            "run_id": run_id,
                            "supplier_id": supplier_cfg.supplier_id,
                            "source_file": file_name,
                            "source_row_number": row_idx,
                            "raw_record": raw_line_repr,
                            "error_code": "MALFORMED_RECORD",
                            "error_message": f"Expected {len(clean_headers)} columns but found {len(row)}",
                            "rejected_at": now_utc,
                        })
                        continue

                    # Build row dictionary
                    row_dict = {clean_headers[i]: row[i].strip() for i in range(len(clean_headers))}

                    # Map columns according to contract
                    mapped_record: Dict[str, Any] = {
                        "_run_id": run_id,
                        "_source_file": file_name,
                        "_source_row_number": row_idx,
                        "_ingested_at": now_utc,
                        "supplier_id": supplier_cfg.supplier_id,
                        "currency_raw": supplier_cfg.default_currency,
                        "weight_unit_raw": supplier_cfg.default_weight_unit,
                    }

                    for contract_col, canonical_key in supplier_cfg.column_mapping.items():
                        mapped_record[canonical_key] = row_dict.get(contract_col, "")

                    staging_records.append(mapped_record)

        except Exception as e:
            if logger:
                logger.error(f"Unhandled file read failure on '{file_name}': {e}", exc_info=True)
            raise

    # 2. JSON Lines Processing
    elif supplier_cfg.format.lower() == "jsonl":
        with open(path, "r", encoding=supplier_cfg.encoding, errors="replace") as f:
            for line_idx, line in enumerate(f, start=1):
                raw_str = line.strip()
                if not raw_str:
                    continue

                try:
                    data = json.loads(raw_str)
                    if not isinstance(data, dict):
                        raise ValueError("JSON line root is not an object")
                except Exception as e:
                    rej_id = generate_reject_id(run_id, file_name, line_idx)
                    reject_records.append({
                        "reject_id": rej_id,
                        "run_id": run_id,
                        "supplier_id": supplier_cfg.supplier_id,
                        "source_file": file_name,
                        "source_row_number": line_idx,
                        "raw_record": raw_str,
                        "error_code": "MALFORMED_RECORD",
                        "error_message": f"JSON parse error: {str(e)}",
                        "rejected_at": now_utc,
                    })
                    continue

                mapped_record = {
                    "_run_id": run_id,
                    "_source_file": file_name,
                    "_source_row_number": line_idx,
                    "_ingested_at": now_utc,
                    "supplier_id": supplier_cfg.supplier_id,
                    "currency_raw": supplier_cfg.default_currency,
                    "weight_unit_raw": supplier_cfg.default_weight_unit,
                }

                for contract_col, canonical_key in supplier_cfg.column_mapping.items():
                    if "." in contract_col:
                        val = extract_nested_value(data, contract_col)
                    else:
                        val = str(data[contract_col]) if contract_col in data and data[contract_col] is not None else ""
                    mapped_record[canonical_key] = val if val is not None else ""

                staging_records.append(mapped_record)

    return staging_records, reject_records
