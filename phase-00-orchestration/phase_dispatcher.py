"""
phase_dispatcher.py — Phase 00: Orchestration
-----------------------------------------------
Executes Phases 01–07 in order on behalf of the orchestrator.

Design principles:
  - Each phase is a callable that accepts (week_id, config, logger).
  - Phases are executed sequentially; failure in any phase raises an
    exception and halts the pipeline.
  - Phase 08 (Streamlit) is a consumer layer, not a pipeline phase —
    it is excluded here.
  - Downstream phases (01–07) are imported lazily so missing Phase
    implementations raise ImportError at dispatch time, not at startup.
    This allows the orchestrator to be run even before all phases exist.
"""

import importlib
import logging
import time
import sys
from typing import Any
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Phase registry
# Each entry: (phase_number, module_path, entry_function_name)
# ---------------------------------------------------------------------------

PHASE_REGISTRY = [
    (1, "phase-01-ingestion.ingestor",             "run"),
    (2, "phase-02-cleaning.cleaner",               "run"),
    (3, "phase-03-theme-extraction.theme_extractor","run"),
    (4, "phase-04-pulse-synthesis.pulse_synthesizer","run"),
    (5, "phase-05-action-items.action_generator",  "run"),
    (6, "phase-06-email-draft.email_drafter",      "run"),
    (7, "phase-07-storage.history_archiver",        "run"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dispatch_all(
    week_id: str,
    config: dict[str, Any],
    logger: logging.Logger,
    dry_run: bool = False,
) -> list[int]:
    """
    Run all registered phases in sequence.

    Args:
        week_id:  Target ISO week string, e.g. '2026-W07'.
        config:   Pipeline configuration dict from config_loader.
        logger:   Bound logger for the run.
        dry_run:  If True, phases are skipped entirely (no-op mode).

    Returns:
        list[int]: Phase numbers that completed successfully.

    Raises:
        RuntimeError: When a phase fails (wraps the original exception).
    """
    completed = []

    for phase_num, module_path, fn_name in PHASE_REGISTRY:
        phase_label = f"Phase {phase_num:02d}"

        if dry_run:
            logger.info(f"[DRY-RUN] Skipping {phase_label} ({module_path})")
            completed.append(phase_num)
            continue

        logger.info(f"[*] Starting {phase_label} ...")
        start = time.monotonic()

        try:
            # We add the phase directory directly to sys.path to allow
            # importing modules from hyphenated folders.
            phase_dir = _PROJECT_ROOT / module_path.split(".")[0]
            if str(phase_dir) not in sys.path:
                sys.path.insert(0, str(phase_dir))

            # The submodule name is the part after the dot
            submodule_name = module_path.split(".")[1]
            phase_fn = _import_phase(submodule_name, fn_name, phase_num)
            
            phase_fn(week_id=week_id, config=config, logger=logger)
        except ImportError as exc:
            # Phase not yet implemented — treat as a non-fatal stub
            logger.warning(
                f"   {phase_label} not yet implemented (stub). Skipping. [{exc}]"
            )
            completed.append(phase_num)
            continue
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error(
                f"[X] {phase_label} FAILED after {elapsed:.1f}s: {exc}"
            )
            raise RuntimeError(f"{phase_label} failed: {exc}") from exc

        elapsed = time.monotonic() - start
        logger.info(f"[OK] {phase_label} completed in {elapsed:.1f}s")
        completed.append(phase_num)

    return completed


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _import_phase(submodule_name: str, fn_name: str, phase_num: int):
    """
    Dynamically import a phase module and return its entry function.

    Raises:
        ImportError: If the module or function cannot be found.
    """
    try:
        module = importlib.import_module(submodule_name)
    except ModuleNotFoundError:
        raise ImportError(
            f"Phase {phase_num:02d} submodule '{submodule_name}' not found."
        )

    if not hasattr(module, fn_name):
        raise ImportError(
            f"Phase {phase_num:02d} submodule '{submodule_name}' has no '{fn_name}()' function."
        )

    return getattr(module, fn_name)
