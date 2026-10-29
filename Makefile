.PHONY: setup sample run gen-large run-large test report bench clean help

VENV ?= .venv
ifeq ($(OS),Windows_NT)
    PYTHON ?= $(wildcard $(VENV)/Scripts/python.exe)
    ifeq ($(strip $(PYTHON)),)
        PYTHON := python
    endif
else
    PYTHON ?= $(wildcard $(VENV)/bin/python)
    ifeq ($(strip $(PYTHON)),)
        PYTHON := python3
    endif
endif

help:
	@echo "Available targets:"
	@echo "  setup      - Install dependencies in virtualenv"
	@echo "  sample     - Generate synthetic sample data (fixed seed 42)"
	@echo "  run        - Execute pipeline on sample data"
	@echo "  gen-large  - Generate large dataset (120,000+ rows)"
	@echo "  run-large  - Run pipeline on large dataset"
	@echo "  test       - Run pytest suite and save docs/test_evidence.txt"
	@echo "  report     - Generate docs/reconciliation_report.md"
	@echo "  bench      - Run benchmark script and produce docs/performance.md"
	@echo "  clean      - Remove temporary files, logs, and build artifacts"

setup:
	$(PYTHON) -m pip install -r requirements.txt

sample:
	$(PYTHON) scripts/generate_data.py --rows 300 --seed 42 --out sample_data/input

run:
	$(PYTHON) -m src.harmonizer.cli run --input-dir sample_data/input --db-path output/harmonizer.duckdb

gen-large:
	$(PYTHON) scripts/generate_data.py --rows 120000 --seed 42 --out output/large_input

run-large:
	$(PYTHON) -m src.harmonizer.cli run --input-dir output/large_input --db-path output/harmonizer_large.duckdb

test:
	$(PYTHON) -c "import subprocess, pathlib, sys; res = subprocess.run([sys.executable, '-m', 'pytest', '-v', '--cov=src.harmonizer', '--cov-report=term-missing', 'tests/'], capture_output=True, text=True); print(res.stdout); print(res.stderr); pathlib.Path('docs/test_evidence.txt').write_text(res.stdout, encoding='utf-8'); sys.exit(res.returncode)"


report:
	$(PYTHON) -m src.harmonizer.cli report --db-path output/harmonizer.duckdb --out-markdown docs/reconciliation_report.md --out-csv docs/reconciliation_metrics.csv

bench:
	$(PYTHON) scripts/benchmark.py --rows 120000 --seed 42

clean:
	$(PYTHON) -c "import shutil, pathlib, glob; [shutil.rmtree(p, ignore_errors=True) for p in ['output', 'logs', '.pytest_cache', 'htmlcov', '__pycache__']]; [pathlib.Path(f).unlink(missing_ok=True) for f in glob.glob('**/*.pyc', recursive=True)]"
