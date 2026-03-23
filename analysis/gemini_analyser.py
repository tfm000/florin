"""
Google Gemini analyser.

Uses Gemini 2.5 Flash-Lite via the google-genai SDK.
Free tier handles the expected volume easily.
"""

from __future__ import annotations

import logging
import time

from google import genai
from google.genai import types

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


class GeminiAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Google Gemini.

    Uses the ``google-genai`` SDK with JSON response format.
    System prompt is set via ``GenerateContentConfig.system_instruction``.

    Args:
        settings: Application settings containing ``gemini_api_key``
            and ``gemini_model``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model_name_str = settings.gemini_model
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @property
    def provider_name(self) -> str:
        """Identifier for this provider."""
        return "gemini"

    @property
    def model_name(self) -> str:
        """Model identifier (e.g. 'gemini-2.5-flash-lite')."""
        return self._model_name_str

    async def health_check(self) -> bool:
        """Verify the Gemini API is reachable.

        Returns:
            True if the API responds successfully, False otherwise.
        """
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name_str,
                contents="Say 'ok'",
            )
            return response.text is not None
        except Exception:
            return False

    async def analyse_announcements(
        self,
        ticker: str,
        filings: list[Form8KFiling],
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse Form 8-K filings using Gemini.

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
        """Analyse market sentiment using Gemini.

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
        """Send a prompt to the Gemini API and parse the response.

        Gemini uses a different SDK structure: system prompt goes into
        ``GenerateContentConfig.system_instruction`` and responses are
        accessed via ``response.text``.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-level prompt with data to analyse.
            analysis_type: The analysis type for the result.

        Returns:
            Parsed AnalysisResult.
        """
        start = time.monotonic()

        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                max_output_tokens=4096,
                response_mime_type="application/json",
            )

            response = await self._client.aio.models.generate_content(
                model=self._model_name_str,
                contents=user_prompt,
                config=config,
            )
            raw = response.text or ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(
                raw, self.provider_name, self._model_name_str, analysis_type, latency,
            )

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Gemini analysis failed")
            return AnalysisResult(
                provider=self.provider_name,
                model=self._model_name_str,
                analysis_type=analysis_type,
                latency_ms=latency,
                error=str(e),
            )
