#!/usr/bin/env python3
"""
Cross-platform helper script for environments where GNU 'make' is not installed in PATH.
Mirrors all Makefile targets: setup, sample, run, gen-large, run-large, test, report, bench, clean.
Usage:
    python run.py <target>
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PYTHON = sys.executable

TARGETS = {
    "setup": [PYTHON, "-m", "pip", "install", "-r", "requirements.txt"],
    "sample": [PYTHON, "scripts/generate_data.py", "--rows", "300", "--seed", "42", "--out", "sample_data/input"],
    "run": [PYTHON, "-m", "src.harmonizer.cli", "run", "--input-dir", "sample_data/input", "--db-path", "output/harmonizer.duckdb"],
    "gen-large": [PYTHON, "scripts/generate_data.py", "--rows", "120000", "--seed", "42", "--out", "output/large_input"],
    "run-large": [PYTHON, "-m", "src.harmonizer.cli", "run", "--input-dir", "output/large_input", "--db-path", "output/harmonizer_large.duckdb"],
    "test": [PYTHON, "-m", "pytest", "-v", "--cov=src.harmonizer", "--cov-report=term-missing", "tests/"],
    "report": [PYTHON, "-m", "src.harmonizer.cli", "report", "--db-path", "output/harmonizer.duckdb", "--out-markdown", "docs/reconciliation_report.md", "--out-csv", "docs/reconciliation_metrics.csv"],
    "bench": [PYTHON, "scripts/benchmark.py", "--rows", "120000", "--seed", "42"],
}


def clean() -> None:
    for d in ["output", "logs", ".pytest_cache", "htmlcov", "__pycache__"]:
        p = Path(d)
        if p.exists() and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    for pyc in Path(".").rglob("*.pyc"):
        pyc.unlink(missing_ok=True)
    print("Cleaned build artifacts, logs, cache, and compiled bytecode.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-platform command runner mirroring Makefile targets")
    parser.add_argument("target", choices=list(TARGETS.keys()) + ["clean"], help="Target command to execute")
    args = parser.parse_args()

    if args.target == "clean":
        clean()
        return

    cmd = TARGETS[args.target]
    print(f">> Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd)
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
