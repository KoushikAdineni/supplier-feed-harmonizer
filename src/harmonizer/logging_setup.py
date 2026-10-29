"""
Structured logging module for supplier-feed-harmonizer.
Provides run_id contextual formatting for both console and persistent file logs.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class RunContextFilter(logging.Filter):
    """Injects run_id into every log record."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


class JsonLogFormatter(logging.Formatter):
    """Formats log records as structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", "NO_RUN_ID"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        # Include custom extra fields if provided
        for key, val in record.__dict__.items():
            if key not in ("msg", "args", "exc_info", "exc_text", "stack_info", "run_id", "levelname", "levelno",
                           "pathname", "filename", "module", "lineno", "funcName", "created", "msecs",
                           "relativeCreated", "thread", "threadName", "processName", "process", "name"):
                log_obj[key] = val
        return json.dumps(log_obj)


def setup_logger(run_id: str, log_dir: str = "logs", level: str = "INFO") -> logging.Logger:
    """Configures structured logger for console and file output."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("harmonizer")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    run_filter = RunContextFilter(run_id)

    # 1. Console Handler (Key=Value human readable or JSON)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_format = logging.Formatter(
        "[%(asctime)s UTC] [%(levelname)s] [run_id=%(run_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    console_handler.addFilter(run_filter)
    logger.addHandler(console_handler)

    # 2. File Handler (Structured JSON)
    file_path = log_path / f"run_{run_id}.log"
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler.setFormatter(JsonLogFormatter())
    file_handler.addFilter(run_filter)
    logger.addHandler(file_handler)

    return logger
