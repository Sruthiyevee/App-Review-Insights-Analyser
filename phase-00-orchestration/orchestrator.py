"""
orchestrator.py — Phase 00: Orchestration
-------------------------------------------
Main entry point for the App Review Pulse pipeline.

Usage:
  # Automatic mode (processes last ISO week):
  python phase-00-orchestration/orchestrator.py

  # Manual mode (specific week):
  python phase-00-orchestration/orchestrator.py --week 2026-W07

  # Force re-run (overwrite existing output):
  python phase-00-orchestration/orchestrator.py --week 2026-W07 --force

  # Dry run (resolve week and validate config, but run nothing):
  python phase-00-orchestration/orchestrator.py --dry-run

Exit codes:
  0  — Success (or skipped because already processed)
  1  — Pipeline failure
  2  — Configuration or argument error
"""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on the Python path when run directly
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PHASE_00_DIR = Path(__file__).resolve().parent

for _p in [str(PROJECT_ROOT), str(PHASE_00_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config_loader import load_config       # noqa: E402
from week_resolver import resolve_week      # noqa: E402
from run_state import (                     # noqa: E402
    is_processed,
    mark_in_progress,
    mark_phase_complete,
    mark_processed,
    mark_failed,
)
from phase_dispatcher import dispatch_all   # noqa: E402
from logger import get_logger               # noqa: E402


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="App Review Pulse — Pipeline Orchestrator",
    )
    parser.add_argument(
        "--week",
        metavar="YYYY-WNN",
        default=None,
        help="Target ISO week to process (e.g. 2026-W07). Defaults to last week.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run even if the week was already processed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Resolve week and validate config, but skip all phase execution.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main orchestration logic
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Orchestrate the full pipeline run.

    Returns:
        int: Exit code (0 = success, 1 = failure, 2 = config/arg error).
    """
    args = _parse_args()

    # --- 1. Load and validate configuration ---
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        return 2

    data_root = config.get("data_root", "data")

    # --- 2. Resolve target week ---
    try:
        week_ctx = resolve_week(args.week)
    except ValueError as exc:
        print(f"[ARGUMENT ERROR] {exc}", file=sys.stderr)
        return 2

    week_id = week_ctx.week_id

    # --- 3. Initialise logger (creates data/{week_id}/ directory) ---
    logger = get_logger(week_id=week_id, data_root=data_root)
    logger.info("=" * 60)
    logger.info(f"App Review Pulse — Orchestrator")
    logger.info(f"Target Week  : {week_id}")
    logger.info(f"Date Range   : {week_ctx.date_from} -> {week_ctx.date_to}")
    logger.info(f"Force Re-run : {args.force}")
    logger.info(f"Dry Run      : {args.dry_run}")
    logger.info("=" * 60)

    # --- 4. Idempotency guard ---
    if not args.force and not args.dry_run and is_processed(week_id):
        logger.info(
            f"Week {week_id} has already been successfully processed. "
            "Use --force to re-run."
        )
        return 0

    # --- 5. Write run_config.json for downstream phases ---
    run_config = {
        "week_id": week_id,
        "date_from": str(week_ctx.date_from),
        "date_to": str(week_ctx.date_to),
        "force": args.force,
        "dry_run": args.dry_run,
        "llm": config.get("llm", {}),
        "apps": config.get("apps", {}),
        "regions": config.get("regions", []),
        "data_root": data_root,
    }

    run_config_path = Path(data_root) / week_id / "run_config.json"
    run_config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(run_config_path, "w", encoding="utf-8") as f:
        json.dump(run_config, f, indent=2, ensure_ascii=False)

    logger.info(f"Run config written -> {run_config_path}")

    # --- 6. Mark run as in-progress ---
    if not args.dry_run:
        mark_in_progress(week_id)

    # --- 7. Dispatch phases ---
    try:
        completed_phases = dispatch_all(
            week_id=week_id,
            config=run_config,
            logger=logger,
            dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        failed_phase = _extract_phase_num(str(exc))
        logger.error(f"Pipeline aborted: {exc}")
        mark_failed(
            week_id=week_id,
            failed_at_phase=failed_phase,
            error=str(exc),
        )
        return 1

    # --- 8. Mark success ---
    if not args.dry_run:
        mark_processed(week_id=week_id, phases_completed=completed_phases)

    logger.info("=" * 60)
    logger.info(
        f"Pipeline complete for {week_id}. "
        f"Phases finished: {completed_phases}"
    )
    logger.info("=" * 60)
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_phase_num(error_msg: str) -> int:
    """Attempt to parse a phase number from a RuntimeError message."""
    import re
    match = re.search(r"Phase\s+(\d+)", error_msg)
    return int(match.group(1)) if match else -1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
