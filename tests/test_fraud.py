"""Tests for the fraud detector module."""

from datetime import UTC, datetime, timedelta

import pytest

from analysis.fraud_detector import FraudDetector
from core.models import (
    AlertSignal,
    FraudRisk,
    NewsArticle,
    RedditPost,
    SECFiling,
    SentimentData,
    StockTwitsMessage,
)


@pytest.fixture
def detector():
    return FraudDetector()


def _make_alert(
    ticker: str = "SCAM",
    price: float = 2.50,
    volume: int = 500_000,
    avg_volume: int = 50_000,
    change_pct: float = 15.0,
) -> AlertSignal:
    return AlertSignal(
        ticker=ticker,
        price=price,
        change_pct=change_pct,
        volume=volume,
        avg_volume=avg_volume,
    )


def _make_sentiment(
    reddit_posts: list | None = None,
    stocktwits_messages: list | None = None,
    sec_filings: list | None = None,
    news_articles: list | None = None,
) -> SentimentData:
    return SentimentData(
        ticker="SCAM",
        reddit_posts=reddit_posts or [],
        reddit_mention_count=len(reddit_posts) if reddit_posts else 0,
        stocktwits_messages=stocktwits_messages or [],
        stocktwits_bullish_count=sum(
            1 for m in (stocktwits_messages or []) if m.sentiment == "Bullish"
        ),
        stocktwits_bearish_count=sum(
            1 for m in (stocktwits_messages or []) if m.sentiment == "Bearish"
        ),
        sec_filings=sec_filings or [],
        news_articles=news_articles or [],
    )


