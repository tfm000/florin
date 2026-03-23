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

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AlertSignal, LLMAnalysis, SentimentData

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

        Uses a simple completion test rather than the /models endpoint to
        validate both connectivity and model availability in one call.

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

    async def analyse(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
    ) -> LLMAnalysis:
        """Generate structured stock analysis via OpenRouter.

        Builds a prompt from the alert and sentiment data, sends it to the
        OpenRouter API (OpenAI-compatible) requesting JSON output, and parses
        the response into an ``LLMAnalysis``.

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
            logger.exception("OpenRouter analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self._model,
                latency_ms=latency,
                error=str(e),
            )
