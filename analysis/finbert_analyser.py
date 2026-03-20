"""
FinBERT analyser — fast batch sentiment scoring.

Uses ProsusAI/finbert via HuggingFace Transformers for rapid
sentiment classification of text snippets. Outputs pos/neg/neutral
percentages rather than full analytical reports.

This is used as a fast preprocessing step, not a primary analyser.
~100 texts/second on CPU.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from analysis.base import LLMAnalyser
from core.models import (
    AlertSignal,
    FraudRisk,
    FraudRiskScore,
    LLMAnalysis,
    Recommendation,
    SentimentData,
)

logger = logging.getLogger(__name__)


class FinBERTAnalyser(LLMAnalyser):
    """
    Fast sentiment scoring via FinBERT.

    Processes all text snippets from sentiment data (Reddit titles,
    StockTwits messages, news headlines) and returns aggregate
    sentiment percentages.
    """

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._loaded = False

    @property
    def provider_name(self) -> str:
        return "finbert"

    @property
    def model_name(self) -> str:
        return "ProsusAI/finbert"

    async def health_check(self) -> bool:
        try:
            self._ensure_loaded()
            return self._loaded
        except Exception:
            return False

    async def analyse(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
        fraud_risk: FraudRiskScore,
    ) -> LLMAnalysis:
        """
        Batch-process all text snippets through FinBERT.

        Returns aggregate sentiment as an LLMAnalysis.
        """
        start = time.monotonic()

        try:
            self._ensure_loaded()

            # Collect all text snippets
            texts = self._collect_texts(sentiment)
            if not texts:
                return LLMAnalysis(
                    provider=self.provider_name,
                    model=self.model_name,
                    summary="No text data available for FinBERT analysis",
                    error="No input texts",
                )

            # Run FinBERT on all texts
            import asyncio
            results = await asyncio.to_thread(self._pipeline, texts, truncation=True, max_length=512)

            # Aggregate scores
            pos_count = sum(1 for r in results if r["label"] == "positive")
            neg_count = sum(1 for r in results if r["label"] == "negative")
            neu_count = sum(1 for r in results if r["label"] == "neutral")
            total = len(results)

            pos_pct = pos_count / total if total > 0 else 0
            neg_pct = neg_count / total if total > 0 else 0

            # Map to sentiment score: -10 to +10
            sentiment_score = (pos_pct - neg_pct) * 10

            # Simple recommendation based on sentiment balance
            if pos_pct > 0.6:
                recommendation = Recommendation.BUY
            elif neg_pct > 0.6:
                recommendation = Recommendation.AVOID
            else:
                recommendation = Recommendation.HOLD

            latency = int((time.monotonic() - start) * 1000)

            return LLMAnalysis(
                provider=self.provider_name,
                model=self.model_name,
                sentiment_score=round(sentiment_score, 2),
                confidence=max(pos_pct, neg_pct),
                bullish_signals=[f"{pos_pct:.0%} of {total} texts classified positive"],
                bearish_signals=[f"{neg_pct:.0%} of {total} texts classified negative"],
                risk_level=3,
                fraud_risk=fraud_risk.risk_level,
                recommendation=recommendation,
                summary=(
                    f"FinBERT analysis of {total} text snippets: "
                    f"{pos_pct:.0%} positive, {neg_pct:.0%} negative, "
                    f"{neu_count/total:.0%} neutral."
                ),
                key_factors=[
                    f"Positive ratio: {pos_pct:.1%}",
                    f"Negative ratio: {neg_pct:.1%}",
                    f"Sample size: {total} texts",
                ],
                latency_ms=latency,
            )

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("FinBERT analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self.model_name,
                latency_ms=latency,
                error=str(e),
            )

    def _collect_texts(self, sentiment: SentimentData) -> list[str]:
        """Extract all analysable text snippets from sentiment data."""
        texts = []

        for post in sentiment.reddit_posts:
            if post.title:
                texts.append(post.title)
            if post.body:
                texts.append(post.body[:200])

        for msg in sentiment.stocktwits_messages:
            if msg.text:
                texts.append(msg.text)

        for article in sentiment.news_articles:
            if article.title:
                texts.append(article.title)
            if article.summary:
                texts.append(article.summary[:200])

        return texts

    def _ensure_loaded(self) -> None:
        """Lazy-load the FinBERT pipeline."""
        if self._loaded:
            return

        from transformers import pipeline

        logger.info("Loading FinBERT model (first use)...")
        self._pipeline = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            device=-1,  # CPU
        )
        self._loaded = True
        logger.info("FinBERT model loaded")