class TestFraudDetector:
    """Tests for FraudDetector.assess()."""

    @pytest.mark.asyncio
    async def test_clean_stock_low_risk(self, detector):
        """Stock with normal volume, news, and filings should score low."""
        alert = _make_alert(volume=60_000, avg_volume=50_000)
        sentiment = _make_sentiment(
            sec_filings=[SECFiling(form_type="8-K", filed_date=datetime.now(UTC))],
            news_articles=[NewsArticle(title="Company announces earnings")],
        )
        result = await detector.assess(alert, sentiment)
        assert result.risk_level == FraudRisk.LOW
        assert result.score < 3.0

    @pytest.mark.asyncio
    async def test_volume_spike_no_news(self, detector):
        """Volume spike with no news or SEC filings should flag."""
        alert = _make_alert(volume=600_000, avg_volume=50_000)  # 12x
        sentiment = _make_sentiment()
        result = await detector.assess(alert, sentiment)
        assert any("Volume spike" in f for f in result.flags)
        assert any("no news" in f.lower() or "no SEC" in f.lower() for f in result.flags)

    @pytest.mark.asyncio
    async def test_volume_spike_with_news(self, detector):
        """Volume spike with news present should still flag but lower score."""
        alert = _make_alert(volume=600_000, avg_volume=50_000)
        sentiment = _make_sentiment(
            news_articles=[NewsArticle(title="Breaking news")],
        )
        result = await detector.assess(alert, sentiment)
        # Should flag but less severely
        assert any("Volume spike" in f for f in result.flags)
        assert result.score < 3.0

    @pytest.mark.asyncio
    async def test_new_reddit_accounts(self, detector):
        """Posts from new/low-karma accounts should flag."""
        now = datetime.now(UTC)
        posts = [
            RedditPost(
                subreddit="pennystocks", title=f"SCAM to the moon {i}",
                score=5, account_age_days=5, author_karma=10,
                created_at=now,
            )
            for i in range(4)
        ]
        alert = _make_alert(volume=50_000, avg_volume=50_000)
        sentiment = _make_sentiment(reddit_posts=posts)
        result = await detector.assess(alert, sentiment)
        assert any("new/low-karma" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_coordinated_posting(self, detector):
        """Many posts in a short window should flag as coordinated."""
        now = datetime.now(UTC)
        posts = [
            RedditPost(
                subreddit="pennystocks", title=f"Buy SCAM {i}",
                score=2, created_at=now + timedelta(minutes=i),
            )
            for i in range(6)  # 6 posts in 5 minutes
        ]
        alert = _make_alert(volume=50_000, avg_volume=50_000)
        sentiment = _make_sentiment(reddit_posts=posts)
        result = await detector.assess(alert, sentiment)
        assert any("Coordinated" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_sub_penny_price(self, detector):
        """Stocks under $1 should flag as high manipulation risk."""
        alert = _make_alert(price=0.05, volume=50_000, avg_volume=50_000)
        sentiment = _make_sentiment(
            sec_filings=[SECFiling(form_type="10-K", filed_date=datetime.now(UTC))],
        )
        result = await detector.assess(alert, sentiment)
        assert any("Sub-dime" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_sub_dollar_price(self, detector):
        """Stocks between $0.10 and $1 should flag but less severely."""
        alert = _make_alert(price=0.50, volume=50_000, avg_volume=50_000)
        sentiment = _make_sentiment(
            sec_filings=[SECFiling(form_type="10-K", filed_date=datetime.now(UTC))],
        )
        result = await detector.assess(alert, sentiment)
        assert any("Sub-penny" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_no_sec_filings(self, detector):
        """No SEC filings should flag."""
        alert = _make_alert(volume=50_000, avg_volume=50_000)
        sentiment = _make_sentiment()
        result = await detector.assess(alert, sentiment)
        assert any("No SEC filings" in f for f in result.flags)

    @pytest.mark.asyncio
    async def test_sentiment_mismatch(self, detector):
        """High social buzz with no fundamentals should flag."""
        msgs = [
            StockTwitsMessage(text=f"SCAM moon {i}", sentiment="Bullish")
            for i in range(25)
        ]
        alert = _make_alert(volume=50_000, avg_volume=50_000)
        sentiment = _make_sentiment(stocktwits_messages=msgs)
        result = await detector.assess(alert, sentiment)
        assert any("social buzz" in f.lower() for f in result.flags)

    @pytest.mark.asyncio
    async def test_critical_risk_level(self, detector):
        """Multiple red flags should produce CRITICAL risk level."""
        now = datetime.now(UTC)
        posts = [
            RedditPost(
                subreddit="pennystocks", title=f"SCAM {i}",
                score=1, account_age_days=3, author_karma=5,
                created_at=now + timedelta(minutes=i),
            )
            for i in range(8)
        ]
        alert = _make_alert(
            price=0.05, volume=1_000_000, avg_volume=10_000
        )
        sentiment = _make_sentiment(reddit_posts=posts)
        result = await detector.assess(alert, sentiment)
        assert result.risk_level in (FraudRisk.HIGH, FraudRisk.CRITICAL)
        assert result.score >= 5.0

    @pytest.mark.asyncio
    async def test_score_clamped_to_10(self, detector):
        """Score should never exceed 10."""
        now = datetime.now(UTC)
        posts = [
            RedditPost(
                subreddit="pennystocks", title=f"SCAM {i}",
                score=1, account_age_days=2, author_karma=1,
                created_at=now + timedelta(minutes=i),
            )
            for i in range(10)
        ]
        msgs = [
            StockTwitsMessage(text=f"moon {i}", sentiment="Bullish")
            for i in range(30)
        ]
        alert = _make_alert(price=0.01, volume=5_000_000, avg_volume=5_000)
        sentiment = _make_sentiment(reddit_posts=posts, stocktwits_messages=msgs)
        result = await detector.assess(alert, sentiment)
        assert result.score <= 10.0

    @pytest.mark.asyncio
    async def test_confidence_scales_with_data(self, detector):
        """Confidence should increase with more data points."""
        alert = _make_alert(volume=50_000, avg_volume=50_000)

        # Empty sentiment = low confidence
        empty = _make_sentiment()
        r1 = await detector.assess(alert, empty)

        # Rich sentiment = higher confidence
        rich = _make_sentiment(
            reddit_posts=[RedditPost(subreddit="s", title=f"t{i}", score=1) for i in range(10)],
            stocktwits_messages=[StockTwitsMessage(text=f"m{i}") for i in range(10)],
            sec_filings=[SECFiling(form_type="4", filed_date=datetime.now(UTC))],
            news_articles=[NewsArticle(title=f"n{i}") for i in range(3)],
        )
        r2 = await detector.assess(alert, rich)

        assert r2.confidence > r1.confidence
