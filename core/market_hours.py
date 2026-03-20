"""US market hours awareness."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# US market holidays 2025-2026 (NYSE observed)
_HOLIDAYS: set[tuple[int, int, int]] = {
    # 2025
    (2025, 1, 1), (2025, 1, 20), (2025, 2, 17), (2025, 4, 18),
    (2025, 5, 26), (2025, 6, 19), (2025, 7, 4), (2025, 9, 1),
    (2025, 11, 27), (2025, 12, 25),
    # 2026
    (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 4, 3),
    (2026, 5, 25), (2026, 6, 19), (2026, 7, 3), (2026, 9, 7),
    (2026, 11, 26), (2026, 12, 25),
}


def is_market_open(at: datetime | None = None) -> bool:
    """Check if the US stock market is currently open.

    Args:
        at: Datetime to check (defaults to now). Must be timezone-aware or UTC is assumed.
    """
    if at is None:
        at = datetime.now(UTC)

    eastern = at.astimezone(US_EASTERN)

    # Weekends
    if eastern.weekday() >= 5:
        return False

    # Holidays
    if (eastern.year, eastern.month, eastern.day) in _HOLIDAYS:
        return False

    # Trading hours
    current_time = eastern.time()
    return MARKET_OPEN <= current_time < MARKET_CLOSE


def next_market_open(at: datetime | None = None) -> datetime:
    """Return the next market open time as a UTC datetime."""
    if at is None:
        at = datetime.now(UTC)

    eastern = at.astimezone(US_EASTERN)

    # If market is currently open, return the current day's open
    if is_market_open(at):
        return eastern.replace(
            hour=9, minute=30, second=0, microsecond=0
        ).astimezone(UTC)

    # Try today if before open
    candidate = eastern.replace(hour=9, minute=30, second=0, microsecond=0)
    if candidate > eastern:
        dt = candidate
        if dt.weekday() < 5 and (dt.year, dt.month, dt.day) not in _HOLIDAYS:
            return dt.astimezone(UTC)

    # Walk forward day by day
    day = eastern.date() + timedelta(days=1)
    for _ in range(10):  # Max 10 days ahead (holiday clusters)
        if day.weekday() < 5 and (day.year, day.month, day.day) not in _HOLIDAYS:
            return datetime(
                day.year, day.month, day.day, 9, 30,
                tzinfo=US_EASTERN,
            ).astimezone(UTC)
        day += timedelta(days=1)

    # Fallback: next business day
    return datetime(
        day.year, day.month, day.day, 9, 30,
        tzinfo=US_EASTERN,
    ).astimezone(UTC)
