"""
ingestor.py — Phase 01: Review Ingestion
------------------------------------------
Primary entry point for the Review Ingestion phase.

Called by the Phase 00 dispatcher as:
    from phase_01_ingestion.ingestor import run
    run(week_id=..., config=..., logger=...)

Responsibilities:
  1. Read run_config.json to get app IDs, regions, and date range.
  2. Invoke the iOS and Android scrapers in parallel (threads).
  3. Combine results and write to data/{week_id}/01-raw/reviews_raw.json.
  4. Write an ingestion_summary.json with counts and metadata.
  5. Raise on failure so the orchestrator can log and abort.
"""

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Ensure both the project root and this phase directory are on sys.path
# so this file works when run directly AND when imported as a package.
_PHASE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from phase_01_ingestion.ios_scraper import fetch_ios_reviews        # noqa: E402
    from phase_01_ingestion.android_scraper import fetch_android_reviews # noqa: E402
    from phase_01_ingestion.review_schema import Review, reviews_to_json # noqa: E402
except ImportError:
    from ios_scraper import fetch_ios_reviews        # noqa: E402
    from android_scraper import fetch_android_reviews # noqa: E402
    from review_schema import Review, reviews_to_json # noqa: E402


# ---------------------------------------------------------------------------
# Phase entry point (called by Phase 00 dispatcher)
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """
    Execute the Review Ingestion phase.

    Args:
        week_id: ISO week string, e.g. '2026-W07'.
        config:  Pipeline run config dict (written by orchestrator).
        logger:  Bound logger for this run.

    Raises:
        RuntimeError: If ingestion fails critically.
    """
    logger.info("Phase 01 — Review Ingestion: starting.")
    start = time.monotonic()

    # -- 1. Parse config ---
    data_root   = config.get("data_root", "data")
    date_from   = date.fromisoformat(config["date_from"])
    date_to     = date.fromisoformat(config["date_to"])
    apps        = config.get("apps", {})
    regions     = config.get("regions", ["us"])

    ios_app_id        = apps.get("ios_app_id")
    android_package   = apps.get("android_package_name")

    logger.info(f"  Date range  : {date_from} -> {date_to}")
    logger.info(f"  iOS App ID  : {ios_app_id}")
    logger.info(f"  Android Pkg : {android_package}")
    logger.info(f"  Regions     : {regions}")

    # -- 2. Scrape concurrently ---
    ios_reviews: list[Review]     = []
    android_reviews: list[Review] = []
    errors: list[str]             = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}

        if ios_app_id:
            futures["ios"] = executor.submit(
                fetch_ios_reviews,
                app_id=ios_app_id,
                app_name="indmoney",          # Used in the App Store URL slug
                regions=regions,
                date_from=date_from,
                date_to=date_to,
                logger=logger,
            )

        if android_package:
            futures["android"] = executor.submit(
                fetch_android_reviews,
                package_name=android_package,
                regions=regions,
                date_from=date_from,
                date_to=date_to,
                logger=logger,
            )

        for platform, future in futures.items():
            try:
                result = future.result()
                if platform == "ios":
                    ios_reviews = result
                else:
                    android_reviews = result
            except Exception as exc:
                msg = f"Scraper failed for platform={platform}: {exc}"
                logger.error(f"  {msg}")
                errors.append(msg)

    # -- 3. Abort if both scrapers failed ---
    if errors and not ios_reviews and not android_reviews:
        raise RuntimeError(
            f"Phase 01 ingestion failed — no reviews fetched. Errors: {errors}"
        )

    # -- 4. Combine and persist ---
    all_reviews = ios_reviews + android_reviews
    logger.info(
        f"  Total reviews fetched: {len(all_reviews)} "
        f"(iOS={len(ios_reviews)}, Android={len(android_reviews)})"
    )

    output_dir = Path(data_root) / week_id / "01-raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / "reviews_raw.json"
    reviews_to_json(all_reviews, str(raw_path))
    logger.info(f"  Raw reviews written → {raw_path}")

    # -- 5. Write ingestion summary ---
    summary = {
        "week_id": week_id,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
        "totals": {
            "ios": len(ios_reviews),
            "android": len(android_reviews),
            "combined": len(all_reviews),
        },
        "regions": regions,
        "errors": errors,
    }

    summary_path = output_dir / "ingestion_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"  Ingestion summary written → {summary_path}")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 01 — Review Ingestion: complete in {elapsed:.1f}s.")


# ---------------------------------------------------------------------------
# Direct execution for local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from datetime import timedelta

    parser = argparse.ArgumentParser(description="Run Phase 01 — Review Ingestion standalone.")
    parser.add_argument("--week", default=None, help="ISO week, e.g. 2026-W07 (mutually exclusive with --lookback)")
    parser.add_argument("--lookback", type=int, default=None,
                        help="Number of weeks of history to scrape (e.g. 12). If set, --week is ignored.")
    parser.add_argument("--config", default=None, help="Path to run_config.json (optional)")
    args = parser.parse_args()

    import yaml
    config_yaml = _PHASE_DIR.parent / "phase-00-orchestration" / "config" / "pipeline_config.yaml"
    with open(config_yaml) as f:
        yaml_cfg = yaml.safe_load(f)

    today = date.today()

    if args.lookback:
        # Wide historical window: last N weeks up to today
        lookback = args.lookback
        date_from = today - timedelta(weeks=lookback)
        date_to   = today
        week_label = f"historical-{lookback}w"
    elif args.week:
        year, wk   = args.week.split("-W")
        date_from  = date.fromisocalendar(int(year), int(wk), 1)
        date_to    = date.fromisocalendar(int(year), int(wk), 7)
        week_label = args.week
    else:
        # Default: last 12 weeks
        date_from  = today - timedelta(weeks=12)
        date_to    = today
        week_label = f"historical-12w"

    cfg = {
        "week_id":   week_label,
        "date_from": str(date_from),
        "date_to":   str(date_to),
        "data_root": str(_PROJECT_ROOT / yaml_cfg.get("data_root", "data")),
        "apps":      yaml_cfg.get("apps", {}),
        "regions":   yaml_cfg.get("regions", ["in"]),
    }

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase01.standalone")

    run(week_id=week_label, config=cfg, logger=_logger)

