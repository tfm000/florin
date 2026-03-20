"""Tests for market hours awareness."""

from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo

from core.market_hours import US_EASTERN, is_market_open, next_market_open


class TestIsMarketOpen:
    def test_weekday_during_hours(self):
        """Tuesday 10:00 ET should be open."""
        # 2026-03-17 is a Tuesday
        dt = datetime(2026, 3, 17, 10, 0, tzinfo=US_EASTERN)
        assert is_market_open(dt) is True

    def test_weekday_before_open(self):
        """Tuesday 9:00 ET should be closed."""
        dt = datetime(2026, 3, 17, 9, 0, tzinfo=US_EASTERN)
        assert is_market_open(dt) is False

    def test_weekday_after_close(self):
        """Tuesday 16:01 ET should be closed."""
        dt = datetime(2026, 3, 17, 16, 1, tzinfo=US_EASTERN)
        assert is_market_open(dt) is False

    def test_exactly_at_open(self):
        """9:30 ET is open."""
        dt = datetime(2026, 3, 17, 9, 30, tzinfo=US_EASTERN)
        assert is_market_open(dt) is True

    def test_exactly_at_close(self):
        """16:00 ET is closed (market closes at 16:00)."""
        dt = datetime(2026, 3, 17, 16, 0, tzinfo=US_EASTERN)
        assert is_market_open(dt) is False

    def test_saturday_closed(self):
        """Saturday should be closed."""
        # 2026-03-21 is a Saturday
        dt = datetime(2026, 3, 21, 12, 0, tzinfo=US_EASTERN)
        assert is_market_open(dt) is False

    def test_sunday_closed(self):
        """Sunday should be closed."""
        dt = datetime(2026, 3, 22, 12, 0, tzinfo=US_EASTERN)
        assert is_market_open(dt) is False

    def test_holiday_closed(self):
        """Christmas 2025 should be closed."""
        dt = datetime(2025, 12, 25, 12, 0, tzinfo=US_EASTERN)
        assert is_market_open(dt) is False

    def test_utc_time_converted(self):
        """UTC time should be converted to Eastern for check."""
        # 2026-03-17 14:30 UTC = 10:30 ET (during market hours)
        dt = datetime(2026, 3, 17, 14, 30, tzinfo=UTC)
        assert is_market_open(dt) is True


class TestNextMarketOpen:
    def test_during_market_hours(self):
        """During market hours, returns today's open."""
        dt = datetime(2026, 3, 17, 12, 0, tzinfo=US_EASTERN)
        result = next_market_open(dt)
        assert result.astimezone(US_EASTERN).hour == 9
        assert result.astimezone(US_EASTERN).minute == 30

    def test_before_open_same_day(self):
        """Before open on a weekday, returns same day's open."""
        dt = datetime(2026, 3, 17, 8, 0, tzinfo=US_EASTERN)
        result = next_market_open(dt)
        eastern = result.astimezone(US_EASTERN)
        assert eastern.day == 17
        assert eastern.hour == 9

    def test_after_close_returns_next_day(self):
        """After close, returns next business day."""
        dt = datetime(2026, 3, 17, 17, 0, tzinfo=US_EASTERN)
        result = next_market_open(dt)
        eastern = result.astimezone(US_EASTERN)
        assert eastern.day == 18  # Wednesday

    def test_friday_after_close_returns_monday(self):
        """Friday after close, returns Monday."""
        # 2026-03-20 is a Friday
        dt = datetime(2026, 3, 20, 17, 0, tzinfo=US_EASTERN)
        result = next_market_open(dt)
        eastern = result.astimezone(US_EASTERN)
        assert eastern.weekday() == 0  # Monday
        assert eastern.day == 23

    def test_returns_utc(self):
        """Result is in UTC."""
        dt = datetime(2026, 3, 17, 8, 0, tzinfo=US_EASTERN)
        result = next_market_open(dt)
        assert result.tzinfo == UTC or result.utcoffset().total_seconds() == 0
