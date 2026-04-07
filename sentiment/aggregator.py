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
    AlphaVantageNewsSentiment,
    NewsArticle,
    RedditPost,
    SECFiling,
    SentimentData,
    WebSearchResult,
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
        """Build a SentimentData object from merged source results.

        Extracts and type-validates data from each source, then
        assembles the unified SentimentData model.
        """
        reddit_data = merged.get("Reddit", {})
        aw_data = merged.get("ApeWisdom", {})
        av_data = merged.get("Alpha Vantage", {})
        sec_data = merged.get("SEC EDGAR", {})
        news_data = merged.get("News", {})
        ws_data = merged.get("Web Search", {})

        return SentimentData(
            ticker=ticker,
            collected_at=datetime.now(UTC),
            reddit_posts=_safe_list(reddit_data, "posts", RedditPost),
            reddit_mention_count=reddit_data.get("mention_count", 0),
            apewisdom_rank=aw_data.get("apewisdom_rank", 0),
            apewisdom_mentions=aw_data.get("apewisdom_mentions", 0),
            apewisdom_upvotes=aw_data.get("apewisdom_upvotes", 0),
            alphavantage_articles=_safe_list(av_data, "alphavantage_articles", AlphaVantageNewsSentiment),
            alphavantage_avg_sentiment=av_data.get("alphavantage_avg_sentiment", 0.0),
            sec_filings=_safe_list(sec_data, "filings", SECFiling),
            insider_buy_count=sec_data.get("insider_buys", 0),
            insider_sell_count=sec_data.get("insider_sells", 0),
            news_articles=_safe_list(news_data, "articles", NewsArticle),
            web_search_results=_safe_list(ws_data, "web_search_results", WebSearchResult),
            sources_queried=sources_queried,
            sources_succeeded=sources_succeeded,
            data_quality=_assess_quality(sources_queried, sources_succeeded),
        )


def _safe_list(data: dict[str, Any], key: str, expected_type: type) -> list:
    """Extract a list from source data with type safety.

    Returns the list only if the first element matches expected_type.
    Otherwise returns an empty list to prevent corrupt data propagation.

    Args:
        data: Source result dict.
        key: Key to extract.
        expected_type: Expected Pydantic model type for list elements.

    Returns:
        Validated list, or empty list on type mismatch.
    """
    items = data.get(key, [])
    if items and not isinstance(items[0], expected_type):
        return []
    return items


def _assess_quality(sources_queried: int, sources_succeeded: int) -> str:
    """Assess data quality based on source success ratio.

    Args:
        sources_queried: Total number of sources attempted.
        sources_succeeded: Number of sources that returned data.

    Returns:
        Quality string: "high", "medium", "low", or "insufficient".
    """
    if sources_succeeded == 0:
        return "insufficient"
    if sources_succeeded == 1:
        return "low"
    if sources_succeeded <= sources_queried // 2:
        return "medium"
    return "high"
