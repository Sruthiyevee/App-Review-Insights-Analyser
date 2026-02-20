"""
ios_scraper.py — Phase 01: Review Ingestion
---------------------------------------------
Fetches reviews from the Apple App Store via Apple's public RSS JSON API.
No third-party scraper library is used — only the `requests` package.

API endpoint pattern:
  https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json

Responsibilities:
  - Fetch reviews for a given iOS app ID and region.
  - Filter reviews to the target week's date range (date_from → date_to).
  - Return a list of canonical Review objects (review_schema.Review).

Pagination strategy:
  - Fetches pages 1–10 sequentially (Apple caps at page 10, ~500 reviews).
  - Stops early once review dates fall before date_from.
"""

import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

import requests

try:
    from phase_01_ingestion.review_schema import Review
except ImportError:
    from review_schema import Review


# Apple RSS API: max 10 pages, 50 reviews per page
MAX_PAGES = 10
RSS_URL = "https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"


def fetch_ios_reviews(
    app_id: str,
    app_name: str,
    regions: list[str],
    date_from: date,
    date_to: date,
    logger: logging.Logger,
) -> list[Review]:
    """
    Fetch App Store reviews for all specified regions within the date window.

    Args:
        app_id:    Numeric Apple App Store ID (as string), e.g. '1450178837'.
        app_name:  Human-readable app name (for logging only).
        regions:   List of country codes, e.g. ['us', 'gb', 'in'].
        date_from: Start of the target week (inclusive).
        date_to:   End of the target week (inclusive).
        logger:    Bound logger for the run.

    Returns:
        List of Review objects within the specified date range.
    """
    all_reviews: list[Review] = []
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    for region in regions:
        logger.info(f"  [iOS] Fetching reviews — region={region} ...")
        region_reviews = _fetch_region(
            app_id=app_id,
            region=region,
            date_from=date_from,
            date_to=date_to,
            fetched_at=fetched_at,
            logger=logger,
        )
        logger.info(f"  [iOS] {region}: {len(region_reviews)} reviews in window.")
        all_reviews.extend(region_reviews)

    return all_reviews


def _fetch_region(
    app_id: str,
    region: str,
    date_from: date,
    date_to: date,
    fetched_at: str,
    logger: logging.Logger,
) -> list[Review]:
    """Fetch and filter reviews for a single region via Apple RSS API."""
    reviews_out = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    for page in range(1, MAX_PAGES + 1):
        url = RSS_URL.format(country=region, page=page, app_id=app_id)
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"  [iOS] Page {page} fetch error region={region}: {exc}")
            break

        entries = data.get("feed", {}).get("entry", [])
        if not entries:
            break  # No more pages

        # The first entry on page 1 is app metadata, not a review
        if page == 1 and entries and "im:rating" not in entries[0]:
            entries = entries[1:]

        stop_early = False
        for entry in entries:
            review_date = _parse_date(
                entry.get("updated", {}).get("label")
            )

            if review_date is None:
                continue
            if review_date < date_from:
                stop_early = True
                break
            if review_date > date_to:
                continue

            review_id = entry.get("id", {}).get("label", f"ios-{region}-{page}")
            rating_raw = entry.get("im:rating", {}).get("label", "0")
            title = entry.get("title", {}).get("label")
            body = entry.get("content", {}).get("label", "")
            author = entry.get("author", {}).get("name", {}).get("label")
            version = entry.get("im:version", {}).get("label")

            reviews_out.append(
                Review(
                    review_id=str(review_id),
                    platform="ios",
                    app_id=app_id,
                    title=title,
                    body=body,
                    rating=int(float(rating_raw)) if rating_raw else 0,
                    author=author,
                    region=region,
                    review_date=review_date.isoformat(),
                    fetched_at=fetched_at,
                    app_version=version,
                    lang=None,
                )
            )

        if stop_early:
            break

        time.sleep(0.3)  # Polite pacing between pages

    return reviews_out


def _parse_date(value) -> Optional[date]:
    """Parse a date string from the Apple RSS feed."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None

