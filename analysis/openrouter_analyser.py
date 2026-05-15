"""
OpenRouter analyser — access hundreds of LLM models via a unified API.

OpenRouter provides an OpenAI-compatible API at https://openrouter.ai/api/v1
supporting models from OpenAI, Anthropic, Meta, Mistral, Google, and others.
Some models are available on a free tier.
"""

from __future__ import annotations

import logging
import time

import openai

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

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterAnalyser(LLMAnalyser):
    """Cloud LLM analysis via OpenRouter (OpenAI-compatible API).

    OpenRouter aggregates many LLM providers behind a single API endpoint.
    This analyser uses the ``openai`` Python client with a custom ``base_url``
    pointing to OpenRouter's API. HTTP-Referer and X-Title headers are included
    as recommended by the OpenRouter documentation.

    Args:
        settings: Application settings containing ``openrouter_api_key``
            and ``openrouter_model``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.openrouter_model
        self._client = openai.AsyncOpenAI(
            base_url=_OPENROUTER_BASE_URL,
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/tfm000/florin-terminal",
                "X-Title": "Florin Terminal",
            },
        )

    @property
    def provider_name(self) -> str:
        """Identifier for this provider."""
        return "openrouter"

    @property
    def model_name(self) -> str:
        """Model identifier (e.g. 'anthropic/claude-3.5-sonnet')."""
        return self._model

    async def health_check(self) -> bool:
        """Verify OpenRouter is reachable by sending a minimal completion request.

        Returns:
            True if the API responds successfully, False otherwise.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Say ok"}],
            )
            return bool(response.choices and response.choices[0].message.content)
        except Exception:
            logger.debug("OpenRouter health check failed", exc_info=True)
            return False

    async def analyse_announcements(
        self,
        ticker: str,
        filings: list[Form8KFiling],
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse Form 8-K filings via OpenRouter.

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
        """Analyse market sentiment via OpenRouter.

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
        """Send a prompt to the OpenRouter API and parse the response.

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
            logger.exception("OpenRouter analysis failed")
            return AnalysisResult(
                provider=self.provider_name,
                model=self._model,
                analysis_type=analysis_type,
                latency_ms=latency,
                error=str(e),
            )
