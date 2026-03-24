"""Tests for Groq, Gemini, and Claude LLM analysers.

Validates all three analysers with mocked API responses — no real API calls are made.
Covers: successful analysis (announcement + sentiment), API errors, health checks,
empty responses, and settings integration (provider enablement).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from analysis.claude_analyser import ClaudeAnalyser
from analysis.gemini_analyser import GeminiAnalyser
from analysis.groq_analyser import GroqAnalyser
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
    return json.dumps({
        "score": 6.5,
        "confidence": 0.85,
        "bullish_signals": ["Strong momentum", "Positive sentiment"],
        "bearish_signals": ["Low market cap"],
        "recommendation": "BUY",
        "summary": "Promising penny stock with strong momentum.",
        "key_points": ["Volume spike", "Social buzz"],
    })


def _mock_completion_response(content: str) -> SimpleNamespace:
    """Build a mock OpenAI-compatible ChatCompletion response object.

    Used for Groq which shares the OpenAI response format.
    """
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _mock_claude_response(content: str) -> SimpleNamespace:
    """Build a mock Anthropic Messages API response object.

    Claude returns ``response.content[0].text`` rather than
    ``response.choices[0].message.content``.
    """
    text_block = SimpleNamespace(text=content)
    return SimpleNamespace(content=[text_block])


def _mock_claude_empty_response() -> SimpleNamespace:
    """Build a mock Anthropic Messages API response with empty content list."""
    return SimpleNamespace(content=[])


def _mock_gemini_response(content: str) -> SimpleNamespace:
    """Build a mock Google genai response object.

    Gemini returns ``response.text``.
    """
    return SimpleNamespace(text=content)


# =============================================================================
# GroqAnalyser tests
# =============================================================================


class TestGroqAnalyser:
    """Tests for the Groq analyser."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Settings with Groq configured."""
        return Settings(
            groq_api_key="gsk-test-key-123",
            groq_model="llama-4-scout-17b-16e-instruct",
        )

    @pytest.fixture
    def analyser(self, settings: Settings) -> GroqAnalyser:
        """GroqAnalyser with a mocked client."""
        a = GroqAnalyser(settings)
        a._client = MagicMock()
        return a

    def test_provider_name(self, analyser: GroqAnalyser) -> None:
        """Provider name should be 'groq'."""
        assert analyser.provider_name == "groq"

    def test_model_name(self, analyser: GroqAnalyser) -> None:
        """Model name should match settings."""
        assert analyser.model_name == "llama-4-scout-17b-16e-instruct"

    @pytest.mark.asyncio
    async def test_analyse_sentiment_success(self, analyser: GroqAnalyser) -> None:
        """Successful sentiment analysis should produce a valid AnalysisResult."""
        mock_response = _mock_completion_response(_make_valid_json_response())
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "groq"
        assert result.model == "llama-4-scout-17b-16e-instruct"
        assert result.analysis_type == AnalysisType.SENTIMENT
        assert result.error is None
        assert result.score == 6.5
        assert result.confidence == 0.85
        assert result.recommendation == Recommendation.BUY
        assert len(result.bullish_signals) == 2
        assert len(result.bearish_signals) == 1
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_analyse_announcements_success(self, analyser: GroqAnalyser) -> None:
        """Successful announcement analysis should produce a valid AnalysisResult."""
        mock_response = _mock_completion_response(_make_valid_json_response())
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_announcements("TEST", _make_filings())

        assert isinstance(result, AnalysisResult)
        assert result.analysis_type == AnalysisType.ANNOUNCEMENT
        assert result.error is None
        assert result.score == 6.5

    @pytest.mark.asyncio
    async def test_analyse_api_error(self, analyser: GroqAnalyser) -> None:
        """API errors should produce an AnalysisResult with the error field set."""
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Rate limit exceeded")
        )

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "groq"
        assert result.error is not None
        assert "Rate limit exceeded" in result.error
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_health_check_success(self, analyser: GroqAnalyser) -> None:
        """Health check should return True when the model is in the list."""
        model_entry = SimpleNamespace(id="llama-4-scout-17b-16e-instruct")
        models_response = SimpleNamespace(data=[model_entry])
        analyser._client.models = MagicMock()
        analyser._client.models.list = AsyncMock(return_value=models_response)

        assert await analyser.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, analyser: GroqAnalyser) -> None:
        """Health check should return False when the API fails."""
        analyser._client.models = MagicMock()
        analyser._client.models.list = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_model_not_found(self, analyser: GroqAnalyser) -> None:
        """Health check should return False when the model is not in the list."""
        model_entry = SimpleNamespace(id="some-other-model")
        models_response = SimpleNamespace(data=[model_entry])
        analyser._client.models = MagicMock()
        analyser._client.models.list = AsyncMock(return_value=models_response)

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_analyse_empty_response(self, analyser: GroqAnalyser) -> None:
        """An empty content string should produce an error in the analysis."""
        mock_response = _mock_completion_response("")
        analyser._client.chat = MagicMock()
        analyser._client.chat.completions = MagicMock()
        analyser._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.error is not None
        assert "Failed to parse" in result.error


