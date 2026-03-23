"""
Tests for sentiment/google_search_source.py — Google Custom Search source.

Covers:
  - Successful API responses with valid items
  - Empty search results
  - API errors (401, 403, 429)
  - Missing API key / CX (returns empty, no crash)
  - Query formatting
  - Daily rate limit enforcement
  - Malformed response handling
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config.settings import Settings
from core.models import GoogleSearchResult
from sentiment.google_search_source import (
    GoogleSearchSource,
    _DailyCounter,
    _GOOGLE_SEARCH_URL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(api_key: str = "test-key", cx: str = "test-cx") -> Settings:
    """Create a Settings object with Google Search credentials."""
    return Settings(
        google_search_api_key=api_key,
        google_search_cx=cx,
    )


def _make_search_response(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a mock Google Custom Search API response body.

    Args:
        items: List of result items. If None, uses a default set.

    Returns:
        Dict matching the structure of a Google Custom Search response.
    """
    if items is None:
        items = [
            {
                "title": "AAPL Stock Surges After Earnings",
                "snippet": "Apple Inc. reported record quarterly revenue...",
                "link": "https://finance.example.com/aapl-earnings",
                "displayLink": "finance.example.com",
            },
            {
                "title": "Is AAPL a Good Buy?",
                "snippet": "Analysts debate the valuation of Apple stock...",
                "link": "https://investing.example.com/aapl-analysis",
                "displayLink": "investing.example.com",
            },
        ]
    return {"items": items}


def _mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
) -> httpx.Response:
    """Create a mock httpx.Response.

    Args:
        status_code: HTTP status code.
        json_data: JSON body. Defaults to a valid search response.
    """
    if json_data is None:
        json_data = _make_search_response()
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", _GOOGLE_SEARCH_URL),
    )
    return resp


# ===========================================================================
# Tests — successful fetch
# ===========================================================================


