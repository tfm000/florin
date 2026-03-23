"""
OpenAI analyser — GPT-based cloud LLM analysis.

Uses the OpenAI Chat Completions API with JSON response format
for structured stock analysis. Supports any OpenAI model
(gpt-4o, gpt-4o-mini, etc.).
"""

from __future__ import annotations

import logging
import time

import openai

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AlertSignal, LLMAnalysis, SentimentData

logger = logging.getLogger(__name__)


class OpenAIAnalyser(LLMAnalyser):
    """Cloud LLM analysis via OpenAI (GPT models).

    Uses the official ``openai`` async client with JSON response format
    to produce structured analysis matching the LLMAnalysis schema.

    Args:
        settings: Application settings containing ``openai_api_key``
            and ``openai_model``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.openai_model
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    @property
    def provider_name(self) -> str:
        """Identifier for this provider."""
        return "openai"

    @property
    def model_name(self) -> str:
        """Model identifier (e.g. 'gpt-4o-mini')."""
        return self._model

    async def health_check(self) -> bool:
        """Verify the OpenAI API is reachable by sending a minimal completion request.

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
            logger.debug("OpenAI health check failed", exc_info=True)
            return False

    async def analyse(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
    ) -> LLMAnalysis:
        """Generate structured stock analysis using an OpenAI model.

        Builds a prompt from the alert and sentiment data, sends it to the
        OpenAI Chat Completions API requesting JSON output, and parses the
        response into an ``LLMAnalysis``.

        Args:
            alert: The momentum alert signal to analyse.
            sentiment: Aggregated sentiment data for the ticker.

        Returns:
            LLMAnalysis with structured fields. On failure, the ``error``
            field is populated and the analysis is still returned.
        """
        start = time.monotonic()

        try:
            user_prompt = build_user_prompt(
                alert, sentiment, self._settings.llm_user_context
            )

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content or ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("OpenAI analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self._model,
                latency_ms=latency,
                error=str(e),
            )
