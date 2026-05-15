"""
Alpha Vantage news sentiment source.

Fetches AI-scored news articles for a ticker from Alpha Vantage's
NEWS_SENTIMENT endpoint. Each article includes overall sentiment
and per-ticker relevance/sentiment scores.

API: GET https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={key}
Rate limit: 25 requests/day (free tier).

Reference: https://www.alphavantage.co/documentation/#news-sentiment
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from config.constants import ALPHAVANTAGE_API_BASE
from core.models import AlphaVantageNewsSentiment
from core.rate_limiter import AsyncRateLimiter
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Maximum articles to retain per fetch
_MAX_ARTICLES = 20


class AlphaVantageSource(SentimentSource):
    """
    Fetches AI-scored news sentiment from Alpha Vantage.

    Returns news articles with sentiment scores and per-ticker
    relevance ratings. Auto-disables if no API key is configured.

    Args:
        api_key: Alpha Vantage API key. If empty, the source is disabled.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        # Free tier: 25 requests/day = ~1 per 3456s.
        # Use a conservative limiter to avoid exhausting the quota.
        self._limiter = AsyncRateLimiter(25, 86400, name="AlphaVantage")

    @property
    def name(self) -> str:
        """Human-readable source name."""
        return "Alpha Vantage"

    @property
    def configured(self) -> bool:
        """True if an API key is provided."""
        return bool(self._api_key)

    async def health_check(self) -> bool:
        """Check if Alpha Vantage API is reachable.

        Returns:
            True if the NEWS_SENTIMENT endpoint responds with 200
            for a known ticker (AAPL) and contains a valid feed.
        """
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    ALPHAVANTAGE_API_BASE,
                    params={
                        "function": "NEWS_SENTIMENT",
                        "tickers": "AAPL",
                        "limit": "1",
                        "apikey": self._api_key,
                    },
                )
                if resp.status_code != 200:
                    return False
                data = resp.json()
                if "Error Message" in data or "Note" in data:
                    return False
                return "feed" in data
        except (httpx.HTTPError, OSError, ValueError):
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch Alpha Vantage news sentiment for a ticker.

        Args:
            ticker: Stock symbol (e.g., "AAPL").
            company_name: Unused; present for interface conformance.

        Returns:
            Dict with keys: "alphavantage_articles"
            (list[AlphaVantageNewsSentiment]), "alphavantage_avg_sentiment"
            (float). Returns empty dict on failure.
        """
        if not self.configured:
            return {}

        try:
            return await self._fetch_and_parse(ticker)
        except httpx.TimeoutException:
            logger.warning("Alpha Vantage: request timed out for %s", ticker)
            return {}
        except httpx.HTTPError as exc:
            logger.warning("Alpha Vantage: HTTP error for %s: %s", ticker, exc)
            return {}
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Alpha Vantage: parse error for %s: %s", ticker, exc)
            return {}

    async def _fetch_and_parse(self, ticker: str) -> dict[str, Any]:
        """Execute the API request and parse the response.

        Args:
            ticker: Stock symbol.

        Returns:
            Dict with parsed articles and avg sentiment, or empty dict.

        Raises:
            httpx.HTTPError: On network/transport failures.
            ValueError: On invalid response data.
        """
        await self._limiter.acquire()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                ALPHAVANTAGE_API_BASE,
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker,
                    "sort": "LATEST",
                    "limit": str(_MAX_ARTICLES),
                    "apikey": self._api_key,
                },
            )

            if resp.status_code != 200:
                logger.warning(
                    "Alpha Vantage: HTTP %d for %s — %s",
                    resp.status_code,
                    ticker,
                    resp.text[:300],
                )
                return {}

            data = resp.json()

        if not isinstance(data, dict):
            logger.warning("Alpha Vantage: response is not a JSON object for %s", ticker)
            return {}

        # Check for API errors embedded in the JSON
        if "Error Message" in data:
            logger.warning("Alpha Vantage: API error for %s: %s", ticker, data["Error Message"])
            return {}
        if "Note" in data:
            logger.warning("Alpha Vantage: rate limit note for %s: %s", ticker, data["Note"])
            return {}

        return self._parse_response(data, ticker)

    def _parse_response(self, data: dict[str, Any], ticker: str) -> dict[str, Any]:
        """Parse Alpha Vantage NEWS_SENTIMENT response.

        Args:
            data: Raw JSON response from Alpha Vantage.
            ticker: Stock symbol (for filtering per-ticker scores).

        Returns:
            Dict with parsed articles and average sentiment, or empty dict.
        """
        feed = data.get("feed", [])
        if not isinstance(feed, list) or not feed:
            logger.debug("Alpha Vantage: no articles for %s", ticker)
            return {}

        articles: list[AlphaVantageNewsSentiment] = []
        total_sentiment = 0.0
        sentiment_count = 0
        ticker_upper = ticker.upper()

        for item in feed[:_MAX_ARTICLES]:
            if not isinstance(item, dict):
                continue
            parsed = self._parse_article(item, ticker_upper)
            if parsed is None:
                continue
            articles.append(parsed)

            # Use ticker-specific score for average if available
            score_for_avg = (
                parsed.ticker_sentiment_score
                if parsed.ticker_relevance > 0
                else parsed.overall_sentiment_score
            )
            total_sentiment += score_for_avg
            sentiment_count += 1

        if not articles:
            return {}

        avg_sentiment = total_sentiment / sentiment_count if sentiment_count > 0 else 0.0
        return {
            "alphavantage_articles": articles,
            "alphavantage_avg_sentiment": round(avg_sentiment, 4),
        }

    def _parse_article(
        self,
        item: dict[str, Any],
        ticker_upper: str,
    ) -> AlphaVantageNewsSentiment | None:
        """Parse a single news article from Alpha Vantage feed.

        Args:
            item: Raw article dict from the feed.
            ticker_upper: Uppercased ticker for matching per-ticker data.

        Returns:
            Parsed AlphaVantageNewsSentiment, or None on parse failure.
        """
        try:
            published_at = self._parse_av_timestamp(item.get("time_published", ""))
            overall_score = max(-1.0, min(1.0, float(item.get("overall_sentiment_score", 0.0))))
            overall_label = item.get("overall_sentiment_label", "")

            ticker_relevance, ticker_score, ticker_label = self._extract_ticker_sentiment(
                item.get("ticker_sentiment", []),
                ticker_upper,
            )

            return AlphaVantageNewsSentiment(
                title=item.get("title", ""),
                source=item.get("source", ""),
                url=item.get("url", ""),
                summary=item.get("summary", ""),
                published_at=published_at,
                overall_sentiment_score=overall_score,
                overall_sentiment_label=overall_label,
                ticker_relevance=ticker_relevance,
                ticker_sentiment_score=ticker_score,
                ticker_sentiment_label=ticker_label,
            )
        except (ValueError, TypeError):
            logger.debug("Alpha Vantage: failed to parse article: %s", item)
            return None

    @staticmethod
    def _extract_ticker_sentiment(
        ticker_sentiments: Any,
        ticker_upper: str,
    ) -> tuple[float, float, str]:
        """Extract per-ticker sentiment from the ticker_sentiment array.

        Args:
            ticker_sentiments: Raw ticker_sentiment list from API.
            ticker_upper: Uppercased ticker to match against.

        Returns:
            Tuple of (relevance, score, label) for the matching ticker,
            or (0.0, 0.0, "") if not found.
        """
        if not isinstance(ticker_sentiments, list):
            return 0.0, 0.0, ""

        for ts in ticker_sentiments:
            if not isinstance(ts, dict):
                continue
            if ts.get("ticker", "").upper() == ticker_upper:
                relevance = max(0.0, min(1.0, float(ts.get("relevance_score", 0.0))))
                score = max(-1.0, min(1.0, float(ts.get("ticker_sentiment_score", 0.0))))
                label = ts.get("ticker_sentiment_label", "")
                return relevance, score, label

        return 0.0, 0.0, ""

    @staticmethod
    def _parse_av_timestamp(time_str: str) -> datetime:
        """Parse Alpha Vantage timestamp (format: YYYYMMDDTHHMMSS).

        Args:
            time_str: Timestamp string from Alpha Vantage.

        Returns:
            Parsed datetime in UTC, or current UTC time on failure.
        """
        if not time_str:
            return datetime.now(UTC)
        try:
            return datetime.strptime(time_str[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            return datetime.now(UTC)
