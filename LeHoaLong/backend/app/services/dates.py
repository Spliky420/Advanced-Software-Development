"""Date helpers.

Small and pure, so the progress and planning arithmetic added in later steps
can be unit tested against a fixed "today" without patching the clock in
several places.

Everything is ISO-8601 text, matching the schema: dates YYYY-MM-DD,
timestamps YYYY-MM-DDTHH:MM:SS.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

DATE_FORMAT = "%Y-%m-%d"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def today() -> date:
    """The current date in UTC.

    UTC rather than local time so that the API, the tests and a container in
    another timezone all agree on which steps are overdue.
    """
    return datetime.now(timezone.utc).date()


def now_iso() -> str:
    """The current UTC timestamp, as stored in created_at / updated_at."""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def parse_date(value: str) -> date:
    """Parse an ISO-8601 date. Raises ValueError on anything else.

    Deliberately strict: `datetime.strptime` accepts '2026-9-3', which would
    then sort wrongly against the zero-padded dates already in the database,
    so the round-trip is checked too.
    """
    parsed = datetime.strptime(value, DATE_FORMAT).date()
    if parsed.strftime(DATE_FORMAT) != value:
        raise ValueError(f"not a zero-padded ISO-8601 date: {value!r}")
    return parsed


def to_iso(value: date) -> str:
    """Format a date as ISO-8601 text."""
    return value.strftime(DATE_FORMAT)


def add_months(start: date, months: int) -> date:
    """Add whole months, clamping the day to the end of the target month.

    31 January plus one month is 28 February, not an error and not 3 March.
    Used to lay out monthly savings steps from a start date.
    """
    zero_based = start.month - 1 + months
    year = start.year + zero_based // 12
    month = zero_based % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start: date, end: date) -> int:
    """Whole months from start to end, rounded up, never below zero.

    "Rounded up" is the useful reading for a savings plan: with six weeks to
    go you need two instalments, not one. A target date on or before the
    start returns 0, which callers treat as "no time left to plan".
    """
    if end <= start:
        return 0
    whole = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        whole += 1
    return max(whole, 1)
