"""
Fraud risk detector — pump-and-dump / manipulation scoring.

Combines rule-based heuristics with sentiment data analysis to
produce a FraudRiskScore for each stock alert.

This score feeds into every LLM analysis prompt as additional context.

Signals checked:
  - Volume spike (>10x average) with no news
  - Reddit/StockTwits posts from new/low-karma accounts
  - No SEC filings in 90+ days
  - Sub-penny price (<$1) — highest manipulation risk
  - Coordinated posting patterns
  - Sentiment vs. fundamentals mismatch
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from config.constants import (
    FRAUD_COORDINATED_POST_THRESHOLD,
    FRAUD_COORDINATED_POST_WINDOW_MINUTES,
    FRAUD_NO_FILING_DAYS,
    FRAUD_REDDIT_MIN_ACCOUNT_AGE_DAYS,
    FRAUD_REDDIT_MIN_KARMA,
    FRAUD_VOLUME_SPIKE_MULTIPLIER,
)
from core.models import (
    AlertSignal,
    FraudRisk,
    FraudRiskScore,
    SentimentData,
)

logger = logging.getLogger(__name__)


class FraudDetector:
    """
    Rule-based fraud risk scoring.

    Analyses an alert and its sentiment data for pump-and-dump indicators.
    Returns a FraudRiskScore that feeds into LLM analysis prompts.
    """

    async def assess(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
    ) -> FraudRiskScore:
        """
        Assess fraud risk for a stock alert.

        Returns FraudRiskScore with score (0-10), risk level, and flags.
        """
        flags: list[str] = []
        score = 0.0

        # 1. Volume spike with no news
        score += self._check_volume_spike(alert, sentiment, flags)

        # 2. New/low-karma Reddit accounts
        score += self._check_reddit_accounts(sentiment, flags)

        # 3. Coordinated posting patterns
        score += self._check_coordinated_posts(sentiment, flags)

        # 4. No recent SEC filings
        score += self._check_sec_filings(sentiment, flags)

        # 5. Sub-penny price
        score += self._check_sub_penny(alert, flags)

        # 6. Extreme sentiment with no fundamentals
        score += self._check_sentiment_mismatch(alert, sentiment, flags)

        # Clamp score to 0-10
        score = max(0.0, min(10.0, score))

        # Determine risk level
        if score >= 7.0:
            risk_level = FraudRisk.CRITICAL
        elif score >= 5.0:
            risk_level = FraudRisk.HIGH
        elif score >= 3.0:
            risk_level = FraudRisk.MEDIUM
        else:
            risk_level = FraudRisk.LOW

        # Confidence based on how many data points we have
        data_points = (
            len(sentiment.reddit_posts) +
            len(sentiment.stocktwits_messages) +
            len(sentiment.sec_filings) +
            len(sentiment.news_articles)
        )
        confidence = min(1.0, data_points / 20)  # Max confidence at 20+ data points

        result = FraudRiskScore(
            ticker=alert.ticker,
            score=round(score, 1),
            risk_level=risk_level,
            flags=flags,
            confidence=round(confidence, 2),
            assessed_at=datetime.utcnow(),
        )

        if flags:
            logger.info(
                "Fraud assessment for %s: %s (%.1f/10) — %d flags",
                alert.ticker, risk_level.value, score, len(flags),
            )

        return result

    def _check_volume_spike(
        self, alert: AlertSignal, sentiment: SentimentData, flags: list[str],
    ) -> float:
        """Check for suspicious volume spike with no corresponding news."""
        if alert.avg_volume <= 0:
            return 0.0

        volume_ratio = alert.volume / alert.avg_volume
        if volume_ratio >= FRAUD_VOLUME_SPIKE_MULTIPLIER:
            has_news = len(sentiment.news_articles) > 0
            has_sec = len(sentiment.sec_filings) > 0

            if not has_news and not has_sec:
                flags.append(
                    f"Volume spike: {volume_ratio:.0f}x average with no news or SEC filings"
                )
                return min(3.0, volume_ratio / 5)
            else:
                flags.append(
                    f"Volume spike: {volume_ratio:.0f}x average (news/filings present)"
                )
                return 0.5

        return 0.0

    def _check_reddit_accounts(
        self, sentiment: SentimentData, flags: list[str],
    ) -> float:
        """Check for posts from new/low-karma Reddit accounts."""
        if not sentiment.reddit_posts:
            return 0.0

        suspicious_count = 0
        for post in sentiment.reddit_posts:
            if (post.account_age_days > 0 and
                    post.account_age_days < FRAUD_REDDIT_MIN_ACCOUNT_AGE_DAYS):
                suspicious_count += 1
            elif (post.author_karma > 0 and
                  post.author_karma < FRAUD_REDDIT_MIN_KARMA):
                suspicious_count += 1

        if suspicious_count > 0:
            ratio = suspicious_count / len(sentiment.reddit_posts)
            if ratio > 0.5:
                flags.append(
                    f"{suspicious_count}/{len(sentiment.reddit_posts)} Reddit posts "
                    f"from new/low-karma accounts (>{ratio:.0%})"
                )
                return 2.5
            elif suspicious_count >= 2:
                flags.append(
                    f"{suspicious_count} Reddit posts from new/low-karma accounts"
                )
                return 1.0

        return 0.0

    def _check_coordinated_posts(
        self, sentiment: SentimentData, flags: list[str],
    ) -> float:
        """Check for coordinated posting patterns (many posts in short window)."""
        if len(sentiment.reddit_posts) < FRAUD_COORDINATED_POST_THRESHOLD:
            return 0.0

        # Check if many posts appeared within the coordinated window
        window = timedelta(minutes=FRAUD_COORDINATED_POST_WINDOW_MINUTES)
        timestamps = sorted(p.created_at for p in sentiment.reddit_posts)

        for i in range(len(timestamps) - FRAUD_COORDINATED_POST_THRESHOLD + 1):
            window_posts = sum(
                1 for t in timestamps[i:]
                if t - timestamps[i] <= window
            )
            if window_posts >= FRAUD_COORDINATED_POST_THRESHOLD:
                flags.append(
                    f"Coordinated posting: {window_posts} posts within "
                    f"{FRAUD_COORDINATED_POST_WINDOW_MINUTES} minutes"
                )
                return 2.0

        return 0.0

    def _check_sec_filings(
        self, sentiment: SentimentData, flags: list[str],
    ) -> float:
        """Check for absence of recent SEC filings."""
        if not sentiment.sec_filings:
            flags.append(
                f"No SEC filings found in last {FRAUD_NO_FILING_DAYS} days"
            )
            return 1.5

        return 0.0

    def _check_sub_penny(
        self, alert: AlertSignal, flags: list[str],
    ) -> float:
        """Sub-penny stocks (<$1) have the highest manipulation risk."""
        if alert.price < 0.10:
            flags.append(f"Sub-dime stock: ${alert.price:.4f} — extreme manipulation risk")
            return 3.0
        elif alert.price < 1.00:
            flags.append(f"Sub-penny stock: ${alert.price:.4f} — high manipulation risk")
            return 1.5

        return 0.0

    def _check_sentiment_mismatch(
        self, alert: AlertSignal, sentiment: SentimentData, flags: list[str],
    ) -> float:
        """Check for extreme social sentiment with no fundamental backing."""
        total_social = (
            sentiment.reddit_mention_count +
            sentiment.stocktwits_bullish_count +
            sentiment.stocktwits_bearish_count
        )
        has_fundamentals = (
            len(sentiment.sec_filings) > 0 or
            len(sentiment.news_articles) > 0
        )

        if total_social > 20 and not has_fundamentals:
            flags.append(
                f"High social buzz ({total_social} mentions) with no "
                f"fundamental news or SEC filings"
            )
            return 2.0

        return 0.0
