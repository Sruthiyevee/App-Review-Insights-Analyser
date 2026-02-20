"""
history_archiver.py — Phase 07: Storage & History Registry
------------------------------------------------------------
Maintains a master history index of all completed pipeline runs.

Responsibilities:
  1. Scan the current run's data directory and verify all phase outputs exist.
  2. Collect summary metadata from each phase artifact.
  3. Upsert a record into data/history/index.json (keyed by run_label).
  4. Write a human-readable data/history/latest.json pointer.

Design:
  - Input : data/{run_label}/01-raw/ through 06-email/
  - Output: data/history/index.json  (master registry of all runs)
             data/history/latest.json (pointer to most recent run)
  - Idempotency: if the exact run_label is already in index.json AND
    none of the source artifacts have changed, skip the upsert.
  - No LLM calls — pure file I/O and JSON.

index.json schema:
{
  "runs": {
    "<run_label>": {
      "run_label":         str,
      "archived_at":       ISO-8601,
      "phases_complete":   list[str],    // e.g. ["01","02","03","04","05","06"]
      "total_raw_reviews": int,
      "total_clean_reviews": int,
      "theme_count":       int,
      "health_score":      int,
      "health_label":      str,
      "weighted_avg_rating": float,
      "action_count":      int,
      "email_sent":        bool,
      "email_recipient":   str,
      "artifacts": {
        "raw":     relative path,
        "clean":   relative path,
        "themes":  relative path,
        "pulse":   relative path,
        "actions": relative path,
        "email":   relative path,
      }
    }
  },
  "updated_at": ISO-8601
}
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Path bootstrap
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Expected artifact paths per phase
# ---------------------------------------------------------------------------

PHASE_ARTIFACTS = {
    "01": "01-raw/reviews_raw.json",
    "02": "02-clean/reviews_clean.json",
    "03": "03-themes/themes.json",
    "04": "04-pulse/pulse.json",
    "05": "05-actions/actions.json",
    "06": "06-email/send_receipt.json",
}


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """Archive the current run into the history index. No LLM calls."""
    logger.info("Phase 07 — Storage & History Registry: starting.")
    start = time.monotonic()

    data_root   = Path(config.get("data_root", "data"))
    run_dir     = data_root / week_id
    history_dir = data_root / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    index_path  = history_dir / "index.json"
    latest_path = history_dir / "latest.json"

    # ── Discover which phases completed ──────────────────────────────────────
    phases_complete = []
    artifacts       = {}
    for phase_id, rel_path in PHASE_ARTIFACTS.items():
        full_path = run_dir / rel_path
        if full_path.exists():
            phases_complete.append(phase_id)
            artifacts[_phase_label(phase_id)] = str(Path(week_id) / rel_path)

    logger.info(f"  Phases complete for '{week_id}': {phases_complete}")

    if not phases_complete:
        raise RuntimeError(
            f"Phase 07: no phase artifacts found for run '{week_id}' in {run_dir}."
        )

    # ── Extract summary metrics from artifacts ───────────────────────────────
    record = _build_record(week_id, run_dir, phases_complete, artifacts, logger)

    # ── Load existing index ──────────────────────────────────────────────────
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            index: dict = json.load(f)
    else:
        index = {"runs": {}, "updated_at": ""}

    # ── Idempotency: skip if record unchanged ────────────────────────────────
    existing = index["runs"].get(week_id)
    if existing and _records_equal(existing, record):
        logger.info(f"  Record for '{week_id}' unchanged — skipping write.")
        elapsed = time.monotonic() - start
        logger.info(f"Phase 07 — Storage & History Registry: complete in {elapsed:.1f}s.")
        return

    # ── Upsert and save ──────────────────────────────────────────────────────
    index["runs"][week_id]  = record
    index["updated_at"]     = datetime.now(tz=timezone.utc).isoformat()

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    logger.info(f"  index.json updated -> {index_path}  ({len(index['runs'])} runs total)")

    # ── Write latest pointer ─────────────────────────────────────────────────
    latest = {"run_label": week_id, "updated_at": index["updated_at"], **record}
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(latest, f, indent=2, ensure_ascii=False)
    logger.info(f"  latest.json updated -> {latest_path}")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 07 — Storage & History Registry: complete in {elapsed:.1f}s.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _phase_label(phase_id: str) -> str:
    return {
        "01": "raw", "02": "clean", "03": "themes",
        "04": "pulse", "05": "actions", "06": "email",
    }.get(phase_id, phase_id)


def _build_record(
    week_id: str,
    run_dir: Path,
    phases_complete: list[str],
    artifacts: dict,
    logger: logging.Logger,
) -> dict:
    """Read artifacts and build the index record for this run."""
    record: dict = {
        "run_label":            week_id,
        "archived_at":          datetime.now(tz=timezone.utc).isoformat(),
        "phases_complete":      phases_complete,
        "total_raw_reviews":    0,
        "total_clean_reviews":  0,
        "theme_count":          0,
        "health_score":         None,
        "health_label":         None,
        "weighted_avg_rating":  None,
        "action_count":         0,
        "email_sent":           False,
        "email_recipient":      None,
        "artifacts":            artifacts,
    }

    # Phase 01 — raw review count
    raw_path = run_dir / "01-raw" / "reviews_raw.json"
    if raw_path.exists():
        try:
            with open(raw_path, encoding="utf-8") as f:
                raw_doc = json.load(f)
            if isinstance(raw_doc, list):
                record["total_raw_reviews"] = len(raw_doc)
            else:
                record["total_raw_reviews"] = raw_doc.get("total_reviews", 0)
        except Exception as e:
            logger.warning(f"  Could not read raw summary: {e}")

    # Phase 02 — clean review count
    clean_path = run_dir / "02-clean" / "reviews_clean.json"
    if clean_path.exists():
        try:
            with open(clean_path, encoding="utf-8") as f:
                clean_doc = json.load(f)
            record["total_clean_reviews"] = len(
                clean_doc if isinstance(clean_doc, list)
                else clean_doc.get("reviews", [])
            )
        except Exception as e:
            logger.warning(f"  Could not read clean count: {e}")

    # Phase 03 — theme count
    themes_path = run_dir / "03-themes" / "themes.json"
    if themes_path.exists():
        try:
            with open(themes_path, encoding="utf-8") as f:
                themes_doc = json.load(f)
            record["theme_count"] = len(themes_doc.get("themes", []))
        except Exception as e:
            logger.warning(f"  Could not read theme count: {e}")

    # Phase 04 — pulse metrics
    pulse_path = run_dir / "04-pulse" / "pulse.json"
    if pulse_path.exists():
        try:
            with open(pulse_path, encoding="utf-8") as f:
                pulse = json.load(f)
            record["health_score"]        = pulse.get("health_score")
            record["health_label"]        = pulse.get("health_label")
            record["weighted_avg_rating"] = pulse.get("weighted_avg_rating")
        except Exception as e:
            logger.warning(f"  Could not read pulse: {e}")

    # Phase 05 — action count
    actions_path = run_dir / "05-actions" / "actions.json"
    if actions_path.exists():
        try:
            with open(actions_path, encoding="utf-8") as f:
                actions_doc = json.load(f)
            record["action_count"] = actions_doc.get("action_count", 0)
        except Exception as e:
            logger.warning(f"  Could not read action count: {e}")

    # Phase 06 — email send status
    receipt_path = run_dir / "06-email" / "send_receipt.json"
    if receipt_path.exists():
        try:
            with open(receipt_path, encoding="utf-8") as f:
                receipt = json.load(f)
            record["email_sent"]      = receipt.get("sent", False)
            record["email_recipient"] = receipt.get("recipient")
        except Exception as e:
            logger.warning(f"  Could not read send receipt: {e}")

    return record


def _records_equal(existing: dict, new: dict) -> bool:
    """Compare records ignoring timestamps."""
    skip_keys = {"archived_at"}
    return all(
        existing.get(k) == new.get(k)
        for k in new
        if k not in skip_keys
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run Phase 07 — Storage & History Registry.")
    parser.add_argument("--run-label", required=True, help="e.g. historical-12w")
    args = parser.parse_args()

    import yaml
    config_yaml = _PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml"
    with open(config_yaml) as f:
        yaml_cfg = yaml.safe_load(f)

    cfg = {"data_root": str(_PROJECT_ROOT / yaml_cfg.get("data_root", "data"))}

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase07.standalone")

    run(week_id=args.run_label, config=cfg, logger=_logger)
