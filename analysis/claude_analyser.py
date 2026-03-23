"""
Anthropic Claude analyser.

Uses Claude Haiku 4.5 for high-quality analysis at low cost.
Default meta-analyser for consensus mode.
"""

from __future__ import annotations

import logging
import time

import anthropic

from analysis._prompt_helper import (
    build_announcement_prompt,
    build_sentiment_prompt,
    parse_llm_response,
)
from analysis.base import LLMAnalyser
from config.constants import ANNOUNCEMENT_SYSTEM_PROMPT, SENTIMENT_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AnalysisResult, AnalysisType, Form8KFiling, SentimentData

logger = logging.getLogger(__name__)


class ClaudeAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Anthropic Claude.

    Args:
        settings: Application settings containing ``anthropic_api_key``
            and ``claude_model``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.claude_model
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @property
    def provider_name(self) -> str:
        """Identifier for this provider."""
        return "claude"

    @property
    def model_name(self) -> str:
        """Model identifier (e.g. 'claude-haiku-4-5-20251001')."""
        return self._model

    async def health_check(self) -> bool:
        """Verify the Anthropic API is reachable.

        Returns:
            True if the API responds successfully, False otherwise.
        """
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Say ok"}],
            )
            return len(response.content) > 0
        except Exception:
            return False

    async def analyse_announcements(
        self,
        ticker: str,
        filings: list[Form8KFiling],
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse Form 8-K filings using Claude.

        Args:
            ticker: Stock symbol.
            filings: Form 8-K filings to analyse.
            user_context: Optional user-provided context.

        Returns:
            AnalysisResult with analysis_type=ANNOUNCEMENT.
        """
        return await self._call_llm(
            system_prompt=ANNOUNCEMENT_SYSTEM_PROMPT,
            user_prompt=build_announcement_prompt(ticker, filings, user_context),
            analysis_type=AnalysisType.ANNOUNCEMENT,
        )

    async def analyse_sentiment(
        self,
        ticker: str,
        sentiment: SentimentData,
        alert_context: dict | None = None,
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse market sentiment using Claude.

        Args:
            ticker: Stock symbol.
            sentiment: Aggregated sentiment data.
            alert_context: Optional price/volume context.
            user_context: Optional user-provided context.

        Returns:
            AnalysisResult with analysis_type=SENTIMENT.
        """
        return await self._call_llm(
            system_prompt=SENTIMENT_SYSTEM_PROMPT,
            user_prompt=build_sentiment_prompt(ticker, sentiment, alert_context, user_context),
            analysis_type=AnalysisType.SENTIMENT,
        )

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        analysis_type: AnalysisType,
    ) -> AnalysisResult:
        """Send a prompt to the Anthropic API and parse the response.

        Claude uses the Messages API which has a different interface than
        OpenAI-compatible providers. System prompt goes in a dedicated
        ``system`` parameter rather than a message.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-level prompt with data to analyse.
            analysis_type: The analysis type for the result.

        Returns:
            Parsed AnalysisResult.
        """
        start = time.monotonic()

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.3,
            )

            raw = response.content[0].text if response.content else ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, analysis_type, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Claude analysis failed")
            return AnalysisResult(
                provider=self.provider_name,
                model=self._model,
                analysis_type=analysis_type,
                latency_ms=latency,
                error=str(e),
            )
