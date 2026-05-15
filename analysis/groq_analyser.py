"""
Groq analyser — ultra-fast cloud LLM inference.

Uses Groq's API with Llama 4 Scout for sub-second analysis.
~$0.0004 per report. Rate limits are generous on free tier.
"""

from __future__ import annotations

import logging
import time

from groq import AsyncGroq

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


class GroqAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Groq (Llama 4 Scout).

    Args:
        settings: Application settings containing ``groq_api_key``
            and ``groq_model``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.groq_model
        self._client = AsyncGroq(api_key=settings.groq_api_key)

    @property
    def provider_name(self) -> str:
        """Identifier for this provider."""
        return "groq"

    @property
    def model_name(self) -> str:
        """Model identifier (e.g. 'llama-4-scout-17b-16e-instruct')."""
        return self._model

    async def health_check(self) -> bool:
        """Check if Groq is available by listing models.

        Returns:
            True if the model is found in the Groq model list.
        """
        try:
            models = await self._client.models.list()
            return any(m.id == self._model for m in models.data)
        except Exception:
            return False

    async def analyse_announcements(
        self,
        ticker: str,
        filings: list[Form8KFiling],
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse Form 8-K filings using Groq.

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
        """Analyse market sentiment using Groq.

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
        """Send a prompt to the Groq API and parse the response.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-level prompt with data to analyse.
            analysis_type: The analysis type for the result.

        Returns:
            Parsed AnalysisResult.
        """
        start = time.monotonic()

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content or ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, analysis_type, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Groq analysis failed")
            return AnalysisResult(
                provider=self.provider_name,
                model=self._model,
                analysis_type=analysis_type,
                latency_ms=latency,
                error=str(e),
            )
