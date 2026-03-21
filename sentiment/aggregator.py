"""
Sentiment aggregator — orchestrates all sentiment sources.

Runs all sources concurrently via asyncio.gather(), handles partial
failures gracefully, and combines results into a unified SentimentData object.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from core.models import (
    NewsArticle,
    RedditPost,
    SECFiling,
    SentimentData,
    StockTwitsMessage,
)
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Timeout for each individual source
SOURCE_TIMEOUT_SECONDS = 30.0


class SentimentAggregator:
    """
    Orchestrates all sentiment sources and merges results.

    Each source is queried concurrently. If a source fails or times out,
    the remaining sources' data is still used. The aggregator tracks
    how many sources succeeded for data quality assessment.
    """

    def __init__(self, sources: list[SentimentSource]) -> None:
        self._sources = sources

    @property
    def source_names(self) -> list[str]:
        return [s.name for s in self._sources]

    async def fetch(self, ticker: str, company_name: str = "") -> SentimentData:
        """
        Fetch sentiment from all sources concurrently and merge.

        Returns a SentimentData object even if all sources fail
        (with appropriate data quality markers).
        """
        # Run all sources concurrently with individual timeouts
        tasks = [
            self._fetch_with_timeout(source, ticker, company_name)
            for source in self._sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        sources_queried = len(self._sources)
        sources_succeeded = 0
        merged: dict[str, Any] = {}

        for source, result in zip(self._sources, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Sentiment source %s failed: %s", source.name, result
                )
                continue

            if isinstance(result, dict) and result:
                merged[source.name] = result
                sources_succeeded += 1

        # Build SentimentData from merged results
        sentiment = self._build_sentiment_data(
            ticker, merged, sources_queried, sources_succeeded,
        )

        logger.info(
            "Sentiment for %s: %d/%d sources succeeded (quality: %s)",
            ticker, sources_succeeded, sources_queried, sentiment.data_quality,
        )

        return sentiment

    async def fetch_filtered(
        self, ticker: str, company_name: str = "", source_names: list[str] | None = None,
    ) -> SentimentData:
        """Fetch sentiment from a named subset of sources."""
        if source_names is None:
            return await self.fetch(ticker, company_name)
        filtered = [s for s in self._sources if s.name in source_names]
        if not filtered:
            return SentimentData(
                ticker=ticker,
                sources_queried=0,
                sources_succeeded=0,
                data_quality="insufficient",
            )
        temp = SentimentAggregator(filtered)
        return await temp.fetch(ticker, company_name)

    async def health_check(self) -> dict[str, bool]:
        """Check health of all sources."""
        results = {}
        for source in self._sources:
            try:
                results[source.name] = await asyncio.wait_for(
                    source.health_check(), timeout=10.0
                )
            except Exception:
                results[source.name] = False
        return results

    async def _fetch_with_timeout(
        self, source: SentimentSource, ticker: str, company_name: str,
    ) -> dict[str, Any]:
        """Fetch from a single source with timeout."""
        try:
            return await asyncio.wait_for(
                source.fetch(ticker, company_name),
                timeout=SOURCE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Sentiment source %s timed out for %s", source.name, ticker)
            return {}

    def _build_sentiment_data(
        self,
        ticker: str,
        merged: dict[str, dict[str, Any]],
        sources_queried: int,
        sources_succeeded: int,
    ) -> SentimentData:
        """Build a SentimentData object from merged source results."""
        # Reddit
        reddit_data = merged.get("Reddit", {})
        reddit_posts = reddit_data.get("posts", [])
        if reddit_posts and not isinstance(reddit_posts[0], RedditPost):
            reddit_posts = []  # Safety check

        # StockTwits
        st_data = merged.get("StockTwits", {})
        st_messages = st_data.get("messages", [])
        if st_messages and not isinstance(st_messages[0], StockTwitsMessage):
            st_messages = []

        # SEC EDGAR
        sec_data = merged.get("SEC EDGAR", {})
        sec_filings = sec_data.get("filings", [])
        if sec_filings and not isinstance(sec_filings[0], SECFiling):
            sec_filings = []

        # News
        news_data = merged.get("News", {})
        news_articles = news_data.get("articles", [])
        if news_articles and not isinstance(news_articles[0], NewsArticle):
            news_articles = []

        # Determine data quality
        if sources_succeeded == 0:
            quality = "insufficient"
        elif sources_succeeded == 1:
            quality = "low"
        elif sources_succeeded <= sources_queried // 2:
            quality = "medium"
        else:
            quality = "high"

        return SentimentData(
            ticker=ticker,
            collected_at=datetime.now(UTC),
            # Reddit
            reddit_posts=reddit_posts,
            reddit_mention_count=reddit_data.get("mention_count", 0),
            # StockTwits
            stocktwits_messages=st_messages,
            stocktwits_bullish_count=st_data.get("bullish_count", 0),
            stocktwits_bearish_count=st_data.get("bearish_count", 0),
            # SEC
            sec_filings=sec_filings,
            insider_buy_count=sec_data.get("insider_buys", 0),
            insider_sell_count=sec_data.get("insider_sells", 0),
            # News
            news_articles=news_articles,
            # Metadata
            sources_queried=sources_queried,
            sources_succeeded=sources_succeeded,
            data_quality=quality,
        )
