"""
week_resolver.py — Phase 00: Orchestration
--------------------------------------------
Resolves the target processing week.

Rules:
  - If --week is provided via CLI, validate and use it.
  - If not provided, compute "last ISO week" relative to today.

Returns a WeekContext dataclass with:
  - week_id:    str  e.g. '2026-W07'
  - date_from:  date (Monday of that week)
  - date_to:    date (Sunday of that week)
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Data contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WeekContext:
    week_id: str    # e.g. '2026-W07'
    date_from: date # Monday
    date_to: date   # Sunday


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_week(week_arg: str | None = None) -> WeekContext:
    """
    Resolve the target week.

    Args:
        week_arg: Optional string in 'YYYY-WNN' format passed from the CLI.

    Returns:
        WeekContext with the resolved week.

    Raises:
        ValueError: If week_arg is provided but has an invalid format or date.
    """
    if week_arg is not None:
        return _parse_week_arg(week_arg)
    return _last_iso_week()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")


def _parse_week_arg(week_arg: str) -> WeekContext:
    """Validate and parse a user-supplied 'YYYY-WNN' string or custom label."""
    # 1. Try standard YYYY-WNN format
    match = _WEEK_PATTERN.match(week_arg.strip().upper())
    if match:
        year = int(match.group(1))
        week_num = int(match.group(2))

        if not (1 <= week_num <= 53):
            raise ValueError(f"Week number {week_num} is out of range (1–53).")

        # ISO week Monday
        monday = date.fromisocalendar(year, week_num, 1)
        sunday = monday + timedelta(days=6)
        week_id = f"{year}-W{week_num:02d}"

        return WeekContext(week_id=week_id, date_from=monday, date_to=sunday)

    # 2. Allow custom alphanumeric labels (e.g. 'historical-12w')
    if re.match(r"^[a-zA-Z0-9_\-]+$", week_arg):
        today = date.today()
        # Default to a wide window; Phase 01's --lookback overrides this anyway
        return WeekContext(
            week_id=week_arg,
            date_from=today - timedelta(days=90),
            date_to=today
        )

    raise ValueError(
        f"Invalid --week format '{week_arg}'. "
        "Expected YYYY-WNN (e.g. 2026-W07) or an alphanumeric label."
    )


def _last_iso_week() -> WeekContext:
    """Compute the ISO week that ended most recently (i.e. last week)."""
    today = date.today()
    # Subtract 7 days to land firmly in last week
    last_week_day = today - timedelta(weeks=1)
    iso = last_week_day.isocalendar()

    year = iso.year
    week_num = iso.week

    monday = date.fromisocalendar(year, week_num, 1)
    sunday = monday + timedelta(days=6)
    week_id = f"{year}-W{week_num:02d}"

    return WeekContext(week_id=week_id, date_from=monday, date_to=sunday)
