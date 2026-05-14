"""Tests for LLM analysis engine.

Covers: prompt builders, response parsing (0-10 scoring), report generator
(single mode with announcement + sentiment), consensus generator, and
simple average fallback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from analysis._prompt_helper import (
    build_announcement_prompt,
    build_consensus_prompt,
    build_sentiment_prompt,
    parse_llm_response,
)
from analysis.base import LLMAnalyser
from analysis.consensus_generator import ConsensusGenerator
from analysis.report_generator import ReportGenerator
from config.settings import Settings
from core.models import (
    AlertSignal,
    AnalysisResult,
    AnalysisType,
    Form8KFiling,
    Recommendation,
    SentimentData,
)

# =============================================================================
# Fixtures
# =============================================================================


def make_alert(**kwargs) -> AlertSignal:
    """Create a minimal AlertSignal for testing."""
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
    """Create a minimal SentimentData for testing."""
    defaults = {"ticker": "TEST"}
    defaults.update(kwargs)
    return SentimentData(**defaults)


def make_filings() -> list[Form8KFiling]:
    """Create minimal Form 8-K filings for testing."""
    return [
        Form8KFiling(
            ticker="TEST",
            filed_date=datetime(2026, 1, 15, tzinfo=UTC),
            form_type="8-K",
            description="Current report",
            items=["Item 2.02"],
            text_content="Quarterly earnings of $0.50 per share.",
        )
    ]


def make_mock_analyser(
    provider: str = "test",
    recommendation: Recommendation = Recommendation.BUY,
    score: float = 5.0,
    error: str | None = None,
) -> LLMAnalyser:
    """Create a mock LLMAnalyser that returns predictable results.

    Both analyse_announcements and analyse_sentiment return an
    AnalysisResult with the given score and recommendation.
    """
    analyser = AsyncMock(spec=LLMAnalyser)
    analyser.provider_name = provider
    analyser.model_name = "test-model"

    announcement_result = AnalysisResult(
        provider=provider,
        model="test-model",
        analysis_type=AnalysisType.ANNOUNCEMENT,
        score=score,
        confidence=0.8,
        recommendation=recommendation,
        summary=f"Test announcement analysis from {provider}",
        key_points=["Test point"],
        bullish_signals=["Test bullish signal"],
        bearish_signals=["Test bearish signal"],
        error=error,
    )
    sentiment_result = AnalysisResult(
        provider=provider,
        model="test-model",
        analysis_type=AnalysisType.SENTIMENT,
        score=score,
        confidence=0.8,
        recommendation=recommendation,
        summary=f"Test sentiment analysis from {provider}",
        key_points=["Test point"],
        bullish_signals=["Test bullish signal"],
        bearish_signals=["Test bearish signal"],
        error=error,
    )

    analyser.analyse_announcements.return_value = announcement_result
    analyser.analyse_sentiment.return_value = sentiment_result
    return analyser


# =============================================================================
# Prompt helper tests
# =============================================================================


class TestPromptHelper:
    """Tests for prompt building and response parsing."""

    def test_build_announcement_prompt(self) -> None:
        """Announcement prompt should include filing details."""
        filings = make_filings()
        prompt = build_announcement_prompt("TEST", filings)

        assert "TEST" in prompt
        assert "8-K" in prompt
        assert "Item 2.02" in prompt
        assert "Quarterly earnings" in prompt

    def test_build_announcement_prompt_no_filings(self) -> None:
        """Announcement prompt with no filings should note that."""
        prompt = build_announcement_prompt("TEST", [])
        assert "No Form 8-K filings found" in prompt

    def test_build_sentiment_prompt(self) -> None:
        """Sentiment prompt should include ticker and sentiment data."""
        sentiment = make_sentiment(
            reddit_mention_count=5,
            apewisdom_mentions=10,
        )
        alert_context = {
            "price": 2.50,
            "change_pct": 7.5,
            "volume": 100_000,
            "avg_volume": 10_000,
        }

        prompt = build_sentiment_prompt("TEST", sentiment, alert_context)

        assert "TEST" in prompt
        assert "$2.5" in prompt
        assert "+7.50%" in prompt
        assert "100,000" in prompt

    def test_build_consensus_prompt(self) -> None:
        """Consensus prompt should list individual analyst reports."""
        results = [
            AnalysisResult(
                provider="groq",
                model="llama",
                score=7.0,
                confidence=0.9,
                recommendation=Recommendation.BUY,
                summary="Positive outlook",
                key_points=["Strong momentum"],
                bullish_signals=["Volume spike"],
            ),
            AnalysisResult(
                provider="gemini",
                model="flash",
                score=4.0,
                confidence=0.6,
                recommendation=Recommendation.HOLD,
                summary="Mixed signals",
            ),
        ]

        prompt = build_consensus_prompt("TEST", "sentiment", results)

        assert "TEST" in prompt
        assert "sentiment" in prompt
        assert "Analyst 1" in prompt
        assert "Analyst 2" in prompt
        assert "7.0/10" in prompt
        assert "4.0/10" in prompt

    def test_parse_valid_json(self) -> None:
        """Valid JSON response should parse into an AnalysisResult with correct fields."""
        raw = json.dumps(
            {
                "score": 6.5,
                "confidence": 0.8,
                "bullish_signals": ["Strong momentum"],
                "bearish_signals": ["Low volume"],
                "recommendation": "BUY",
                "summary": "Looks promising",
                "key_points": ["Momentum", "Sentiment"],
            }
        )

        result = parse_llm_response(raw, "test", "test-model", AnalysisType.SENTIMENT, 100)

        assert result.score == 6.5
        assert result.confidence == 0.8
        assert result.recommendation == Recommendation.BUY
        assert len(result.bullish_signals) == 1
        assert result.latency_ms == 100
        assert result.error is None
        assert result.analysis_type == AnalysisType.SENTIMENT

    def test_parse_json_with_code_fences(self) -> None:
        """JSON wrapped in markdown code fences should still parse."""
        raw = (
            "```json\n"
            '{"score": 3.0, "confidence": 0.5, "recommendation": "HOLD", '
            '"bullish_signals": [], "bearish_signals": [], "summary": "Neutral", '
            '"key_points": []}\n```'
        )

        result = parse_llm_response(raw, "test", "model", AnalysisType.ANNOUNCEMENT)
        assert result.score == 3.0
        assert result.recommendation == Recommendation.HOLD

    def test_parse_invalid_json(self) -> None:
        """Invalid JSON should produce an AnalysisResult with an error."""
        result = parse_llm_response("not json at all", "test", "model", AnalysisType.SENTIMENT)
        assert result.error is not None
        assert "Failed to parse" in result.error

    def test_parse_unknown_recommendation_defaults(self) -> None:
        """Unknown recommendation string should default to HOLD."""
        raw = json.dumps(
            {
                "score": 5.0,
                "confidence": 0.5,
                "recommendation": "MAYBE",
                "bullish_signals": [],
                "bearish_signals": [],
                "summary": "",
                "key_points": [],
            }
        )

        result = parse_llm_response(raw, "test", "model", AnalysisType.SENTIMENT)
        assert result.recommendation == Recommendation.HOLD  # Default fallback

    def test_parse_score_clamped_to_range(self) -> None:
        """Scores outside 0-10 should be clamped."""
        raw = json.dumps(
            {
                "score": 15.0,
                "confidence": 1.5,
                "recommendation": "BUY",
                "summary": "",
                "key_points": [],
            }
        )

        result = parse_llm_response(raw, "test", "model", AnalysisType.SENTIMENT)
        assert result.score == 10.0
        assert result.confidence == 1.0

    def test_parse_negative_score_clamped(self) -> None:
        """Negative scores should be clamped to 0."""
        raw = json.dumps(
            {
                "score": -5.0,
                "confidence": -0.3,
                "recommendation": "AVOID",
                "summary": "",
                "key_points": [],
            }
        )

        result = parse_llm_response(raw, "test", "model", AnalysisType.SENTIMENT)
        assert result.score == 0.0
        assert result.confidence == 0.0


# =============================================================================
# Report generator tests
# =============================================================================


class TestReportGenerator:
    """Tests for single-mode report generation."""

    @pytest.mark.asyncio
    async def test_sentiment_only(self) -> None:
        """Report with only sentiment analysis type."""
        analyser = make_mock_analyser("groq", Recommendation.BUY, 6.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"groq": analyser}, settings)

        report = await gen.generate(
            make_alert(),
            make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.ticker == "TEST"
        assert report.mode == "single"
        assert report.sentiment_analysis is not None
        assert report.announcement_analysis is None
        assert report.final_recommendation == Recommendation.BUY
        assert report.sentiment_score == 6.0

    @pytest.mark.asyncio
    async def test_announcement_and_sentiment(self) -> None:
        """Report with both analysis types."""
        analyser = make_mock_analyser("groq", Recommendation.BUY, 7.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"groq": analyser}, settings)

        report = await gen.generate(
            make_alert(),
            make_sentiment(),
            filings=make_filings(),
        )

        assert report.announcement_analysis is not None
        assert report.sentiment_analysis is not None
        assert report.announcement_score == 7.0
        assert report.sentiment_score == 7.0

    @pytest.mark.asyncio
    async def test_fallback_to_other_provider(self) -> None:
        """Default provider unavailable should fall back to any available."""
        analyser = make_mock_analyser("gemini", Recommendation.HOLD, 4.0)
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({"gemini": analyser}, settings)

        report = await gen.generate(
            make_alert(),
            make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.sentiment_analysis is not None
        assert report.sentiment_analysis.provider == "gemini"

    @pytest.mark.asyncio
    async def test_no_analysers_returns_empty_report(self) -> None:
        """No analysers available should return a report without analyses."""
        settings = Settings(llm_default_provider="groq")
        gen = ReportGenerator({}, settings)

        report = await gen.generate(make_alert(), make_sentiment())

        assert report.announcement_analysis is None
        assert report.sentiment_analysis is None
        assert report.mode == "single"


# =============================================================================
# Consensus generator tests
# =============================================================================


class TestConsensusGenerator:
    """Tests for multi-model consensus generation."""

    @pytest.mark.asyncio
    async def test_consensus_sentiment(self) -> None:
        """Consensus mode should run all models on sentiment analysis."""
        analysers = {
            "groq": make_mock_analyser("groq", Recommendation.BUY, 6.0),
            "gemini": make_mock_analyser("gemini", Recommendation.HOLD, 3.0),
            "claude-cli": make_mock_analyser("claude-cli", Recommendation.BUY, 5.0),
        }

        settings = Settings(llm_consensus_meta_provider="claude-cli")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            make_alert(),
            make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert report.mode == "consensus"
        assert len(report.sentiment_analyses) == 3
        # Consensus should exist (simple average fallback since mock lacks _client)
        assert report.sentiment_consensus is not None

    @pytest.mark.asyncio
    async def test_consensus_with_filings(self) -> None:
        """Consensus mode should run both analysis types when filings provided."""
        analysers = {
            "groq": make_mock_analyser("groq", Recommendation.BUY, 7.0),
            "gemini": make_mock_analyser("gemini", Recommendation.BUY, 6.0),
        }

        settings = Settings(llm_consensus_meta_provider="groq")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            make_alert(),
            make_sentiment(),
            filings=make_filings(),
        )

        assert len(report.announcement_analyses) == 2
        assert len(report.sentiment_analyses) == 2
        assert report.announcement_consensus is not None
        assert report.sentiment_consensus is not None

    @pytest.mark.asyncio
    async def test_simple_average_fallback(self) -> None:
        """Simple average should compute correct averages and majority vote."""
        gen = ConsensusGenerator({}, Settings())

        analyses = [
            AnalysisResult(
                provider="a",
                score=6.0,
                confidence=0.8,
                recommendation=Recommendation.BUY,
                bullish_signals=["X"],
            ),
            AnalysisResult(
                provider="b",
                score=4.0,
                confidence=0.6,
                recommendation=Recommendation.HOLD,
                bearish_signals=["Y"],
            ),
            AnalysisResult(
                provider="c",
                score=7.0,
                confidence=0.9,
                recommendation=Recommendation.BUY,
            ),
        ]

        result = gen._simple_average(analyses, "sentiment")

        # Average score: (6+4+7)/3 ≈ 5.67
        assert result.score == pytest.approx(5.67, abs=0.1)
        # BUY has majority (2 vs 1)
        assert result.recommendation == Recommendation.BUY
        assert result.analysis_type == AnalysisType.SENTIMENT

    @pytest.mark.asyncio
    async def test_single_model_consensus(self) -> None:
        """With only 1 model, consensus should use that model's result directly."""
        analysers = {
            "groq": make_mock_analyser("groq", Recommendation.BUY, 8.0),
        }

        settings = Settings(llm_consensus_meta_provider="groq")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            make_alert(),
            make_sentiment(),
            analysis_types=["sentiment"],
        )

        assert len(report.sentiment_analyses) == 1
        # Should still produce a consensus (single model note)
        assert report.sentiment_consensus is not None
        assert "only 1 model" in report.sentiment_consensus.summary