class TestGoogleSearchSourceFetchSuccess:
    """Test successful Google Custom Search API responses."""

    @pytest.mark.asyncio
    async def test_returns_google_results_key(self) -> None:
        """fetch() returns a dict with 'google_results' key."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert "google_results" in result
        assert len(result["google_results"]) == 2

    @pytest.mark.asyncio
    async def test_results_are_google_search_result_objects(self) -> None:
        """Each result should be a GoogleSearchResult instance."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        for item in result["google_results"]:
            assert isinstance(item, GoogleSearchResult)

        first = result["google_results"][0]
        assert first.title == "AAPL Stock Surges After Earnings"
        assert first.source == "finance.example.com"
        assert "finance.example.com" in first.url

    @pytest.mark.asyncio
    async def test_query_format(self) -> None:
        """The search query should be formatted as '"TICKER" stock news'."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await source.fetch("TSLA")

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params", call_args.args[1] if len(call_args.args) > 1 else {})
        assert params["q"] == '"TSLA" stock news'


# ===========================================================================
# Tests — empty results
# ===========================================================================


class TestGoogleSearchSourceEmptyResults:
    """Test behaviour when search returns no items."""

    @pytest.mark.asyncio
    async def test_empty_items_returns_empty_list(self) -> None:
        """API response with empty items array returns empty list."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                json_data={"items": []},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_no_items_key_returns_empty_list(self) -> None:
        """API response without 'items' key returns empty list."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                json_data={"searchInformation": {"totalResults": "0"}},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []


# ===========================================================================
# Tests — API errors
# ===========================================================================


class TestGoogleSearchSourceAPIErrors:
    """Test graceful handling of API error responses."""

    @pytest.mark.asyncio
    async def test_401_returns_empty_no_crash(self) -> None:
        """401 Unauthorized returns empty list without crashing."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                status_code=401, json_data={"error": {"message": "Invalid key"}},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_429_returns_empty_no_crash(self) -> None:
        """429 Too Many Requests returns empty list without crashing."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                status_code=429, json_data={},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_403_returns_empty_no_crash(self) -> None:
        """403 Forbidden returns empty list without crashing."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                status_code=403, json_data={},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_no_crash(self) -> None:
        """Request timeout returns empty list without crashing."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("Timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []


# ===========================================================================
# Tests — missing API key
# ===========================================================================


class TestGoogleSearchSourceNoAPIKey:
    """Test behaviour when API key or CX is not configured."""

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self) -> None:
        """Missing API key returns empty results immediately."""
        source = GoogleSearchSource(_make_settings(api_key="", cx="test-cx"))
        result = await source.fetch("AAPL")
        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_no_cx_returns_empty(self) -> None:
        """Missing CX returns empty results immediately."""
        source = GoogleSearchSource(_make_settings(api_key="test-key", cx=""))
        result = await source.fetch("AAPL")
        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_both_empty_returns_empty(self) -> None:
        """Both API key and CX empty returns empty results."""
        source = GoogleSearchSource(_make_settings(api_key="", cx=""))
        result = await source.fetch("AAPL")
        assert result["google_results"] == []

    def test_configured_property_false(self) -> None:
        """configured property returns False when credentials missing."""
        source = GoogleSearchSource(_make_settings(api_key="", cx=""))
        assert source.configured is False

    def test_configured_property_true(self) -> None:
        """configured property returns True when both credentials set."""
        source = GoogleSearchSource(_make_settings())
        assert source.configured is True


# ===========================================================================
# Tests — daily rate limit counter
# ===========================================================================


class TestDailyCounter:
    """Test the daily usage counter."""

    def test_can_query_under_limit(self) -> None:
        """Counter allows queries when under the limit."""
        counter = _DailyCounter(limit=5)
        assert counter.can_query() is True

    def test_cannot_query_at_limit(self) -> None:
        """Counter blocks queries at the limit."""
        counter = _DailyCounter(limit=2)
        counter.increment()
        counter.increment()
        assert counter.can_query() is False

    def test_remaining_decreases(self) -> None:
        """remaining property decreases as queries are made."""
        counter = _DailyCounter(limit=5)
        assert counter.remaining == 5
        counter.increment()
        assert counter.remaining == 4
        counter.increment()
        counter.increment()
        assert counter.remaining == 2

    @pytest.mark.asyncio
    async def test_daily_limit_blocks_fetch(self) -> None:
        """When daily limit is exhausted, fetch returns empty."""
        source = GoogleSearchSource(_make_settings())
        # Exhaust the daily limit
        source._counter._count = 100
        result = await source.fetch("AAPL")
        assert result["google_results"] == []


# ===========================================================================
# Tests — malformed response
# ===========================================================================


class TestGoogleSearchSourceMalformedResponse:
    """Test handling of unexpected response formats."""

    @pytest.mark.asyncio
    async def test_items_not_a_list_returns_empty(self) -> None:
        """items field that is not a list returns empty."""
        source = GoogleSearchSource(_make_settings())

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                json_data={"items": "not a list"},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert result["google_results"] == []

    @pytest.mark.asyncio
    async def test_items_with_missing_title_skipped(self) -> None:
        """Items without a title are skipped."""
        source = GoogleSearchSource(_make_settings())

        items = [
            {"snippet": "No title here", "link": "https://example.com"},
            {"title": "Valid Title", "snippet": "Good", "link": "https://good.com", "displayLink": "good.com"},
        ]

        with patch("sentiment.google_search_source.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(
                json_data={"items": items},
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await source.fetch("AAPL")

        assert len(result["google_results"]) == 1
        assert result["google_results"][0].title == "Valid Title"


# ===========================================================================
# Tests — health check
# ===========================================================================


class TestGoogleSearchSourceHealthCheck:
    """Test health_check behaviour."""

    @pytest.mark.asyncio
    async def test_health_check_false_when_not_configured(self) -> None:
        """health_check returns False when API key is missing."""
        source = GoogleSearchSource(_make_settings(api_key=""))
        result = await source.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_false_when_limit_exhausted(self) -> None:
        """health_check returns False when daily limit is reached."""
        source = GoogleSearchSource(_make_settings())
        source._counter._count = 100
        result = await source.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_true_when_configured_and_under_limit(self) -> None:
        """health_check returns True when configured and under limit."""
        source = GoogleSearchSource(_make_settings())
        result = await source.health_check()
        assert result is True
