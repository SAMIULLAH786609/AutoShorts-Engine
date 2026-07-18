"""
AutoShorts Engine — structured logging.

All modules call get_logger(__name__) and log_step() for consistent output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def configure_logging() -> logging.Logger:
    """Configure root autoshorts logger. Safe to call multiple times."""
    logger = logging.getLogger("autoshorts")

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — full DEBUG level
    file_handler = logging.FileHandler(
        LOG_DIR / "autoshorts.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console handler — INFO and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the autoshorts namespace."""
    configure_logging()
    return logging.getLogger(f"autoshorts.{name}")


def log_step(logger: logging.Logger, step: str, message: str = "") -> None:
    """Log a pipeline step in a visually distinct format."""
    separator = "─" * 55
    logger.info(separator)
    logger.info("  ▶  %s  %s", step.upper(), f"— {message}" if message else "")
    logger.info(separator)