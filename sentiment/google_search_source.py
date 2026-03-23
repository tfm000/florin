"""
Google Custom Search sentiment source.

Fetches web search results for a ticker via the Google Custom Search
JSON API (https://www.googleapis.com/customsearch/v1). Results provide
headlines, snippets, and source domains that supplement news data.

Free tier: 100 queries/day. A simple daily counter tracks usage and
refuses to query once the limit is reached.

Requires two settings:
  - google_search_api_key: API key for Google Custom Search
  - google_search_cx: Custom Search Engine ID
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config.settings import Settings
from core.models import GoogleSearchResult
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Google Custom Search JSON API endpoint
_GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

# Free tier daily limit
_DAILY_QUERY_LIMIT = 100

# Maximum results to request per query (API max is 10)
_MAX_RESULTS_PER_QUERY = 10


class _DailyCounter:
    """Simple daily usage counter that resets at midnight UTC.

    Tracks the number of API queries made today and refuses to
    allow more once the daily limit is reached.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._count = 0
        self._day: int = _utc_day()

    def can_query(self) -> bool:
        """Return True if a query is allowed under the daily limit."""
        self._maybe_reset()
        return self._count < self._limit

    def increment(self) -> None:
        """Record one query."""
        self._maybe_reset()
        self._count += 1

    @property
    def remaining(self) -> int:
        """Number of queries remaining today."""
        self._maybe_reset()
        return max(0, self._limit - self._count)

    def _maybe_reset(self) -> None:
        """Reset the counter if the UTC day has changed."""
        today = _utc_day()
        if today != self._day:
            self._count = 0
            self._day = today


def _utc_day() -> int:
    """Return the current UTC day as an ordinal integer."""
    return int(time.time() // 86400)


class GoogleSearchSource(SentimentSource):
    """
    Fetches Google Custom Search results for a stock ticker.

    Returns a list of GoogleSearchResult objects containing titles,
    snippets, URLs, and source domains. The search query is formatted
    as '"TICKER" stock news' to focus on relevant financial content.

    If the API key is not configured, all methods return empty results
    without raising exceptions.
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.google_search_api_key
        self._cx = settings.google_search_cx
        self._counter = _DailyCounter(_DAILY_QUERY_LIMIT)

    @property
    def name(self) -> str:
        return "Google Search"

    @property
    def configured(self) -> bool:
        """Return True if the API key and CX are both set."""
        return bool(self._api_key and self._cx)

    async def health_check(self) -> bool:
        """Check if the Google Custom Search API is reachable.

        Returns False if the API key is not configured or the daily
        limit has been exhausted.
        """
        if not self.configured:
            return False
        if not self._counter.can_query():
            logger.warning(
                "Google Search daily limit reached (%d/%d)",
                _DAILY_QUERY_LIMIT, _DAILY_QUERY_LIMIT,
            )
            return False
        return True

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch Google Custom Search results for a ticker.

        Args:
            ticker: Stock symbol (e.g., "AAPL").
            company_name: Optional company name (unused; query uses ticker).

        Returns:
            Dict with key ``google_results`` containing a list of
            GoogleSearchResult objects. Returns empty list on any error.
        """
        if not self.configured:
            logger.debug("Google Search: API key or CX not configured, skipping")
            return {"google_results": []}

        if not self._counter.can_query():
            logger.warning(
                "Google Search: daily query limit reached (%d/%d)",
                _DAILY_QUERY_LIMIT, _DAILY_QUERY_LIMIT,
            )
            return {"google_results": []}

        query = f'"{ticker}" stock news'
        results = await self._execute_search(query)
        return {"google_results": results}

    async def _execute_search(self, query: str) -> list[GoogleSearchResult]:
        """Execute a Google Custom Search query and parse results.

        Args:
            query: The search query string.

        Returns:
            List of GoogleSearchResult parsed from the API response.
            Returns empty list on HTTP errors or malformed responses.
        """
        params = {
            "key": self._api_key,
            "cx": self._cx,
            "q": query,
            "num": _MAX_RESULTS_PER_QUERY,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_GOOGLE_SEARCH_URL, params=params)

            # Record the query against the daily counter regardless of outcome
            self._counter.increment()

            if resp.status_code == 401:
                logger.error("Google Search: invalid API key (401 Unauthorized)")
                return []

            if resp.status_code == 429:
                logger.warning("Google Search: rate limited by Google (429)")
                return []

            if resp.status_code == 403:
                logger.error(
                    "Google Search: forbidden (403) — check API key permissions or billing"
                )
                return []

            if resp.status_code != 200:
                logger.warning(
                    "Google Search: unexpected status %d for query '%s'",
                    resp.status_code, query,
                )
                return []

            # Validate response body
            data = resp.json()
            if not isinstance(data, dict):
                logger.warning("Google Search: response is not a JSON object")
                return []

            items = data.get("items", [])
            if not isinstance(items, list):
                logger.warning("Google Search: 'items' field is not a list")
                return []

            return self._parse_items(items)

        except httpx.TimeoutException:
            logger.warning("Google Search: request timed out for query '%s'", query)
            return []
        except httpx.HTTPError as exc:
            logger.warning("Google Search: HTTP error: %s", exc)
            return []
        except Exception:
            logger.exception("Google Search: unexpected error during search")
            return []

    def _parse_items(self, items: list[dict[str, Any]]) -> list[GoogleSearchResult]:
        """Parse raw API items into GoogleSearchResult objects.

        Args:
            items: List of item dicts from the Google Custom Search API response.

        Returns:
            List of validated GoogleSearchResult objects. Skips items
            that are missing required fields.
        """
        results: list[GoogleSearchResult] = []

        for item in items:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "").strip()
            if not title:
                continue

            results.append(GoogleSearchResult(
                title=title,
                snippet=item.get("snippet", "").strip(),
                url=item.get("link", ""),
                source=item.get("displayLink", ""),
            ))

        return results
