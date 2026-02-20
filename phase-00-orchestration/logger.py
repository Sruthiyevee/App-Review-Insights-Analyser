"""
logger.py — Phase 00: Orchestration
-------------------------------------
Provides a structured, per-run logger.
Streams to stdout AND writes to data/{week_id}/run.log.
"""

import logging
import os
import sys
from pathlib import Path


def get_logger(week_id: str, data_root: str = "data") -> logging.Logger:
    """
    Returns a configured Logger instance for the given week_id.
    Creates the week data directory and run.log file if they do not exist.

    Args:
        week_id:    ISO week identifier, e.g. '2026-W07'.
        data_root:  Root data directory relative to the project root.

    Returns:
        logging.Logger: Configured logger instance.
    """
    log_dir = Path(data_root) / week_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "run.log"

    logger = logging.getLogger(f"pulse.{week_id}")
    logger.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers on re-runs within the same process
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # File handler — append so re-runs accumulate audit trails
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — INFO and above only
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger
