"""
Tests for sentiment/aggregator.py — fetch_filtered, health_check,
timeout handling, and data quality levels.

Uses mock SentimentSource implementations to test the aggregator
in isolation from real API calls.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sentiment.aggregator import SentimentAggregator, SOURCE_TIMEOUT_SECONDS
from sentiment.base import SentimentSource


# ---------------------------------------------------------------------------
# Mock source implementation
# ---------------------------------------------------------------------------


class MockSource(SentimentSource):
    """A configurable mock sentiment source for testing."""

    def __init__(
        self,
        name: str,
        data: dict[str, Any] | None = None,
        *,
        delay: float = 0.0,
        should_fail: bool = False,
        healthy: bool = True,
    ) -> None:
        self._name = name
        self._data = data if data is not None else {"score": 0.5}
        self._delay = delay
        self._should_fail = should_fail
        self._healthy = healthy
        self.fetch_called = False

    @property
    def name(self) -> str:
        return self._name

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        self.fetch_called = True
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._should_fail:
            raise RuntimeError(f"{self._name} failed")
        return self._data

    async def health_check(self) -> bool:
        return self._healthy


# ===================================================================
# Tests
# ===================================================================


class TestFetchFilteredRunsOnlyNamedSources:
    """Only the named sources should be invoked by fetch_filtered."""

    @pytest.mark.asyncio
    async def test_only_named_sources_called(self):
        src_a = MockSource("SourceA", {"a": 1})
        src_b = MockSource("SourceB", {"b": 2})
        src_c = MockSource("SourceC", {"c": 3})

        agg = SentimentAggregator([src_a, src_b, src_c])
        result = await agg.fetch_filtered("AAPL", source_names=["SourceA", "SourceB"])

        assert src_a.fetch_called is True
        assert src_b.fetch_called is True
        assert src_c.fetch_called is False  # should NOT have been called

        assert result.ticker == "AAPL"
        assert result.sources_queried == 2
        assert result.sources_succeeded == 2

    @pytest.mark.asyncio
    async def test_no_matching_sources_returns_insufficient(self):
        src_a = MockSource("SourceA")
        agg = SentimentAggregator([src_a])

        result = await agg.fetch_filtered("AAPL", source_names=["NonExistent"])
        assert result.data_quality == "insufficient"
        assert result.sources_queried == 0
        assert src_a.fetch_called is False


class TestFetchTimeoutReturnsPartialResults:
    """If one source times out, the other sources' data is still returned."""

    @pytest.mark.asyncio
    async def test_slow_source_excluded_fast_sources_included(self):
        fast_src = MockSource("FastSource", {"score": 0.8})
        # Delay longer than SOURCE_TIMEOUT_SECONDS would cause a real timeout,
        # but we patch the timeout to be very short for the test.
        slow_src = MockSource("SlowSource", {"score": 0.2}, delay=5.0)

        agg = SentimentAggregator([fast_src, slow_src])

        # Patch the timeout to be very short so the test runs quickly
        import sentiment.aggregator as agg_module
        original_timeout = agg_module.SOURCE_TIMEOUT_SECONDS
        agg_module.SOURCE_TIMEOUT_SECONDS = 0.1
        try:
            result = await agg.fetch("AAPL")
        finally:
            agg_module.SOURCE_TIMEOUT_SECONDS = original_timeout

        # Fast source succeeded, slow source timed out
        assert result.sources_queried == 2
        assert result.sources_succeeded == 1
        assert result.data_quality == "low"


class TestHealthCheckAggregatesAllSources:
    """health_check returns a dict mapping source name to boolean."""

    @pytest.mark.asyncio
    async def test_mixed_health_results(self):
        healthy_src = MockSource("Healthy", healthy=True)
        sick_src = MockSource("Sick", healthy=False)
        error_src = MockSource("Error")
        # Make the health_check raise instead of returning a bool
        error_src.health_check = AsyncMock(side_effect=RuntimeError("boom"))

        agg = SentimentAggregator([healthy_src, sick_src, error_src])
        result = await agg.health_check()

        assert result == {
            "Healthy": True,
            "Sick": False,
            "Error": False,  # exception -> False
        }


class TestFetchWithAllSourcesFailing:
    """When every source fails, data_quality should be 'insufficient'."""

    @pytest.mark.asyncio
    async def test_all_failing_returns_insufficient(self):
        src_a = MockSource("A", should_fail=True)
        src_b = MockSource("B", should_fail=True)
        src_c = MockSource("C", should_fail=True)

        agg = SentimentAggregator([src_a, src_b, src_c])
        result = await agg.fetch("AAPL")

        assert result.sources_queried == 3
        assert result.sources_succeeded == 0
        assert result.data_quality == "insufficient"
        assert result.ticker == "AAPL"
        # Lists should be empty
        assert result.reddit_posts == []
        assert result.news_articles == []
        assert result.sec_filings == []


class TestDataQualityLevels:
    """Verify the quality tier logic: 0=insufficient, 1=low, <=half=medium, >half=high."""

    @pytest.mark.asyncio
    async def test_zero_sources_insufficient(self):
        agg = SentimentAggregator([])
        result = await agg.fetch("TEST")
        assert result.data_quality == "insufficient"

    @pytest.mark.asyncio
    async def test_one_of_one_is_low(self):
        """1 succeeded out of 1 queried -> sources_succeeded == 1 -> 'low'.

        The aggregator treats a single source as low quality regardless
        of whether it was the only one queried.
        """
        agg = SentimentAggregator([MockSource("Only")])
        result = await agg.fetch("TEST")
        assert result.sources_succeeded == 1
        assert result.data_quality == "low"

    @pytest.mark.asyncio
    async def test_one_of_many_is_low(self):
        """1 succeeded out of 3 queried -> 'low'."""
        sources = [
            MockSource("Good"),
            MockSource("Bad1", should_fail=True),
            MockSource("Bad2", should_fail=True),
        ]
        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")
        assert result.sources_succeeded == 1
        assert result.data_quality == "low"

    @pytest.mark.asyncio
    async def test_two_of_four_is_medium(self):
        """2 succeeded out of 4 queried -> <= half -> 'medium'."""
        sources = [
            MockSource("G1"),
            MockSource("G2"),
            MockSource("B1", should_fail=True),
            MockSource("B2", should_fail=True),
        ]
        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")
        assert result.sources_succeeded == 2
        assert result.data_quality == "medium"

    @pytest.mark.asyncio
    async def test_three_of_four_is_high(self):
        """3 succeeded out of 4 queried -> > half -> 'high'."""
        sources = [
            MockSource("G1"),
            MockSource("G2"),
            MockSource("G3"),
            MockSource("B1", should_fail=True),
        ]
        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")
        assert result.sources_succeeded == 3
        assert result.data_quality == "high"
