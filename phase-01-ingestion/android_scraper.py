"""
android_scraper.py — Phase 01: Review Ingestion
-------------------------------------------------
Fetches reviews from the Google Play Store using the
`google-play-scraper` library.

Responsibilities:
  - Fetch reviews for a given Android package name and region.
  - Filter reviews to the target week's date range (date_from → date_to).
  - Return a list of canonical Review objects (review_schema.Review).

Pagination strategy:
  - Fetches reviews sorted by newest first.
  - Continues fetching pages with continuation_token until reviews fall
    before date_from or MAX_REVIEWS is reached.
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from google_play_scraper import reviews as gplay_reviews
from google_play_scraper import Sort

try:
    from phase_01_ingestion.review_schema import Review
except ImportError:
    from review_schema import Review


# Safety cap: maximum reviews to fetch per region
MAX_REVIEWS = 2000
BATCH_SIZE = 200


def fetch_android_reviews(
    package_name: str,
    regions: list[str],
    date_from: date,
    date_to: date,
    logger: logging.Logger,
) -> list[Review]:
    """
    Fetch Google Play reviews for all specified regions within the date window.

    Args:
        package_name: Android package name, e.g. 'in.indwealth'.
        regions:      List of country codes, e.g. ['us', 'gb', 'in'].
        date_from:    Start of the target week (inclusive).
        date_to:      End of the target week (inclusive).
        logger:       Bound logger for the run.

    Returns:
        List of Review objects within the specified date range.
    """
    all_reviews: list[Review] = []
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    for region in regions:
        logger.info(f"  [Android] Fetching reviews for region={region} ...")
        region_reviews = _fetch_region(
            package_name=package_name,
            region=region,
            date_from=date_from,
            date_to=date_to,
            fetched_at=fetched_at,
            logger=logger,
        )
        logger.info(f"  [Android] {region}: {len(region_reviews)} reviews in window.")
        all_reviews.extend(region_reviews)

    return all_reviews


def _fetch_region(
    package_name: str,
    region: str,
    date_from: date,
    date_to: date,
    fetched_at: str,
    logger: logging.Logger,
) -> list[Review]:
    """Fetch and filter reviews for a single region using pagination."""
    reviews_out = []
    continuation_token = None
    total_fetched = 0

    while total_fetched < MAX_REVIEWS:
        try:
            batch, continuation_token = gplay_reviews(
                package_name,
                lang="en",
                country=region,
                sort=Sort.NEWEST,
                count=BATCH_SIZE,
                continuation_token=continuation_token,
            )
        except Exception as exc:
            logger.warning(f"  [Android] Error fetching region={region}: {exc}")
            break

        if not batch:
            break

        for raw in batch:
            review_date = _parse_date(raw.get("at"))
            if review_date is None:
                continue

            # Stop fetching once we pass the beginning of the target window
            if review_date < date_from:
                return reviews_out

            if review_date <= date_to:
                reviews_out.append(
                    Review(
                        review_id=str(raw.get("reviewId", f"android-{region}-{hash(raw.get('content',''))}")),
                        platform="android",
                        app_id=package_name,
                        title=None,  # Google Play reviews have no title
                        body=raw.get("content", ""),
                        rating=int(raw.get("score", 0)),
                        author=raw.get("userName"),
                        region=region,
                        review_date=review_date.isoformat(),
                        fetched_at=fetched_at,
                        app_version=raw.get("appVersion"),
                        lang="en",
                    )
                )

        total_fetched += len(batch)

        # No more pages
        if continuation_token is None:
            break

    return reviews_out


def _parse_date(value) -> Optional[date]:
    """Parse a date from the datetime object Google Play scraper returns."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None
