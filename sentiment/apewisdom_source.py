"""
ApeWisdom Reddit-aggregated sentiment source.

Fetches trending stock rankings from ApeWisdom, which aggregates
mention counts and upvotes across Reddit stock subreddits (WSB,
r/stocks, r/pennystocks, r/investing, etc.).

API: GET https://apewisdom.io/api/v1.0/filter/all-stocks
No API key required — free and public.

Reference: https://apewisdom.io/api/
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config.constants import APEWISDOM_API_BASE
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Cache the trending list for this many seconds to avoid hammering
# during multi-ticker analysis runs.
_CACHE_TTL_SECONDS = 900  # 15 minutes


class ApeWisdomSource(SentimentSource):
    """
    Fetches Reddit-aggregated stock trending data from ApeWisdom.

    Returns rank, mention count, and upvote count for the requested
    ticker. The trending list is cached for 15 minutes to minimise
    requests during multi-ticker runs.

    No API key required — always enabled.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_time: float = 0.0

    @property
    def name(self) -> str:
        """Human-readable source name."""
        return "ApeWisdom"

    @property
    def configured(self) -> bool:
        """Always True — no API key required."""
        return True

    async def health_check(self) -> bool:
        """Check if ApeWisdom API is reachable.

        Returns:
            True if the trending endpoint responds with 200.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{APEWISDOM_API_BASE}/filter/all-stocks",
                )
                return resp.status_code == 200
        except (httpx.HTTPError, OSError, ValueError):
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch ApeWisdom trending data for a ticker.

        Args:
            ticker: Stock symbol (e.g., "AAPL").
            company_name: Unused; present for interface conformance.

        Returns:
            Dict with keys: "apewisdom_rank", "apewisdom_mentions",
            "apewisdom_upvotes". Returns empty dict on network failure,
            or zeroed data if ticker is not trending.
        """
        try:
            ticker_map = await self._get_trending_map()
            entry = ticker_map.get(ticker.upper())

            if not entry:
                logger.debug("ApeWisdom: %s not in trending list", ticker)
                return {
                    "apewisdom_rank": 0,
                    "apewisdom_mentions": 0,
                    "apewisdom_upvotes": 0,
                }

            return {
                "apewisdom_rank": entry.get("rank", 0),
                "apewisdom_mentions": entry.get("mentions", 0),
                "apewisdom_upvotes": entry.get("upvotes", 0),
            }

        except httpx.TimeoutException:
            logger.warning("ApeWisdom: request timed out")
            return {}
        except httpx.HTTPError as exc:
            logger.warning("ApeWisdom: HTTP error: %s", exc)
            return {}
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("ApeWisdom: parse error for %s: %s", ticker, exc)
            return {}

    async def _get_trending_map(self) -> dict[str, dict[str, Any]]:
        """Fetch and cache the trending stocks map.

        Returns a dict keyed by uppercase ticker symbol, each value
        containing rank, mentions, and upvotes.

        The list is cached for _CACHE_TTL_SECONDS to avoid redundant
        requests during multi-ticker analysis runs.
        """
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < _CACHE_TTL_SECONDS:
            return self._cache

        data = await self._fetch_trending_data()
        if data is None:
            return self._cache  # Return stale cache on failure

        ticker_map = self._parse_trending_results(data)
        self._cache = ticker_map
        self._cache_time = now
        logger.debug("ApeWisdom: cached %d trending tickers", len(ticker_map))
        return ticker_map

    async def _fetch_trending_data(self) -> dict[str, Any] | None:
        """Fetch raw trending data from ApeWisdom API.

        Returns:
            Parsed JSON response dict, or None on failure.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{APEWISDOM_API_BASE}/filter/all-stocks")

            if resp.status_code != 200:
                logger.warning(
                    "ApeWisdom: HTTP %d — %s", resp.status_code, resp.text[:300],
                )
                return None

            data = resp.json()

        if not isinstance(data, dict):
            logger.warning("ApeWisdom: response is not a JSON object")
            return None

        return data

    def _parse_trending_results(self, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Parse trending results into a ticker-keyed map.

        Args:
            data: Validated JSON response from ApeWisdom.

        Returns:
            Dict keyed by uppercase ticker, values contain rank/mentions/upvotes.
        """
        results = data.get("results", [])
        if not isinstance(results, list):
            logger.warning("ApeWisdom: 'results' is not a list")
            return {}

        ticker_map: dict[str, dict[str, Any]] = {}
        for entry in results:
            if not isinstance(entry, dict):
                continue
            raw_ticker = entry.get("ticker", "")
            if not raw_ticker:
                continue

            try:
                ticker_map[raw_ticker.upper()] = {
                    "rank": int(entry.get("rank", 0)),
                    "mentions": int(entry.get("mentions", 0)),
                    "upvotes": int(entry.get("upvotes", 0)),
                    "rank_24h_ago": int(entry.get("rank_24h_ago", 0)),
                    "mentions_24h_ago": int(entry.get("mentions_24h_ago", 0)),
                }
            except (ValueError, TypeError):
                logger.debug("ApeWisdom: failed to parse entry: %s", entry)
                continue

        return ticker_map
