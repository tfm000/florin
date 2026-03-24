"""
Tests for sentiment/web_search_source.py — DuckDuckGo web search source.

Covers:
- Successful news fetch with structured results
- Empty results handling
- Network/import error handling
- Malformed response handling
- Date field parsing
- Health check and configured property
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.models import WebSearchResult
from sentiment.web_search_source import WebSearchSource


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def source() -> WebSearchSource:
    """Create a WebSearchSource instance."""
    return WebSearchSource()


def _make_ddgs_results(count: int = 3) -> list[dict]:
    """Create mock DuckDuckGo news results."""
    results = []
    for i in range(count):
        results.append({
            "title": f"Stock News {i + 1}",
            "body": f"This is the snippet for article {i + 1}.",
            "url": f"https://example.com/article-{i + 1}",
            "source": f"Source {i + 1}",
            "date": f"2026-03-{20 + i}T12:00:00+00:00",
            "image": f"https://example.com/img-{i + 1}.jpg",
        })
    return results


# =============================================================================
# Properties
# =============================================================================


class TestWebSearchSourceProperties:
    """Test basic properties of WebSearchSource."""

    def test_name(self, source: WebSearchSource) -> None:
        """Source name should be 'Web Search'."""
        assert source.name == "Web Search"

    def test_configured_always_true(self, source: WebSearchSource) -> None:
        """configured should always be True (no API key needed)."""
        assert source.configured is True

    @pytest.mark.asyncio
    async def test_health_check_always_true(self, source: WebSearchSource) -> None:
        """health_check should always return True."""
        assert await source.health_check() is True


# =============================================================================
# Successful fetch
# =============================================================================


class TestWebSearchSourceFetchSuccess:
    """Test successful DuckDuckGo news search."""

    @pytest.mark.asyncio
    async def test_returns_web_search_results_key(self, source: WebSearchSource) -> None:
        """fetch() returns a dict with 'web_search_results' key."""
        mock_results = _make_ddgs_results(2)

        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = mock_results
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert "web_search_results" in result
        assert len(result["web_search_results"]) == 2

    @pytest.mark.asyncio
    async def test_results_are_web_search_result_objects(self, source: WebSearchSource) -> None:
        """Each result should be a WebSearchResult instance."""
        mock_results = _make_ddgs_results(3)

        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = mock_results
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        for item in result["web_search_results"]:
            assert isinstance(item, WebSearchResult)

        first = result["web_search_results"][0]
        assert first.title == "Stock News 1"
        assert first.snippet == "This is the snippet for article 1."
        assert first.url == "https://example.com/article-1"
        assert first.source == "Source 1"
        assert first.date == "2026-03-20T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_query_format(self, source: WebSearchSource) -> None:
        """Query should be formatted as '"TICKER" stock news'."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = []
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            await source.fetch("TSLA")

        mock_ddgs.news.assert_called_once_with('"TSLA" stock news', max_results=10)


# =============================================================================
# Empty results
# =============================================================================


class TestWebSearchSourceEmptyResults:
    """Test handling of empty search results."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, source: WebSearchSource) -> None:
        """Empty results list returns empty web_search_results."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = []
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"] == []

    @pytest.mark.asyncio
    async def test_non_list_returns_empty(self, source: WebSearchSource) -> None:
        """Non-list response returns empty list."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = "not a list"
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"] == []


# =============================================================================
# Error handling
# =============================================================================


class TestWebSearchSourceErrors:
    """Test error handling during search."""

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self, source: WebSearchSource) -> None:
        """Network errors should return empty list, not crash."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.side_effect = ConnectionError("Network down")
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"] == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self, source: WebSearchSource) -> None:
        """Timeout errors should return empty list."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.side_effect = TimeoutError("Timed out")
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"] == []

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_empty(self, source: WebSearchSource) -> None:
        """Unexpected exceptions should return empty list."""
        with patch("ddgs.DDGS") as MockDDGS:
            MockDDGS.side_effect = RuntimeError("Unexpected")

            result = await source.fetch("AAPL")

        assert result["web_search_results"] == []


# =============================================================================
# Malformed response handling
# =============================================================================


class TestWebSearchSourceMalformedResponse:
    """Test handling of malformed/unexpected data from DuckDuckGo."""

    @pytest.mark.asyncio
    async def test_items_not_dicts_skipped(self, source: WebSearchSource) -> None:
        """Non-dict items in results should be skipped."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = ["not a dict", 42, None]
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"] == []

    @pytest.mark.asyncio
    async def test_items_without_title_skipped(self, source: WebSearchSource) -> None:
        """Items missing 'title' field should be skipped."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = [
                {"body": "No title here", "url": "https://example.com"},
                {"title": "", "body": "Empty title"},
                {"title": "Valid Title", "body": "Has title", "url": "https://example.com/valid"},
            ]
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert len(result["web_search_results"]) == 1
        assert result["web_search_results"][0].title == "Valid Title"

    @pytest.mark.asyncio
    async def test_missing_optional_fields_use_defaults(self, source: WebSearchSource) -> None:
        """Items with missing optional fields should use defaults."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = [
                {"title": "Minimal Result"},
            ]
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert len(result["web_search_results"]) == 1
        item = result["web_search_results"][0]
        assert item.title == "Minimal Result"
        assert item.snippet == ""
        assert item.url == ""
        assert item.source == ""
        assert item.date == ""


# =============================================================================
# Date field parsing
# =============================================================================


class TestWebSearchDateParsing:
    """Test that date field is preserved from DuckDuckGo results."""

    @pytest.mark.asyncio
    async def test_iso_date_preserved(self, source: WebSearchSource) -> None:
        """ISO date strings from DDG should be preserved as-is."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = [
                {
                    "title": "Test Article",
                    "date": "2026-03-23T15:15:00+00:00",
                    "body": "Content",
                    "url": "https://example.com",
                    "source": "Test Source",
                },
            ]
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"][0].date == "2026-03-23T15:15:00+00:00"

    @pytest.mark.asyncio
    async def test_relative_date_preserved(self, source: WebSearchSource) -> None:
        """Relative date strings (e.g., 'Opinion4 days ago') should be preserved."""
        with patch("ddgs.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.news.return_value = [
                {
                    "title": "Test Article",
                    "date": "Opinion4 days ago",
                    "body": "Content",
                    "url": "https://example.com",
                    "source": "Test Source",
                },
            ]
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            MockDDGS.return_value = mock_ddgs

            result = await source.fetch("AAPL")

        assert result["web_search_results"][0].date == "Opinion4 days ago"