# =============================================================================
# ClaudeAnalyser tests
# =============================================================================


class TestClaudeAnalyser:
    """Tests for the Claude (Anthropic) analyser."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Settings with Claude configured."""
        return Settings(
            anthropic_api_key="sk-ant-test-key-456",
            claude_model="claude-haiku-4-5-20251001",
        )

    @pytest.fixture
    def analyser(self, settings: Settings) -> ClaudeAnalyser:
        """ClaudeAnalyser with a mocked client."""
        a = ClaudeAnalyser(settings)
        a._client = MagicMock()
        return a

    def test_provider_name(self, analyser: ClaudeAnalyser) -> None:
        """Provider name should be 'claude'."""
        assert analyser.provider_name == "claude"

    def test_model_name(self, analyser: ClaudeAnalyser) -> None:
        """Model name should match settings."""
        assert analyser.model_name == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_analyse_sentiment_success(self, analyser: ClaudeAnalyser) -> None:
        """Successful sentiment analysis should produce a valid AnalysisResult."""
        mock_response = _mock_claude_response(_make_valid_json_response())
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "claude"
        assert result.model == "claude-haiku-4-5-20251001"
        assert result.analysis_type == AnalysisType.SENTIMENT
        assert result.error is None
        assert result.score == 6.5
        assert result.confidence == 0.85
        assert result.recommendation == Recommendation.BUY
        assert len(result.bullish_signals) == 2
        assert len(result.bearish_signals) == 1
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_analyse_announcements_success(self, analyser: ClaudeAnalyser) -> None:
        """Successful announcement analysis should produce a valid AnalysisResult."""
        mock_response = _mock_claude_response(_make_valid_json_response())
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_announcements("TEST", _make_filings())

        assert isinstance(result, AnalysisResult)
        assert result.analysis_type == AnalysisType.ANNOUNCEMENT
        assert result.error is None
        assert result.score == 6.5

    @pytest.mark.asyncio
    async def test_analyse_api_error(self, analyser: ClaudeAnalyser) -> None:
        """API errors should produce an AnalysisResult with the error field set."""
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(
            side_effect=Exception("Overloaded")
        )

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "claude"
        assert result.error is not None
        assert "Overloaded" in result.error
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_health_check_success(self, analyser: ClaudeAnalyser) -> None:
        """Health check should return True when the API responds with content."""
        mock_response = _mock_claude_response("ok")
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(return_value=mock_response)

        assert await analyser.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, analyser: ClaudeAnalyser) -> None:
        """Health check should return False when the API fails."""
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(
            side_effect=Exception("Unauthorized")
        )

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_empty_content(self, analyser: ClaudeAnalyser) -> None:
        """Health check should return False when the API returns empty content."""
        mock_response = _mock_claude_empty_response()
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(return_value=mock_response)

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_analyse_empty_response(self, analyser: ClaudeAnalyser) -> None:
        """An empty content string should produce an error in the analysis."""
        mock_response = _mock_claude_response("")
        analyser._client.messages = MagicMock()
        analyser._client.messages.create = AsyncMock(return_value=mock_response)

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.error is not None
        assert "Failed to parse" in result.error


# =============================================================================
# GeminiAnalyser tests
# =============================================================================


