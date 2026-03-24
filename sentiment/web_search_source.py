"""
DuckDuckGo web search sentiment source.

Fetches news search results for a ticker via the ddgs library
(DuckDuckGo Search). Results provide headlines, snippets, source
domains, and publication dates that supplement news data.

No API key required — DuckDuckGo search is completely free.
"""

from __future__ import annotations

import logging
from typing import Any

from core.models import WebSearchResult
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Maximum results to request per query
_MAX_RESULTS = 10


class WebSearchSource(SentimentSource):
    """
    Fetches DuckDuckGo news search results for a stock ticker.

    Returns a list of WebSearchResult objects containing titles,
    snippets, URLs, source domains, and publication dates. The search
    query is formatted as '"TICKER" stock news' to focus on relevant
    financial content.

    No API key is required — this source is always available.
    """

    @property
    def name(self) -> str:
        return "Web Search"

    @property
    def configured(self) -> bool:
        """Always True — no API key required."""
        return True

    async def health_check(self) -> bool:
        """Check if DuckDuckGo search is reachable.

        Returns True unconditionally since no API key is needed.
        Actual connectivity is validated during fetch().
        """
        return True

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch DuckDuckGo news search results for a ticker.

        Args:
            ticker: Stock symbol (e.g., "AAPL").
            company_name: Optional company name (unused; query uses ticker).

        Returns:
            Dict with key ``web_search_results`` containing a list of
            WebSearchResult objects. Returns empty list on any error.
        """
        query = f'"{ticker}" stock news'
        results = await self._execute_search(query)
        return {"web_search_results": results}

    async def _execute_search(self, query: str) -> list[WebSearchResult]:
        """Execute a DuckDuckGo news search query and parse results.

        Args:
            query: The search query string.

        Returns:
            List of WebSearchResult parsed from the DuckDuckGo response.
            Returns empty list on errors or empty results.
        """
        try:
            import asyncio

            from ddgs import DDGS

            # DDGS is synchronous — run in executor to avoid blocking
            def _search() -> list[dict[str, Any]]:
                with DDGS() as ddgs:
                    return list(ddgs.news(query, max_results=_MAX_RESULTS))

            loop = asyncio.get_running_loop()
            raw_results = await loop.run_in_executor(None, _search)

            if not isinstance(raw_results, list):
                logger.warning("Web Search: unexpected response type: %s", type(raw_results))
                return []

            return self._parse_results(raw_results)

        except ImportError:
            logger.error("Web Search: ddgs package not installed — pip install ddgs")
            return []
        except Exception:
            logger.exception("Web Search: unexpected error during search for '%s'", query)
            return []

    def _parse_results(self, raw_results: list[dict[str, Any]]) -> list[WebSearchResult]:
        """Parse raw DuckDuckGo news results into WebSearchResult objects.

        Args:
            raw_results: List of result dicts from DDGS.news().
                Expected keys: title, body, url, source, date.

        Returns:
            List of validated WebSearchResult objects. Skips items
            that are missing required fields.
        """
        results: list[WebSearchResult] = []

        for item in raw_results:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "").strip()
            if not title:
                continue

            results.append(WebSearchResult(
                title=title,
                snippet=item.get("body", "").strip(),
                url=item.get("url", ""),
                source=item.get("source", ""),
                date=item.get("date", ""),
            ))

        return results
