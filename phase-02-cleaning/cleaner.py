"""
cleaner.py — Phase 02: Data Cleaning & Normalization
------------------------------------------------------
Entry point for the cleaning phase. Reads the raw reviews from Phase 01,
applies deduplication, normalization, and light validation, then writes a
clean JSON file for downstream phases.

Cleaning steps applied (in order):
  1. Deduplicate by review_id (Android scraper returns same reviews per region).
  2. Drop reviews with empty or whitespace-only body.
  3. Strip leading/trailing whitespace from title and body.
  4. Normalize rating to integer in [1, 5]; drop if out of range.
  5. Ensure review_date is a valid ISO date string.
  6. Add a clean `week_id` field derived from review_date (ISO week).

Output:
  data/{run_label}/02-clean/reviews_clean.json
  data/{run_label}/02-clean/cleaning_summary.json
"""

import csv
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Ensure both the project root and this phase dir are importable
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Phase entry point (called by Phase 00 dispatcher)
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """
    Execute the Data Cleaning phase.

    Args:
        week_id: ISO week / run label string, e.g. 'historical-12w'.
        config:  Pipeline run config dict.
        logger:  Bound logger for this run.

    Raises:
        RuntimeError: If no clean reviews remain after filtering.
    """
    logger.info("Phase 02 — Data Cleaning: starting.")
    start = time.monotonic()

    data_root  = Path(config.get("data_root", "data"))
    input_path = data_root / week_id / "01-raw" / "reviews_raw.json"
    output_dir = data_root / week_id / "02-clean"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load raw ---
    if not input_path.exists():
        raise RuntimeError(f"Phase 02: input not found: {input_path}")

    with open(input_path, encoding="utf-8") as f:
        raw_reviews: list[dict] = json.load(f)

    logger.info(f"  Loaded {len(raw_reviews)} raw reviews from {input_path}")

    # --- Clean ---
    clean_reviews, stats = _clean(raw_reviews, logger)

    if not clean_reviews:
        raise RuntimeError("Phase 02: no reviews survived cleaning — aborting.")

    # --- Write output ---
    clean_path = output_dir / "reviews_clean.json"
    with open(clean_path, "w", encoding="utf-8") as f:
        json.dump(clean_reviews, f, indent=2, ensure_ascii=False)
    logger.info(f"  Clean reviews written → {clean_path}  ({len(clean_reviews)} records)")

    # Write CSV
    csv_path = output_dir / "reviews_clean.csv"
    if clean_reviews:
        fieldnames = list(clean_reviews[0].keys())
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(clean_reviews)
        logger.info(f"  Clean reviews CSV written → {csv_path}")

    # --- Summary ---
    summary = {
        "week_id": week_id,
        "cleaned_at": datetime.now(tz=timezone.utc).isoformat(),
        "input_count":        stats["input"],
        "output_count":       stats["kept"],
        "dropped_duplicate":  stats["dup"],
        "dropped_empty_body": stats["empty"],
        "dropped_bad_rating": stats["bad_rating"],
        "dropped_bad_date":   stats["bad_date"],
        "platform_counts":    stats["platforms"],
        "week_counts":        stats["weeks"],
    }
    summary_path = output_dir / "cleaning_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"  Cleaning summary written → {summary_path}")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 02 — Data Cleaning: complete in {elapsed:.1f}s. "
                f"({stats['input']} in → {stats['kept']} out, "
                f"{stats['input'] - stats['kept']} dropped)")


# ---------------------------------------------------------------------------
# Internal cleaning logic
# ---------------------------------------------------------------------------

def _clean(
    raw: list[dict],
    logger: logging.Logger,
) -> tuple[list[dict], dict]:
    """Apply all cleaning steps and return (clean_list, stats_dict)."""
    stats: dict[str, Any] = {
        "input": len(raw),
        "dup": 0,
        "empty": 0,
        "bad_rating": 0,
        "bad_date": 0,
        "kept": 0,
        "platforms": {},
        "weeks": {},
    }

    seen_ids: set[str] = set()
    clean: list[dict] = []

    for r in raw:
        # 1. Deduplicate by review_id
        rid = str(r.get("review_id", ""))
        if rid in seen_ids:
            stats["dup"] += 1
            continue
        seen_ids.add(rid)

        # 2. Drop empty body
        body = (r.get("body") or "").strip()
        if not body:
            stats["empty"] += 1
            continue

        # 3. Normalize rating
        try:
            rating = int(r.get("rating", 0))
        except (ValueError, TypeError):
            stats["bad_rating"] += 1
            continue
        if not (1 <= rating <= 5):
            stats["bad_rating"] += 1
            continue

        # 4. Validate date
        review_date_str = r.get("review_date", "")
        try:
            review_date = date.fromisoformat(review_date_str)
        except (ValueError, TypeError):
            stats["bad_date"] += 1
            continue

        # 5. Derive ISO week label
        iso_cal   = review_date.isocalendar()
        week_tag  = f"{iso_cal.year}-W{iso_cal.week:02d}"

        # Build clean record
        clean_record = {
            "review_id":   rid,
            "platform":    (r.get("platform") or "unknown").lower(),
            "app_id":      r.get("app_id", ""),
            "title":       (r.get("title") or "").strip() or None,
            "body":        body,
            "rating":      rating,
            "author":      (r.get("author") or "").strip() or None,
            "region":      (r.get("region") or "").lower(),
            "review_date": review_date_str,
            "week_id":     week_tag,
            "app_version": r.get("app_version"),
            "lang":        r.get("lang"),
            "fetched_at":  r.get("fetched_at"),
        }

        # Track counts
        plat = clean_record["platform"]
        stats["platforms"][plat] = stats["platforms"].get(plat, 0) + 1
        stats["weeks"][week_tag] = stats["weeks"].get(week_tag, 0) + 1

        clean.append(clean_record)

    # Sort by review_date descending (newest first)
    clean.sort(key=lambda x: x["review_date"], reverse=True)

    stats["kept"] = len(clean)
    return clean, stats


# ---------------------------------------------------------------------------
# Direct execution for local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Phase 02 — Data Cleaning standalone.")
    parser.add_argument("--run-label", required=True,
                        help="Run/week label used in data dir, e.g. historical-12w or 2026-W08")
    args = parser.parse_args()

    import yaml
    config_yaml = _PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml"
    with open(config_yaml) as f:
        yaml_cfg = yaml.safe_load(f)

    cfg = {
        "week_id":   args.run_label,
        "data_root": str(_PROJECT_ROOT / yaml_cfg.get("data_root", "data")),
    }

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase02.standalone")

    run(week_id=args.run_label, config=cfg, logger=_logger)