class TestGeminiAnalyser:
    """Tests for the Gemini (Google) analyser."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Settings with Gemini configured."""
        return Settings(
            gemini_api_key="AIza-test-key-789",
            gemini_model="gemini-2.5-flash-lite",
        )

    @pytest.fixture
    def analyser(self, settings: Settings) -> GeminiAnalyser:
        """GeminiAnalyser with a mocked client."""
        a = GeminiAnalyser(settings)
        a._client = MagicMock()
        return a

    def test_provider_name(self, analyser: GeminiAnalyser) -> None:
        """Provider name should be 'gemini'."""
        assert analyser.provider_name == "gemini"

    def test_model_name(self, analyser: GeminiAnalyser) -> None:
        """Model name should match settings."""
        assert analyser.model_name == "gemini-2.5-flash-lite"

    @pytest.mark.asyncio
    async def test_analyse_sentiment_success(self, analyser: GeminiAnalyser) -> None:
        """Successful sentiment analysis should produce a valid AnalysisResult."""
        mock_response = _mock_gemini_response(_make_valid_json_response())
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "gemini"
        assert result.model == "gemini-2.5-flash-lite"
        assert result.analysis_type == AnalysisType.SENTIMENT
        assert result.error is None
        assert result.score == 6.5
        assert result.confidence == 0.85
        assert result.recommendation == Recommendation.BUY
        assert len(result.bullish_signals) == 2
        assert len(result.bearish_signals) == 1
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_analyse_announcements_success(self, analyser: GeminiAnalyser) -> None:
        """Successful announcement analysis should produce a valid AnalysisResult."""
        mock_response = _mock_gemini_response(_make_valid_json_response())
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        result = await analyser.analyse_announcements("TEST", _make_filings())

        assert isinstance(result, AnalysisResult)
        assert result.analysis_type == AnalysisType.ANNOUNCEMENT
        assert result.error is None
        assert result.score == 6.5

    @pytest.mark.asyncio
    async def test_analyse_api_error(self, analyser: GeminiAnalyser) -> None:
        """API errors should produce an AnalysisResult with the error field set."""
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("Quota exceeded")
        )

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.provider == "gemini"
        assert result.error is not None
        assert "Quota exceeded" in result.error
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_health_check_success(self, analyser: GeminiAnalyser) -> None:
        """Health check should return True when the API responds with text."""
        mock_response = _mock_gemini_response("ok")
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        assert await analyser.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, analyser: GeminiAnalyser) -> None:
        """Health check should return False when the API fails."""
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("Service unavailable")
        )

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_null_text(self, analyser: GeminiAnalyser) -> None:
        """Health check should return False when response.text is None."""
        mock_response = SimpleNamespace(text=None)
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        assert await analyser.health_check() is False

    @pytest.mark.asyncio
    async def test_analyse_empty_response(self, analyser: GeminiAnalyser) -> None:
        """An empty text response should produce an error in the analysis."""
        mock_response = _mock_gemini_response("")
        analyser._client.aio = MagicMock()
        analyser._client.aio.models = MagicMock()
        analyser._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        result = await analyser.analyse_sentiment("TEST", _make_sentiment())

        assert isinstance(result, AnalysisResult)
        assert result.error is not None
        assert "Failed to parse" in result.error


# =============================================================================
# Settings integration tests
# =============================================================================


class TestSettingsProviderEnablement:
    """Test that GROQ, GEMINI, and CLAUDE appear in enabled providers when keys are set."""

    def test_groq_enabled_when_key_set(self) -> None:
        """GROQ should be in enabled providers when groq_api_key is non-empty."""
        settings = Settings(groq_api_key="gsk-test")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.GROQ in providers

    def test_groq_not_enabled_when_key_empty(self) -> None:
        """GROQ should NOT be in enabled providers when groq_api_key is empty."""
        settings = Settings(groq_api_key="")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.GROQ not in providers

    def test_gemini_enabled_when_key_set(self) -> None:
        """GEMINI should be in enabled providers when gemini_api_key is non-empty."""
        settings = Settings(gemini_api_key="AIza-test")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.GEMINI in providers

    def test_gemini_not_enabled_when_key_empty(self) -> None:
        """GEMINI should NOT be in enabled providers when gemini_api_key is empty."""
        settings = Settings(gemini_api_key="")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.GEMINI not in providers

    def test_claude_enabled_when_key_set(self) -> None:
        """CLAUDE should be in enabled providers when anthropic_api_key is non-empty."""
        settings = Settings(anthropic_api_key="sk-ant-test")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.CLAUDE in providers

    def test_claude_not_enabled_when_key_empty(self) -> None:
        """CLAUDE should NOT be in enabled providers when anthropic_api_key is empty."""
        settings = Settings(anthropic_api_key="")
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.CLAUDE not in providers

    def test_all_three_enabled_when_all_keys_set(self) -> None:
        """All three providers should appear when all API keys are configured."""
        settings = Settings(
            groq_api_key="gsk-test",
            gemini_api_key="AIza-test",
            anthropic_api_key="sk-ant-test",
        )
        providers = settings.get_enabled_llm_providers()
        assert LLMProvider.GROQ in providers
        assert LLMProvider.GEMINI in providers
        assert LLMProvider.CLAUDE in providers

    def test_empty_when_no_keys(self) -> None:
        """No providers should be enabled when no API keys are set."""
        settings = Settings()
        providers = settings.get_enabled_llm_providers()
        assert len(providers) == 0
