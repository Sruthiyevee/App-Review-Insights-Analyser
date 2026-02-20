"""
run_state.py — Phase 00: Orchestration
-----------------------------------------
Manages the persisted run registry so the pipeline is idempotent.

Registry location: data/run_registry.json
Format:
  {
    "2026-W07": {
      "status": "success" | "failed" | "in_progress",
      "started_at": "<ISO datetime>",
      "completed_at": "<ISO datetime>",
      "phases_completed": [1, 2, 3, ...],
      "failed_at_phase": null,
      "error": null
    },
    ...
  }

Re-runs upsert the existing entry — they never create duplicates.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTRY_FILE = Path("data") / "run_registry.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_processed(week_id: str) -> bool:
    """
    Return True if the given week_id has a 'success' entry in the registry.

    Args:
        week_id: ISO week string, e.g. '2026-W07'.

    Returns:
        bool: True only if a successful run is recorded.
    """
    registry = _load_registry()
    entry = registry.get(week_id)
    return entry is not None and entry.get("status") == "success"


def mark_in_progress(week_id: str) -> None:
    """
    Record that a run for week_id has started.
    Called by the orchestrator before dispatching any phase.
    """
    registry = _load_registry()
    registry[week_id] = {
        "status": "in_progress",
        "started_at": _now(),
        "completed_at": None,
        "phases_completed": [],
        "failed_at_phase": None,
        "error": None,
    }
    _save_registry(registry)


def mark_phase_complete(week_id: str, phase_num: int) -> None:
    """
    Append a completed phase number to the week's registry entry.

    Args:
        week_id:   ISO week string.
        phase_num: Integer phase number (1–7).
    """
    registry = _load_registry()
    entry = registry.setdefault(week_id, _empty_entry())
    completed = entry.get("phases_completed") or []
    if phase_num not in completed:
        completed.append(phase_num)
    entry["phases_completed"] = completed
    _save_registry(registry)


def mark_processed(week_id: str, phases_completed: list[int]) -> None:
    """
    Record a fully successful run.

    Args:
        week_id:          ISO week string.
        phases_completed: List of phase numbers that completed successfully.
    """
    registry = _load_registry()
    entry = registry.get(week_id, _empty_entry())
    entry.update({
        "status": "success",
        "completed_at": _now(),
        "phases_completed": phases_completed,
        "failed_at_phase": None,
        "error": None,
    })
    registry[week_id] = entry
    _save_registry(registry)


def mark_failed(week_id: str, failed_at_phase: int, error: str) -> None:
    """
    Record a failed run with context.

    Args:
        week_id:         ISO week string.
        failed_at_phase: Phase number where the failure occurred.
        error:           Human-readable error description.
    """
    registry = _load_registry()
    entry = registry.get(week_id, _empty_entry())
    entry.update({
        "status": "failed",
        "completed_at": _now(),
        "failed_at_phase": failed_at_phase,
        "error": error,
    })
    registry[week_id] = entry
    _save_registry(registry)


def get_entry(week_id: str) -> Optional[dict]:
    """
    Return the registry entry for a week, or None if not found.
    """
    return _load_registry().get(week_id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_registry(registry: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _empty_entry() -> dict:
    return {
        "status": "in_progress",
        "started_at": _now(),
        "completed_at": None,
        "phases_completed": [],
        "failed_at_phase": None,
        "error": None,
    }
