"""Tests for Phase 3: Sentiment sources and aggregator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from core.models import (
    NewsArticle,
    RedditPost,
    SECFiling,
    SentimentData,
    StockTwitsMessage,
)
from sentiment.aggregator import SentimentAggregator
from sentiment.base import SentimentSource
from sentiment.stocktwits_source import StockTwitsSource


# =============================================================================
# Mock source for testing the aggregator
# =============================================================================


class MockSource(SentimentSource):
    """Configurable mock sentiment source for testing."""

    def __init__(
        self,
        source_name: str,
        result: dict[str, Any] | None = None,
        should_fail: bool = False,
    ) -> None:
        self._name = source_name
        self._result = result or {}
        self._should_fail = should_fail

    @property
    def name(self) -> str:
        return self._name

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        if self._should_fail:
            raise ConnectionError(f"{self._name} failed")
        return self._result

    async def health_check(self) -> bool:
        return not self._should_fail


# =============================================================================
# Aggregator tests
# =============================================================================


class TestSentimentAggregator:
    @pytest.mark.asyncio
    async def test_all_sources_succeed(self) -> None:
        sources = [
            MockSource("Reddit", {
                "posts": [RedditPost(subreddit="pennystocks", title="TEST to the moon", score=50)],
                "mention_count": 5,
            }),
            MockSource("StockTwits", {
                "messages": [StockTwitsMessage(text="Bullish on TEST", sentiment="Bullish")],
                "bullish_count": 3,
                "bearish_count": 1,
            }),
            MockSource("SEC EDGAR", {
                "filings": [SECFiling(form_type="4", filed_date=datetime.now(UTC),
                                      transaction_type="Purchase")],
                "insider_buys": 1,
                "insider_sells": 0,
            }),
            MockSource("News", {
                "articles": [NewsArticle(title="TEST Corp announces partnership")],
            }),
        ]

        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST", "Test Corp")

        assert isinstance(result, SentimentData)
        assert result.ticker == "TEST"
        assert result.sources_queried == 4
        assert result.sources_succeeded == 4
        assert result.data_quality == "high"

        assert result.reddit_mention_count == 5
        assert len(result.reddit_posts) == 1
        assert result.stocktwits_bullish_count == 3
        assert result.insider_buy_count == 1
        assert len(result.news_articles) == 1

    @pytest.mark.asyncio
    async def test_partial_failure(self) -> None:
        sources = [
            MockSource("Reddit", {
                "posts": [RedditPost(subreddit="pennystocks", title="TEST", score=10)],
                "mention_count": 1,
            }),
            MockSource("StockTwits", should_fail=True),
            MockSource("SEC EDGAR", should_fail=True),
            MockSource("News", {
                "articles": [NewsArticle(title="Some news")],
            }),
        ]

        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")

        assert result.sources_queried == 4
        assert result.sources_succeeded == 2
        assert result.data_quality == "medium"

        # Failed sources should have empty data
        assert len(result.stocktwits_messages) == 0
        assert len(result.sec_filings) == 0

        # Successful sources should have data
        assert result.reddit_mention_count == 1
        assert len(result.news_articles) == 1

    @pytest.mark.asyncio
    async def test_all_sources_fail(self) -> None:
        sources = [
            MockSource("Reddit", should_fail=True),
            MockSource("StockTwits", should_fail=True),
        ]

        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")

        assert result.sources_succeeded == 0
        assert result.data_quality == "insufficient"

    @pytest.mark.asyncio
    async def test_empty_sources(self) -> None:
        agg = SentimentAggregator([])
        result = await agg.fetch("TEST")

        assert result.ticker == "TEST"
        assert result.sources_queried == 0
        assert result.sources_succeeded == 0

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        sources = [
            MockSource("Reddit", should_fail=False),
            MockSource("StockTwits", should_fail=True),
        ]

        agg = SentimentAggregator(sources)
        health = await agg.health_check()

        assert health["Reddit"] is True
        assert health["StockTwits"] is False

    def test_source_names(self) -> None:
        sources = [
            MockSource("Reddit"),
            MockSource("StockTwits"),
        ]
        agg = SentimentAggregator(sources)
        assert agg.source_names == ["Reddit", "StockTwits"]

    @pytest.mark.asyncio
    async def test_single_source_gives_low_quality(self) -> None:
        sources = [
            MockSource("Reddit", {"posts": [], "mention_count": 0}),
            MockSource("StockTwits", should_fail=True),
            MockSource("SEC EDGAR", should_fail=True),
        ]

        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")

        assert result.sources_succeeded == 1
        assert result.data_quality == "low"


# =============================================================================
# StockTwits source tests (parsing)
# =============================================================================


class TestStockTwitsSource:
    def test_parse_message_with_sentiment(self) -> None:
        source = StockTwitsSource()
        msg = source._parse_message({
            "body": "Going long on TEST",
            "entities": {"sentiment": {"basic": "Bullish"}},
            "likes": {"total": 5},
            "created_at": "2024-06-15T10:30:00Z",
        })

        assert msg is not None
        assert msg.text == "Going long on TEST"
        assert msg.sentiment == "Bullish"
        assert msg.likes == 5

    def test_parse_message_no_sentiment(self) -> None:
        source = StockTwitsSource()
        msg = source._parse_message({
            "body": "Just watching TEST",
            "entities": {},
        })

        assert msg is not None
        assert msg.sentiment is None

    def test_parse_message_invalid(self) -> None:
        source = StockTwitsSource()
        msg = source._parse_message({"invalid": True})
        # Should still return something (body defaults to "")
        assert msg is not None


# =============================================================================
# News source tests (parsing)
# =============================================================================


# =============================================================================
# SentimentData model tests
# =============================================================================


class TestSentimentData:
    def test_to_summary(self) -> None:
        data = SentimentData(
            ticker="TEST",
            reddit_posts=[
                RedditPost(subreddit="pennystocks", title="TEST looking good", score=100),
            ],
            reddit_mention_count=5,
            stocktwits_messages=[
                StockTwitsMessage(text="Bullish", sentiment="Bullish"),
            ],
            stocktwits_bullish_count=3,
            stocktwits_bearish_count=1,
            sec_filings=[SECFiling(form_type="4", filed_date=datetime.now(UTC))],
            insider_buy_count=2,
            insider_sell_count=0,
            news_articles=[NewsArticle(title="Big news", source="Reuters")],
        )

        summary = data.to_summary()
        assert "Reddit: 5 mentions" in summary
        assert "3 bullish" in summary
        assert "2 insider buys" in summary
        assert "Reuters" in summary
