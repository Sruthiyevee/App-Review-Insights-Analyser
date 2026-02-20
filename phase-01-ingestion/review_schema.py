"""
review_schema.py — Phase 01: Review Ingestion
-----------------------------------------------
Defines the canonical, normalised Review dataclass.

All scrapers (iOS, Android) MUST produce this schema.
Downstream phases consume ONLY this shape — never raw source data.
"""

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional
import json


@dataclass
class Review:
    """Canonical single-review record written by every scraper."""

    # --- Identity ---
    review_id: str              # Unique ID from the source platform
    platform: str               # "ios" | "android"
    app_id: str                 # The app identifier used to fetch this review

    # --- Content ---
    title: Optional[str]        # Review title (may be None on Android)
    body: str                   # Review text body
    rating: int                 # 1–5 stars

    # --- Attribution ---
    author: Optional[str]       # Display name (may be anonymised)
    region: str                 # Locale/country code, e.g. "us"

    # --- Timestamps ---
    review_date: str            # ISO date string, e.g. "2026-02-13"
    fetched_at: str             # ISO datetime when this record was scraped

    # --- Metadata ---
    app_version: Optional[str] = field(default=None)  # App version reviewed
    lang: Optional[str] = field(default=None)         # Language code, e.g. "en"

    def to_dict(self) -> dict:
        return asdict(self)


def reviews_to_json(reviews: list[Review], path: str) -> None:
    """
    Serialise a list of Review objects to a JSON file.

    Args:
        reviews: List of Review dataclass instances.
        path:    Absolute or relative file path to write.
    """
    import pathlib
    out_path = pathlib.Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in reviews], f, indent=2, ensure_ascii=False)
