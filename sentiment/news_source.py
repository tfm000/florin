"""
News sentiment source.

Aggregates financial news from free API tiers:
  - FMP (Financial Modeling Prep) stock news endpoint
  - Alpha Vantage News Sentiment endpoint (if configured)

Both provide headlines, sources, timestamps, and relevance scores.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from config.settings import Settings
from core.models import NewsArticle
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

FMP_NEWS_URL = "https://financialmodelingprep.com/api/v3/stock_news"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

MAX_ARTICLES = 15


class NewsSource(SentimentSource):
    """
    Fetches financial news from FMP and Alpha Vantage free tiers.

    Returns recent news articles mentioning the given ticker,
    with headline, source, and relevance scoring.
    """

    def __init__(self, settings: Settings) -> None:
        self._fmp_key = settings.fmp_api_key
        # Alpha Vantage key reuse — add to settings if needed
        self._av_key = ""  # Optional, not in settings yet

    @property
    def name(self) -> str:
        return "News"

    async def health_check(self) -> bool:
        if not self._fmp_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    FMP_NEWS_URL,
                    params={"apikey": self._fmp_key, "limit": 1},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch news articles for a ticker from available sources.

        Returns dict with key "articles": list[NewsArticle]
        """
        articles: list[NewsArticle] = []

        # FMP news (primary)
        if self._fmp_key:
            fmp_articles = await self._fetch_fmp_news(ticker)
            articles.extend(fmp_articles)

        # Alpha Vantage news (supplementary)
        if self._av_key:
            av_articles = await self._fetch_av_news(ticker)
            # Deduplicate by title similarity
            existing_titles = {a.title.lower()[:50] for a in articles}
            for article in av_articles:
                if article.title.lower()[:50] not in existing_titles:
                    articles.append(article)

        # Sort by published date, most recent first
        articles.sort(key=lambda a: a.published_at, reverse=True)

        return {"articles": articles[:MAX_ARTICLES]}

    async def _fetch_fmp_news(self, ticker: str) -> list[NewsArticle]:
        """Fetch news from FMP stock_news endpoint."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    FMP_NEWS_URL,
                    params={
                        "tickers": ticker,
                        "limit": MAX_ARTICLES,
                        "apikey": self._fmp_key,
                    },
                )

                if resp.status_code != 200:
                    logger.warning("FMP news returned %d", resp.status_code)
                    return []

                data = resp.json()
                if not isinstance(data, list):
                    return []

                articles = []
                for item in data:
                    article = self._parse_fmp_article(item)
                    if article:
                        articles.append(article)

                return articles

        except Exception:
            logger.exception("FMP news fetch failed for %s", ticker)
            return []

    async def _fetch_av_news(self, ticker: str) -> list[NewsArticle]:
        """Fetch news from Alpha Vantage News Sentiment endpoint."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    ALPHA_VANTAGE_URL,
                    params={
                        "function": "NEWS_SENTIMENT",
                        "tickers": ticker,
                        "limit": 10,
                        "apikey": self._av_key,
                    },
                )

                if resp.status_code != 200:
                    return []

                data = resp.json()
                articles = []
                for item in data.get("feed", []):
                    article = self._parse_av_article(item, ticker)
                    if article:
                        articles.append(article)

                return articles

        except Exception:
            logger.exception("Alpha Vantage news fetch failed for %s", ticker)
            return []

    def _parse_fmp_article(self, item: dict[str, Any]) -> NewsArticle | None:
        """Parse an FMP news item."""
        try:
            published_str = item.get("publishedDate", "")
            published_at = datetime.now(UTC)
            if published_str:
                try:
                    published_at = datetime.fromisoformat(
                        published_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            return NewsArticle(
                title=item.get("title", ""),
                source=item.get("site", ""),
                url=item.get("url", ""),
                summary=(item.get("text", "") or "")[:300],
                published_at=published_at,
                relevance_score=1.0,  # FMP doesn't provide relevance
            )
        except Exception:
            return None

    def _parse_av_article(
        self, item: dict[str, Any], ticker: str,
    ) -> NewsArticle | None:
        """Parse an Alpha Vantage news item."""
        try:
            time_str = item.get("time_published", "")
            published_at = datetime.now(UTC)
            if time_str:
                try:
                    published_at = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                except ValueError:
                    pass

            # Find relevance score for our ticker
            relevance = 0.0
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker") == ticker:
                    relevance = float(ts.get("relevance_score", 0.0))
                    break

            return NewsArticle(
                title=item.get("title", ""),
                source=item.get("source", ""),
                url=item.get("url", ""),
                summary=(item.get("summary", "") or "")[:300],
                published_at=published_at,
                relevance_score=relevance,
            )
        except Exception:
            return None
