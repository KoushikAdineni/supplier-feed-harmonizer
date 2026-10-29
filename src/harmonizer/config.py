"""
Configuration loader and validator for supplier-feed-harmonizer.
Loads pipeline settings, supplier contracts, and reference lookup tables.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class SupplierConfig:
    supplier_id: str
    supplier_name: str
    priority_rank: int
    trust_weight: float
    file_pattern: str
    format: str
    encoding: str = "utf-8"
    delimiter: str = ","
    decimal_separator: str = "."
    required_columns: List[str] = field(default_factory=list)
    optional_columns: List[str] = field(default_factory=list)
    column_mapping: Dict[str, str] = field(default_factory=dict)
    default_currency: str = "USD"
    default_weight_unit: str = "kg"
    date_format: str = "iso8601"


@dataclass
class ReferenceMaps:
    category_map: Dict[str, Dict[str, str]] = field(default_factory=dict)  # raw_cat -> {category_id, category_name}
    unit_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)       # raw_unit -> {standard_unit, factor}
    color_map: Dict[str, Dict[str, str]] = field(default_factory=dict)      # raw_color -> {color_id, color_name}
    currency_map: Dict[str, float] = field(default_factory=dict)            # raw_curr -> rate_to_usd
    country_map: Dict[str, Dict[str, str]] = field(default_factory=dict)    # raw_country -> {country_code, country_name}


@dataclass
class PipelineConfig:
    name: str = "supplier-feed-harmonizer"
    version: str = "1.0.0"
    db_path: str = "output/harmonizer.duckdb"
    input_dir: str = "sample_data/input"
    mappings_dir: str = "config/mappings"
    suppliers_dir: str = "config/suppliers"
    output_dir: str = "output"
    log_dir: str = "logs"
    conflict_resolution: Dict[str, str] = field(default_factory=dict)
    entity_resolution: Dict[str, str] = field(default_factory=dict)
    suppliers: Dict[str, SupplierConfig] = field(default_factory=dict)
    references: ReferenceMaps = field(default_factory=ReferenceMaps)
    raw_config: Dict[str, Any] = field(default_factory=dict)


def load_reference_maps(mappings_dir: str | Path) -> ReferenceMaps:
    """Loads reference CSV tables into memory for rapid row-level validation and standardization."""
    maps_path = Path(mappings_dir)
    ref = ReferenceMaps()

    # 1. Category Map
    cat_file = maps_path / "category_map.csv"
    if cat_file.exists():
        with open(cat_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = row["source_category"].strip().lower()
                ref.category_map[src] = {
                    "category_id": row["category_id"].strip(),
                    "category_name": row["category_name"].strip(),
                }

    # 2. Unit Map
    unit_file = maps_path / "unit_map.csv"
    if unit_file.exists():
        with open(unit_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = row["source_unit"].strip().lower()
                ref.unit_map[src] = {
                    "standard_unit": row["standard_unit"].strip(),
                    "conversion_factor_to_kg": float(row["conversion_factor_to_kg"]),
                }

    # 3. Color Map
    color_file = maps_path / "color_map.csv"
    if color_file.exists():
        with open(color_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = row["source_color"].strip().lower()
                ref.color_map[src] = {
                    "color_id": row["color_id"].strip(),
                    "color_name": row["color_name"].strip(),
                }

    # 4. Currency Map
    curr_file = maps_path / "currency_map.csv"
    if curr_file.exists():
        with open(curr_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = row["source_currency"].strip().upper()
                ref.currency_map[src] = float(row["exchange_rate_to_usd"])

    # 5. Country Map
    country_file = maps_path / "country_map.csv"
    if country_file.exists():
        with open(country_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = row["source_country"].strip().lower()
                ref.country_map[src] = {
                    "country_code": row["country_code_iso2"].strip().upper(),
                    "country_name": row["country_name"].strip(),
                }

    return ref


def load_supplier_configs(suppliers_dir: str | Path) -> Dict[str, SupplierConfig]:
    """Loads supplier configuration contracts from YAML files."""
    supp_path = Path(suppliers_dir)
    suppliers: Dict[str, SupplierConfig] = {}

    for yaml_path in sorted(supp_path.glob("*.yaml")):
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            cfg = SupplierConfig(
                supplier_id=data["supplier_id"],
                supplier_name=data["supplier_name"],
                priority_rank=int(data["priority_rank"]),
                trust_weight=float(data.get("trust_weight", 1.0)),
                file_pattern=data.get("file_pattern", "*"),
                format=data.get("format", "csv"),
                encoding=data.get("encoding", "utf-8"),
                delimiter=data.get("delimiter", ","),
                decimal_separator=data.get("decimal_separator", "."),
                required_columns=data.get("required_columns", []),
                optional_columns=data.get("optional_columns", []),
                column_mapping=data.get("column_mapping", {}),
                default_currency=data.get("default_currency", "USD"),
                default_weight_unit=data.get("default_weight_unit", "kg"),
                date_format=data.get("date_format", "iso8601"),
            )
            suppliers[cfg.supplier_id] = cfg

    return suppliers


def load_pipeline_config(config_path: str = "config/pipeline.yaml") -> PipelineConfig:
    """Loads top-level pipeline config and attached supplier/reference sub-configs."""
    cpath = Path(config_path)
    with open(cpath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    p_info = data.get("pipeline", {})
    mappings_dir = p_info.get("mappings_dir", "config/mappings")
    suppliers_dir = p_info.get("suppliers_dir", "config/suppliers")

    references = load_reference_maps(mappings_dir)
    suppliers = load_supplier_configs(suppliers_dir)

    return PipelineConfig(
        name=p_info.get("name", "supplier-feed-harmonizer"),
        version=p_info.get("version", "1.0.0"),
        db_path=p_info.get("db_path", "output/harmonizer.duckdb"),
        input_dir=p_info.get("input_dir", "sample_data/input"),
        mappings_dir=mappings_dir,
        suppliers_dir=suppliers_dir,
        output_dir=p_info.get("output_dir", "output"),
        log_dir=p_info.get("log_dir", "logs"),
        conflict_resolution=data.get("conflict_resolution", {}),
        entity_resolution=data.get("entity_resolution", {}),
        suppliers=suppliers,
        references=references,
        raw_config=data,
    )
