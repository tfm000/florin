"""Tests for OpenAI and OpenRouter LLM analysers.

Validates both analysers with mocked API responses — no real API calls are made.
Covers: successful analysis, API errors, health checks, base_url configuration,
and settings integration (provider enablement).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysis.openai_analyser import OpenAIAnalyser
from analysis.openrouter_analyser import OpenRouterAnalyser, _OPENROUTER_BASE_URL
from config.settings import LLMProvider, Settings
from core.models import (
    AlertSignal,
    LLMAnalysis,
    Recommendation,
    SentimentData,
)


# =============================================================================
# Fixtures
# =============================================================================


def _make_alert() -> AlertSignal:
    """Create a minimal AlertSignal for testing."""
    return AlertSignal(
        ticker="TEST",
        price=2.50,
        change_pct=7.5,
        volume=100_000,
        avg_volume=10_000,
    )


def _make_sentiment() -> SentimentData:
    """Create a minimal SentimentData for testing."""
    return SentimentData(ticker="TEST")


def _make_valid_json_response() -> str:
    """Return a valid JSON string matching the expected LLM analysis schema."""
    return json.dumps({
        "sentiment_score": 6.5,
        "confidence": 0.85,
        "bullish_signals": ["Strong momentum", "Positive sentiment"],
        "bearish_signals": ["Low market cap"],
        "risk_level": 2,
        "recommendation": "BUY",
        "summary": "Promising penny stock with strong momentum.",
        "key_factors": ["Volume spike", "Social buzz"],
    })


def _mock_completion_response(content: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response object."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _mock_health_response() -> MagicMock:
    """Build a mock OpenAI ChatCompletion response for health check."""
    return _mock_completion_response("ok")


# =============================================================================
# OpenAIAnalyser tests
# =============================================================================


class TestOpenAIAnalyser:
    """Tests for the OpenAI analyser."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Settings with OpenAI configured."""
        return Settings(openai_api_key="sk-test-key-123", openai_model="gpt-4o-mini")

    @pytest.fixture
    def analyser(self, settings: Settings) -> OpenAIAnalyser:
        """OpenAIAnalyser with a mocked client."""
        a = OpenAIAnalyser(settings)
        a._client = MagicMock()
        return a

    def test_provider_name(self, analyser: OpenAIAnalyser) -> None:
        """Provider name should be 'openai'."""
        assert analyser.provider_name == "openai"

    def test_model_name(self, analyser: OpenAIAnalyser) -> None:
        """Model name should match settings."""
        assert analyser.model_name == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_analyse_success(self, analyser: OpenAIAnalyser) -> None:
        """Successful API response should produce a valid LLMAnalysis."""
        mock_response = _mock_completion_response(_make_valid_json_response())
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse(_make_alert(), _make_sentiment())

        assert isinstance(result, LLMAnalysis)
        assert result.provider == "openai"
        assert result.model == "gpt-4o-mini"
        assert result.error is None
        assert result.sentiment_score == 6.5
        assert result.confidence == 0.85
        assert result.recommendation == Recommendation.BUY
        assert len(result.bullish_signals) == 2
        assert len(result.bearish_signals) == 1
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_analyse_api_error(self, analyser: OpenAIAnalyser) -> None:
        """API errors should produce an LLMAnalysis with the error field set."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Rate limit exceeded")
        )

        result = await analyser.analyse(_make_alert(), _make_sentiment())

        assert isinstance(result, LLMAnalysis)
        assert result.provider == "openai"
        assert result.error is not None
        assert "Rate limit exceeded" in result.error
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_health_check_success(self, analyser: OpenAIAnalyser) -> None:
        """Health check should return True when the API responds."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            return_value=_mock_health_response()
        )

        assert await analyser.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, analyser: OpenAIAnalyser) -> None:
        """Health check should return False when the API fails."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_analyse_empty_response(self, analyser: OpenAIAnalyser) -> None:
        """An empty content string should produce an error in the analysis."""
        mock_response = _mock_completion_response("")
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse(_make_alert(), _make_sentiment())

        assert isinstance(result, LLMAnalysis)
        assert result.error is not None
        assert "Failed to parse" in result.error


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
    async def test_analyse_success(self, analyser: OpenRouterAnalyser) -> None:
        """Successful API response should produce a valid LLMAnalysis."""
        mock_response = _mock_completion_response(_make_valid_json_response())
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse(_make_alert(), _make_sentiment())

        assert isinstance(result, LLMAnalysis)
        assert result.provider == "openrouter"
        assert result.model == "anthropic/claude-3.5-sonnet"
        assert result.error is None
        assert result.sentiment_score == 6.5
        assert result.recommendation == Recommendation.BUY
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_analyse_api_error(self, analyser: OpenRouterAnalyser) -> None:
        """API errors should produce an LLMAnalysis with the error field set."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Model not available")
        )

        result = await analyser.analyse(_make_alert(), _make_sentiment())

        assert isinstance(result, LLMAnalysis)
        assert result.provider == "openrouter"
        assert result.error is not None
        assert "Model not available" in result.error

    @pytest.mark.asyncio
    async def test_health_check_success(self, analyser: OpenRouterAnalyser) -> None:
        """Health check should return True when the API responds."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            return_value=_mock_health_response()
        )

        assert await analyser.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, analyser: OpenRouterAnalyser) -> None:
        """Health check should return False when the API fails."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Unauthorized")
        )

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_analyse_malformed_json(self, analyser: OpenRouterAnalyser) -> None:
        """Malformed JSON from the LLM should produce an error in the analysis."""
        mock_response = _mock_completion_response("This is not JSON at all")
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse(_make_alert(), _make_sentiment())

        assert isinstance(result, LLMAnalysis)
        assert result.error is not None
        assert "Failed to parse" in result.error


# =============================================================================
# Settings integration tests
# =============================================================================


class TestSettingsProviderEnablement:
    """Test that OPENAI and OPENROUTER appear in enabled providers when keys are set."""

    def test_openai_enabled_when_key_set(self) -> None:
        """OPENAI should be in enabled providers when openai_api_key is non-empty."""
        settings = Settings(openai_api_key="sk-test")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.OPENAI in providers

    def test_openai_not_enabled_when_key_empty(self) -> None:
        """OPENAI should NOT be in enabled providers when openai_api_key is empty."""
        settings = Settings(openai_api_key="")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.OPENAI not in providers

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

    def test_both_enabled_when_both_keys_set(self) -> None:
        """Both providers should appear when both API keys are configured."""
        settings = Settings(openai_api_key="sk-test", openrouter_api_key="sk-or-test")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.OPENAI in providers
        assert LLMProvider.OPENROUTER in providers

    def test_empty_when_no_keys(self) -> None:
        """No providers should be enabled when no API keys are set."""
        settings = Settings()
        providers = settings.get_enabled_llm_providers()
        assert len(providers) == 0
