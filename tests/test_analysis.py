"""Tests for LLM analysis engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.consensus_generator import ConsensusGenerator
from analysis.report_generator import ReportGenerator
from analysis.base import LLMAnalyser
from config.settings import Settings
from core.models import (
    AlertSignal,
    LLMAnalysis,
    NewsArticle,
    Recommendation,
    RedditPost,
    SentimentData,
    StockTwitsMessage,
)


# =============================================================================
# Fixtures
# =============================================================================


def make_alert(**kwargs) -> AlertSignal:
    defaults = {
        "ticker": "TEST",
        "price": 2.50,
        "change_pct": 7.5,
        "volume": 100_000,
        "avg_volume": 10_000,
    }
    defaults.update(kwargs)
    return AlertSignal(**defaults)


def make_sentiment(**kwargs) -> SentimentData:
    defaults = {"ticker": "TEST"}
    defaults.update(kwargs)
    return SentimentData(**defaults)


def make_mock_analyser(
    provider: str = "test",
    recommendation: Recommendation = Recommendation.BUY,
    score: float = 5.0,
    error: str | None = None,
) -> LLMAnalyser:
    """Create a mock LLMAnalyser that returns a predictable result."""
    analyser = AsyncMock(spec=LLMAnalyser)
    analyser.provider_name = provider
    analyser.model_name = "test-model"

    result = LLMAnalysis(
        provider=provider,
        model="test-model",
        sentiment_score=score,
        confidence=0.8,
        recommendation=recommendation,
        summary=f"Test analysis from {provider}",
        bullish_signals=["Test bullish signal"],
        bearish_signals=["Test bearish signal"],
        error=error,
    )
    analyser.analyse.return_value = result
    return analyser


# =============================================================================
# Prompt helper tests
# =============================================================================


class TestPromptHelper:
    def test_build_user_prompt(self) -> None:
        alert = make_alert()
        sentiment = make_sentiment(
            reddit_mention_count=5,
            stocktwits_bullish_count=3,
        )

        prompt = build_user_prompt(alert, sentiment)

        assert "TEST" in prompt
        assert "$2.5" in prompt
        assert "+7.50%" in prompt
        assert "100,000" in prompt

    def test_parse_valid_json(self) -> None:
        raw = json.dumps({
            "sentiment_score": 6.5,
            "confidence": 0.8,
            "bullish_signals": ["Strong momentum"],
            "bearish_signals": ["Low volume"],
            "risk_level": 2,
            "recommendation": "BUY",
            "summary": "Looks promising",
            "key_factors": ["Momentum", "Sentiment"],
        })

        result = parse_llm_response(raw, "test", "test-model", 100)

        assert result.sentiment_score == 6.5
        assert result.confidence == 0.8
        assert result.recommendation == Recommendation.BUY
        assert len(result.bullish_signals) == 1
        assert result.latency_ms == 100
        assert result.error is None

    def test_parse_json_with_code_fences(self) -> None:
        raw = '```json\n{"sentiment_score": 3.0, "confidence": 0.5, "recommendation": "HOLD", "risk_level": 3, "bullish_signals": [], "bearish_signals": [], "summary": "Neutral", "key_factors": []}\n```'

        result = parse_llm_response(raw, "test", "model")
        assert result.sentiment_score == 3.0
        assert result.recommendation == Recommendation.HOLD

    def test_parse_invalid_json(self) -> None:
        result = parse_llm_response("not json at all", "test", "model")
        assert result.error is not None
        assert "Failed to parse" in result.error

    def test_parse_unknown_recommendation_defaults(self) -> None:
        raw = json.dumps({
            "sentiment_score": 0,
            "confidence": 0.5,
            "recommendation": "MAYBE",
            "risk_level": 3,
            "bullish_signals": [],
            "bearish_signals": [],
            "summary": "",
            "key_factors": [],
        })

        result = parse_llm_response(raw, "test", "model")
        assert result.recommendation == Recommendation.HOLD  # Default fallback


# =============================================================================
# Report generator tests
# =============================================================================


class TestReportGenerator:
    @pytest.mark.asyncio
    async def test_single_report_generation(self) -> None:
        analyser = make_mock_analyser("groq", Recommendation.BUY, 6.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"groq": analyser}, settings)

        alert = make_alert()
        sentiment = make_sentiment()

        report = await gen.generate(alert, sentiment)

        assert report.ticker == "TEST"
        assert report.mode == "single"
        assert report.primary_analysis is not None
        assert report.final_recommendation == Recommendation.BUY
        assert report.final_score == 6.0

    @pytest.mark.asyncio
    async def test_fallback_to_other_provider(self) -> None:
        # Default provider "groq" not available, should fall back to "gemini"
        analyser = make_mock_analyser("gemini", Recommendation.HOLD, 2.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"gemini": analyser}, settings)

        report = await gen.generate(make_alert(), make_sentiment())

        assert report.primary_analysis.provider == "gemini"


# =============================================================================
# Consensus generator tests
# =============================================================================


class TestConsensusGenerator:
    @pytest.mark.asyncio
    async def test_consensus_with_multiple_llms(self) -> None:
        analysers = {
            "groq": make_mock_analyser("groq", Recommendation.BUY, 6.0),
            "gemini": make_mock_analyser("gemini", Recommendation.HOLD, 3.0),
            "claude": make_mock_analyser("claude", Recommendation.BUY, 5.0),
        }

        settings = Settings(llm_consensus_meta_provider="claude")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(make_alert(), make_sentiment())

        assert report.mode == "consensus"
        # All 3 analysers should produce individual analyses
        assert len(report.individual_analyses) == 3
        # Consensus should exist (simple average fallback since claude mock doesn't have _client)
        assert report.consensus is not None

    @pytest.mark.asyncio
    async def test_simple_average_fallback(self) -> None:
        gen = ConsensusGenerator({}, Settings())

        analyses = [
            LLMAnalysis(provider="a", sentiment_score=6.0, confidence=0.8,
                        recommendation=Recommendation.BUY, bullish_signals=["X"]),
            LLMAnalysis(provider="b", sentiment_score=4.0, confidence=0.6,
                        recommendation=Recommendation.HOLD, bearish_signals=["Y"]),
            LLMAnalysis(provider="c", sentiment_score=7.0, confidence=0.9,
                        recommendation=Recommendation.BUY),
        ]

        result = gen._simple_average(analyses)

        # Average score: (6+4+7)/3 ≈ 5.67
        assert result.sentiment_score == pytest.approx(5.67, abs=0.1)
        # BUY has majority (2 vs 1)
        assert result.recommendation == Recommendation.BUY
