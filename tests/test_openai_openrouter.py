"""Tests for the OpenRouter LLM analyser.

Validates the analyser with mocked API responses — no real API calls are made.
Covers: successful analysis (announcement + sentiment), API errors, health checks,
base_url configuration, and settings integration (provider enablement).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysis.openrouter_analyser import _OPENROUTER_BASE_URL, OpenRouterAnalyser
from config.settings import LLMProvider, Settings
from core.models import (
    AnalysisResult,
    AnalysisType,
    Form8KFiling,
    Recommendation,
    SentimentData,
)

# =============================================================================
# Fixtures
# =============================================================================


def _make_sentiment() -> SentimentData:
    """Create a minimal SentimentData for testing."""
    return SentimentData(ticker="TEST")


def _make_filings() -> list[Form8KFiling]:
    """Create minimal Form 8-K filings for testing."""
    return [
        Form8KFiling(
            ticker="TEST",
            filed_date=datetime(2026, 1, 15, tzinfo=UTC),
            form_type="8-K",
            description="Current report",
            items=["Item 2.02"],
            text_content="The company reported Q4 earnings of $0.50 per share.",
        )
    ]


def _make_valid_json_response() -> str:
    """Return a valid JSON string matching the expected analysis schema."""
    return json.dumps(
        {
            "score": 6.5,
            "confidence": 0.85,
            "bullish_signals": ["Strong momentum", "Positive sentiment"],
            "bearish_signals": ["Low market cap"],
            "recommendation": "BUY",
            "summary": "Promising penny stock with strong momentum.",
            "key_points": ["Volume spike", "Social buzz"],
        }
    )


def _mock_completion_response(content: str) -> SimpleNamespace:
    """Build a mock OpenAI ChatCompletion response object."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _mock_health_response() -> SimpleNamespace:
    """Build a mock OpenAI ChatCompletion response for health check."""
    return _mock_completion_response("ok")


# =============================================================================
# OpenRouterAnalyser tests
# =============================================================================


class TestOpenRouterAnalyser:
    """Tests for the OpenRouter analyser."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Settings with OpenRouter configured."""
        return Settings(
            openrouter_api_key="sk-or-test-key-456",
            openrouter_model="anthropic/claude-3.5-sonnet",
        )

    @pytest.fixture
    def analyser(self, settings: Settings) -> OpenRouterAnalyser:
        """OpenRouterAnalyser with a mocked client."""
        a = OpenRouterAnalyser(settings)
        a._client = MagicMock()
        return a

    def test_provider_name(self, analyser: OpenRouterAnalyser) -> None:
        """Provider name should be 'openrouter'."""
        assert analyser.provider_name == "openrouter"

    def test_model_name(self, analyser: OpenRouterAnalyser) -> None:
        """Model name should match settings."""
        assert analyser.model_name == "anthropic/claude-3.5-sonnet"

    def test_base_url_is_openrouter(self, settings: Settings) -> None:
        """The OpenRouter analyser must use the OpenRouter base URL, not default OpenAI."""
        with patch("analysis.openrouter_analyser.openai.AsyncOpenAI") as mock_cls:
            OpenRouterAnalyser(settings)
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["base_url"] == _OPENROUTER_BASE_URL
            assert call_kwargs["api_key"] == "sk-or-test-key-456"
            assert "HTTP-Referer" in call_kwargs["default_headers"]
            assert "X-Title" in call_kwargs["default_headers"]

    @pytest.mark.asyncio
    async def test_analyse_sentiment_success(self, analyser: OpenRouterAnalyser) -> None:
        """Successful sentiment analysis should produce a valid AnalysisResult."""
        mock_response = _mock_completion_response(_make_valid_json_response())
        analyser._client.chat = MagicMock()  # type: ignore[misc]
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "openrouter"
        assert result.model == "anthropic/claude-3.5-sonnet"
        assert result.analysis_type == AnalysisType.SENTIMENT
        assert result.error is None
        assert result.score == 6.5
        assert result.recommendation == Recommendation.BUY
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_analyse_announcements_success(self, analyser: OpenRouterAnalyser) -> None:
        """Successful announcement analysis should produce a valid AnalysisResult."""
        mock_response = _mock_completion_response(_make_valid_json_response())
        analyser._client.chat = MagicMock()  # type: ignore[misc]
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_announcements("TEST", _make_filings())

        assert isinstance(result, AnalysisResult)
        assert result.analysis_type == AnalysisType.ANNOUNCEMENT
        assert result.error is None
        assert result.score == 6.5

    @pytest.mark.asyncio
    async def test_analyse_api_error(self, analyser: OpenRouterAnalyser) -> None:
        """API errors should produce an AnalysisResult with the error field set."""
        analyser._client.chat = MagicMock()  # type: ignore[misc]
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Model not available")
        )

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "openrouter"
        assert result.error is not None
        assert "Model not available" in result.error

    @pytest.mark.asyncio
    async def test_health_check_success(self, analyser: OpenRouterAnalyser) -> None:
        """Health check should return True when the API responds."""
        analyser._client.chat = MagicMock()  # type: ignore[misc]
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=_mock_health_response())

        assert await analyser.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, analyser: OpenRouterAnalyser) -> None:
        """Health check should return False when the API fails."""
        analyser._client.chat = MagicMock()  # type: ignore[misc]
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(side_effect=Exception("Unauthorized"))

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_analyse_malformed_json(self, analyser: OpenRouterAnalyser) -> None:
        """Malformed JSON from the LLM should produce an error in the analysis."""
        mock_response = _mock_completion_response("This is not JSON at all")
        analyser._client.chat = MagicMock()  # type: ignore[misc]
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.error is not None
        assert "Failed to parse" in result.error


# =============================================================================
# Settings integration tests
# =============================================================================


class TestSettingsProviderEnablement:
    """Test that OPENROUTER appears in enabled providers when keys are set."""

    def test_openrouter_enabled_when_key_set(self) -> None:
        """OPENROUTER should be in enabled providers when openrouter_api_key is non-empty."""
        settings = Settings(openrouter_api_key="sk-or-test")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.OPENROUTER in providers

    def test_openrouter_not_enabled_when_key_empty(self) -> None:
        """OPENROUTER should NOT be in enabled providers when openrouter_api_key is empty."""
        settings = Settings(openrouter_api_key="")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.OPENROUTER not in providers

    @patch("config.settings._claude_sdk_available", return_value=False)
    def test_empty_when_no_keys(self, _mock_sdk: MagicMock) -> None:
        """No providers should be enabled when no API keys are set."""
        settings = Settings()
        providers = settings.get_enabled_llm_providers()
        assert len(providers) == 0
