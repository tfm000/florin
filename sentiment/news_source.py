"""
News sentiment source.

Aggregates financial news from:
  - yfinance (Yahoo Finance news for ticker)
  - Alpha Vantage News Sentiment endpoint (if configured)
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

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

MAX_ARTICLES = 15


class NewsSource(SentimentSource):
    """
    Fetches financial news from yfinance and Alpha Vantage free tiers.

    Returns recent news articles mentioning the given ticker,
    with headline, source, and relevance scoring.
    """

    def __init__(self, settings: Settings) -> None:
        # Alpha Vantage key reuse — add to settings if needed
        self._av_key = ""  # Optional, not in settings yet

    @property
    def name(self) -> str:
        return "News"

    async def health_check(self) -> bool:
        # yfinance is always available (no API key needed)
        return True

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch news articles for a ticker from available sources.

        Returns dict with key "articles": list[NewsArticle]
        """
        articles: list[NewsArticle] = []

        # yfinance news (primary)
        yf_articles = await self._fetch_yfinance_news(ticker)
        articles.extend(yf_articles)

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

    async def _fetch_yfinance_news(self, ticker: str) -> list[NewsArticle]:
        """Fetch news from yfinance."""
        import asyncio
        import yfinance as yf

        def _get() -> list[NewsArticle]:
            try:
                t = yf.Ticker(ticker)
                news = t.news or []
                articles = []
                for item in news:
                    content = item.get("content", {}) if isinstance(item, dict) else {}
                    title = content.get("title") or item.get("title", "")
                    if not title:
                        continue

                    pub_time = content.get("pubDate") or item.get("providerPublishTime", "")
                    published_at = datetime.now(UTC)
                    if isinstance(pub_time, (int, float)):
                        published_at = datetime.fromtimestamp(pub_time, tz=UTC)
                    elif isinstance(pub_time, str) and pub_time:
                        try:
                            published_at = datetime.fromisoformat(pub_time.replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    articles.append(NewsArticle(
                        title=title,
                        source=content.get("provider", {}).get("displayName", "")
                            or item.get("publisher", ""),
                        url=content.get("canonicalUrl", {}).get("url", "")
                            or item.get("link", ""),
                        summary=(content.get("summary", "") or "")[:300],
                        published_at=published_at,
                        relevance_score=1.0,
                    ))
                return articles[:MAX_ARTICLES]
            except Exception:
                logger.exception("yfinance news fetch failed for %s", ticker)
                return []

        return await asyncio.to_thread(_get)

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
