"""Tests for the LLM analyser factory and consensus edge cases.

Covers:
- _create_temp_analyser factory: verifies correct analyser type for each host.
- ConsensusGenerator edge cases: all-fail, partial-fail, high score variance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from analysis.base import LLMAnalyser
from analysis.claude_analyser import ClaudeAnalyser
from analysis.consensus_generator import ConsensusGenerator
from analysis.gemini_analyser import GeminiAnalyser
from analysis.groq_analyser import GroqAnalyser
from analysis.openrouter_analyser import OpenRouterAnalyser
from config.settings import Settings
from core.models import (
    AnalysisResult,
    AnalysisType,
    Recommendation,
)
from dashboard.routes.llm_models import _create_temp_analyser
from tests.test_analysis import make_alert, make_filings, make_mock_analyser, make_sentiment


# =============================================================================
# Factory tests
# =============================================================================


class TestAnalyserFactory:
    """Tests for _create_temp_analyser factory function."""

    def test_creates_groq_analyser(self) -> None:
        """host='groq' should return a GroqAnalyser instance."""
        result = _create_temp_analyser("groq", "llama-4-scout", "fake-key")
        assert isinstance(result, GroqAnalyser)

    def test_creates_gemini_analyser(self) -> None:
        """host='gemini' should return a GeminiAnalyser instance."""
        result = _create_temp_analyser("gemini", "gemini-2.0-flash", "fake-key")
        assert isinstance(result, GeminiAnalyser)

    def test_creates_claude_analyser(self) -> None:
        """host='anthropic-cli' should return a ClaudeAnalyser instance."""
        result = _create_temp_analyser("anthropic-cli", "claude-haiku-4-5-20251001", "fake-key")
        assert isinstance(result, ClaudeAnalyser)

    def test_creates_openrouter_analyser(self) -> None:
        """host='openrouter' should return an OpenRouterAnalyser instance."""
        result = _create_temp_analyser("openrouter", "meta-llama/llama-3", "fake-key")
        assert isinstance(result, OpenRouterAnalyser)

    def test_unknown_host_returns_none(self) -> None:
        """An unrecognised host string should return None."""
        result = _create_temp_analyser("unknown", "some-model", "fake-key")
        assert result is None

    def test_all_four_hosts(self) -> None:
        """Every supported host should produce a non-None analyser."""
        hosts = ["groq", "gemini", "anthropic-cli", "openrouter"]
        for host in hosts:
            analyser = _create_temp_analyser(host, "test-model", "fake-key")
            assert analyser is not None, f"Factory returned None for host={host!r}"


# =============================================================================
# Consensus edge-case tests
# =============================================================================


def _make_failing_analyser(provider: str) -> LLMAnalyser:
    """Create a mock analyser whose analyse methods always raise."""
    analyser = AsyncMock(spec=LLMAnalyser)
    analyser.provider_name = provider
    analyser.model_name = "fail-model"
    analyser.analyse_announcements.side_effect = RuntimeError(f"{provider} exploded")
    analyser.analyse_sentiment.side_effect = RuntimeError(f"{provider} exploded")
    return analyser


class TestConsensusEdgeCases:
    """Edge-case tests for ConsensusGenerator beyond the basics in test_analysis.py."""

    @pytest.mark.asyncio
    async def test_consensus_all_models_fail(self) -> None:
        """When every analyser raises, the report should have no usable consensus.

        All 3 models fail, so 0 successful results means the consensus
        falls through (no consensus produced because len(successful) < 1).
        """
        analysers = {
            "groq": _make_failing_analyser("groq"),
            "gemini": _make_failing_analyser("gemini"),
            "claude-cli": _make_failing_analyser("claude-cli"),
        }

        settings = Settings(llm_consensus_meta_provider="groq")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            make_alert(), make_sentiment(), analysis_types=["sentiment"],
        )

        assert report.mode == "consensus"
        # All 3 attempted, all produced error results
        assert len(report.sentiment_analyses) == 3
        for ar in report.sentiment_analyses:
            assert ar.error is not None
        # No successful results → no consensus produced
        assert report.sentiment_consensus is None

    @pytest.mark.asyncio
    async def test_consensus_partial_failure(self) -> None:
        """Two of three analysers succeed; the third raises.

        The report should contain 3 attempted analyses and a consensus
        computed from the 2 successful results.
        """
        analysers = {
            "groq": make_mock_analyser("groq", Recommendation.BUY, 7.0),
            "gemini": make_mock_analyser("gemini", Recommendation.HOLD, 4.0),
            "claude-cli": _make_failing_analyser("claude-cli"),
        }

        settings = Settings(llm_consensus_meta_provider="groq")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            make_alert(), make_sentiment(), analysis_types=["sentiment"],
        )

        assert report.mode == "consensus"
        # 3 attempted (2 success + 1 error)
        assert len(report.sentiment_analyses) == 3
        error_count = sum(1 for a in report.sentiment_analyses if a.error)
        assert error_count == 1
        # Consensus should exist (2 successful results >= 2 threshold)
        assert report.sentiment_consensus is not None

    @pytest.mark.asyncio
    async def test_consensus_score_variance(self) -> None:
        """Models returning widely varied scores (2, 5, 9) should still
        produce a consensus whose score is near the simple average.
        """
        analysers = {
            "groq": make_mock_analyser("groq", Recommendation.AVOID, 2.0),
            "gemini": make_mock_analyser("gemini", Recommendation.HOLD, 5.0),
            "claude-cli": make_mock_analyser("claude-cli", Recommendation.STRONG_BUY, 9.0),
        }

        settings = Settings(llm_consensus_meta_provider="groq")
        gen = ConsensusGenerator(analysers, settings)

        report = await gen.generate(
            make_alert(), make_sentiment(), analysis_types=["sentiment"],
        )

        assert report.mode == "consensus"
        assert len(report.sentiment_analyses) == 3
        assert report.sentiment_consensus is not None
        # Simple-average fallback (mock analysers lack _client) → (2+5+9)/3 ≈ 5.33
        assert report.sentiment_consensus.score == pytest.approx(5.33, abs=0.1)
