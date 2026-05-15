"""Tests for sentiment sources and aggregator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from core.models import (
    AlphaVantageNewsSentiment,
    NewsArticle,
    RedditPost,
    SECFiling,
    SentimentData,
)
from sentiment.aggregator import SentimentAggregator
from sentiment.alphavantage_source import AlphaVantageSource
from sentiment.apewisdom_source import ApeWisdomSource
from sentiment.base import SentimentSource

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
        sources: list[SentimentSource] = [
            MockSource(
                "Reddit",
                {
                    "posts": [
                        RedditPost(subreddit="pennystocks", title="TEST to the moon", score=50)
                    ],
                    "mention_count": 5,
                },
            ),
            MockSource(
                "ApeWisdom",
                {
                    "apewisdom_rank": 3,
                    "apewisdom_mentions": 42,
                    "apewisdom_upvotes": 1200,
                },
            ),
            MockSource(
                "SEC EDGAR",
                {
                    "filings": [
                        SECFiling(
                            form_type="4", filed_date=datetime.now(UTC), transaction_type="Purchase"
                        )
                    ],
                    "insider_buys": 1,
                    "insider_sells": 0,
                },
            ),
            MockSource(
                "News",
                {
                    "articles": [NewsArticle(title="TEST Corp announces partnership")],
                },
            ),
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
        assert result.apewisdom_mentions == 42
        assert result.insider_buy_count == 1
        assert len(result.news_articles) == 1

    @pytest.mark.asyncio
    async def test_partial_failure(self) -> None:
        sources: list[SentimentSource] = [
            MockSource(
                "Reddit",
                {
                    "posts": [RedditPost(subreddit="pennystocks", title="TEST", score=10)],
                    "mention_count": 1,
                },
            ),
            MockSource("ApeWisdom", should_fail=True),
            MockSource("SEC EDGAR", should_fail=True),
            MockSource(
                "News",
                {
                    "articles": [NewsArticle(title="Some news")],
                },
            ),
        ]

        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")

        assert result.sources_queried == 4
        assert result.sources_succeeded == 2
        assert result.data_quality == "medium"

        # Failed sources should have empty data
        assert result.apewisdom_mentions == 0
        assert len(result.sec_filings) == 0

        # Successful sources should have data
        assert result.reddit_mention_count == 1
        assert len(result.news_articles) == 1

    @pytest.mark.asyncio
    async def test_all_sources_fail(self) -> None:
        sources: list[SentimentSource] = [
            MockSource("Reddit", should_fail=True),
            MockSource("ApeWisdom", should_fail=True),
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
        sources: list[SentimentSource] = [
            MockSource("Reddit", should_fail=False),
            MockSource("ApeWisdom", should_fail=True),
        ]

        agg = SentimentAggregator(sources)
        health = await agg.health_check()

        assert health["Reddit"] is True
        assert health["ApeWisdom"] is False

    def test_source_names(self) -> None:
        sources: list[SentimentSource] = [
            MockSource("Reddit"),
            MockSource("ApeWisdom"),
        ]
        agg = SentimentAggregator(sources)
        assert agg.source_names == ["Reddit", "ApeWisdom"]

    @pytest.mark.asyncio
    async def test_single_source_gives_low_quality(self) -> None:
        sources: list[SentimentSource] = [
            MockSource("Reddit", {"posts": [], "mention_count": 0}),
            MockSource("ApeWisdom", should_fail=True),
            MockSource("SEC EDGAR", should_fail=True),
        ]

        agg = SentimentAggregator(sources)
        result = await agg.fetch("TEST")

        assert result.sources_succeeded == 1
        assert result.data_quality == "low"


# =============================================================================
# ApeWisdom source tests
# =============================================================================


class TestApeWisdomSource:
    def test_always_configured(self) -> None:
        source = ApeWisdomSource()
        assert source.configured is True
        assert source.name == "ApeWisdom"

    @pytest.mark.asyncio
    async def test_fetch_ticker_found(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {
                        "ticker": "AAPL",
                        "rank": 1,
                        "mentions": "500",
                        "upvotes": "12000",
                        "rank_24h_ago": "2",
                        "mentions_24h_ago": "450",
                    },
                    {
                        "ticker": "TSLA",
                        "rank": 2,
                        "mentions": "300",
                        "upvotes": "8000",
                        "rank_24h_ago": "1",
                        "mentions_24h_ago": "350",
                    },
                ],
            },
            request=httpx.Request("GET", "https://apewisdom.io/api/v1.0/filter/all-stocks"),
        )

        with patch("sentiment.apewisdom_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = ApeWisdomSource()
            result = await source.fetch("AAPL")

        assert result["apewisdom_rank"] == 1
        assert result["apewisdom_mentions"] == 500
        assert result["apewisdom_upvotes"] == 12000

    @pytest.mark.asyncio
    async def test_fetch_ticker_not_found(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {
                        "ticker": "AAPL",
                        "rank": 1,
                        "mentions": "100",
                        "upvotes": "5000",
                        "rank_24h_ago": "1",
                        "mentions_24h_ago": "90",
                    }
                ]
            },
            request=httpx.Request("GET", "https://apewisdom.io/api/v1.0/filter/all-stocks"),
        )

        with patch("sentiment.apewisdom_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = ApeWisdomSource()
            result = await source.fetch("OBSCURE")

        assert result["apewisdom_rank"] == 0
        assert result["apewisdom_mentions"] == 0

    @pytest.mark.asyncio
    async def test_fetch_api_error(self) -> None:
        mock_response = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("GET", "https://apewisdom.io/api/v1.0/filter/all-stocks"),
        )

        with patch("sentiment.apewisdom_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = ApeWisdomSource()
            # Should return stale cache (empty since first call)
            result = await source.fetch("AAPL")

        # Empty dict means no stale cache and API failed
        assert result == {"apewisdom_rank": 0, "apewisdom_mentions": 0, "apewisdom_upvotes": 0}

    @pytest.mark.asyncio
    async def test_fetch_timeout(self) -> None:
        with patch("sentiment.apewisdom_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = ApeWisdomSource()
            result = await source.fetch("AAPL")

        assert result == {}

    @pytest.mark.asyncio
    async def test_stale_cache_returned_on_failure(self) -> None:
        """After a successful fetch, a subsequent API failure returns stale cache."""
        success_response = httpx.Response(
            200,
            json={
                "results": [
                    {
                        "ticker": "AAPL",
                        "rank": 1,
                        "mentions": "100",
                        "upvotes": "5000",
                        "rank_24h_ago": "2",
                        "mentions_24h_ago": "90",
                    }
                ]
            },
            request=httpx.Request("GET", "https://apewisdom.io/api/v1.0/filter/all-stocks"),
        )
        error_response = httpx.Response(
            500,
            text="Server Error",
            request=httpx.Request("GET", "https://apewisdom.io/api/v1.0/filter/all-stocks"),
        )

        source = ApeWisdomSource()

        # First call: success — populates cache
        with patch("sentiment.apewisdom_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=success_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result1 = await source.fetch("AAPL")

        assert result1["apewisdom_rank"] == 1

        # Expire the cache manually
        source._cache_time = 0.0

        # Second call: API fails — should still return stale cached data
        with patch("sentiment.apewisdom_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result2 = await source.fetch("AAPL")

        # Stale cache should still return data
        assert result2["apewisdom_rank"] == 1
        assert result2["apewisdom_mentions"] == 100


# =============================================================================
# Alpha Vantage source tests
# =============================================================================


class TestAlphaVantageSource:
    def test_not_configured_without_key(self) -> None:
        source = AlphaVantageSource()
        assert source.configured is False
        assert source.name == "Alpha Vantage"

    def test_configured_with_key(self) -> None:
        source = AlphaVantageSource(api_key="test-key")
        assert source.configured is True

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_without_key(self) -> None:
        source = AlphaVantageSource()
        result = await source.fetch("AAPL")
        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_success(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "feed": [
                    {
                        "title": "Apple Reports Record Quarter",
                        "source": "Reuters",
                        "url": "https://example.com/article",
                        "summary": "Apple beats expectations",
                        "time_published": "20260401T120000",
                        "overall_sentiment_score": 0.35,
                        "overall_sentiment_label": "Somewhat-Bullish",
                        "ticker_sentiment": [
                            {
                                "ticker": "AAPL",
                                "relevance_score": "0.95",
                                "ticker_sentiment_score": "0.42",
                                "ticker_sentiment_label": "Bullish",
                            }
                        ],
                    }
                ],
            },
            request=httpx.Request("GET", "https://www.alphavantage.co/query"),
        )

        with patch("sentiment.alphavantage_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = AlphaVantageSource(api_key="test-key")
            result = await source.fetch("AAPL")

        assert "alphavantage_articles" in result
        assert len(result["alphavantage_articles"]) == 1
        article = result["alphavantage_articles"][0]
        assert article.title == "Apple Reports Record Quarter"
        assert article.ticker_sentiment_score == 0.42
        assert article.ticker_sentiment_label == "Bullish"
        assert result["alphavantage_avg_sentiment"] == 0.42

    @pytest.mark.asyncio
    async def test_fetch_empty_feed(self) -> None:
        mock_response = httpx.Response(
            200,
            json={"feed": []},
            request=httpx.Request("GET", "https://www.alphavantage.co/query"),
        )

        with patch("sentiment.alphavantage_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = AlphaVantageSource(api_key="test-key")
            result = await source.fetch("AAPL")

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_api_error_in_json(self) -> None:
        mock_response = httpx.Response(
            200,
            json={"Error Message": "Invalid API call"},
            request=httpx.Request("GET", "https://www.alphavantage.co/query"),
        )

        with patch("sentiment.alphavantage_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = AlphaVantageSource(api_key="bad-key")
            result = await source.fetch("AAPL")

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_rate_limit_note(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "Note": (
                    "Thank you for using Alpha Vantage! Our standard API rate "
                    "limit is 25 requests per day."
                )
            },
            request=httpx.Request("GET", "https://www.alphavantage.co/query"),
        )

        with patch("sentiment.alphavantage_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = AlphaVantageSource(api_key="test-key")
            result = await source.fetch("AAPL")

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_timeout(self) -> None:
        with patch("sentiment.alphavantage_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            source = AlphaVantageSource(api_key="test-key")
            result = await source.fetch("AAPL")

        assert result == {}

    def test_parse_av_timestamp(self) -> None:
        ts = AlphaVantageSource._parse_av_timestamp("20260401T120000")
        assert ts.year == 2026
        assert ts.month == 4
        assert ts.day == 1
        assert ts.hour == 12

    def test_parse_av_timestamp_invalid(self) -> None:
        ts = AlphaVantageSource._parse_av_timestamp("not-a-date")
        # Should return current time (not crash)
        assert ts.tzinfo is not None

    def test_extract_ticker_sentiment_found(self) -> None:
        sentiments = [
            {
                "ticker": "AAPL",
                "relevance_score": "0.9",
                "ticker_sentiment_score": "0.5",
                "ticker_sentiment_label": "Bullish",
            },
            {
                "ticker": "MSFT",
                "relevance_score": "0.3",
                "ticker_sentiment_score": "0.1",
                "ticker_sentiment_label": "Neutral",
            },
        ]
        rel, score, label = AlphaVantageSource._extract_ticker_sentiment(sentiments, "AAPL")
        assert rel == 0.9
        assert score == 0.5
        assert label == "Bullish"

    def test_extract_ticker_sentiment_not_found(self) -> None:
        sentiments = [
            {
                "ticker": "MSFT",
                "relevance_score": "0.3",
                "ticker_sentiment_score": "0.1",
                "ticker_sentiment_label": "Neutral",
            }
        ]
        rel, score, label = AlphaVantageSource._extract_ticker_sentiment(sentiments, "AAPL")
        assert rel == 0.0
        assert score == 0.0
        assert label == ""


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
            apewisdom_rank=5,
            apewisdom_mentions=42,
            apewisdom_upvotes=1200,
            alphavantage_articles=[
                AlphaVantageNewsSentiment(
                    title="Big news",
                    source="Reuters",
                    ticker_sentiment_label="Bullish",
                ),
            ],
            alphavantage_avg_sentiment=0.25,
            sec_filings=[SECFiling(form_type="4", filed_date=datetime.now(UTC))],
            insider_buy_count=2,
            insider_sell_count=0,
            news_articles=[NewsArticle(title="Big news", source="Reuters")],
        )

        summary = data.to_summary()
        assert "Reddit: 5 mentions" in summary
        assert "ApeWisdom: rank #5" in summary
        assert "Alpha Vantage" in summary
        assert "2 insider buys" in summary
        assert "Reuters" in summary
