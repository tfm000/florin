"""
Anthropic Claude analyser.

Uses Claude Haiku 4.5 for high-quality analysis at low cost.
Default meta-analyser for consensus mode.
"""

from __future__ import annotations

import logging
import time

import anthropic

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AlertSignal, LLMAnalysis, SentimentData

logger = logging.getLogger(__name__)


class ClaudeAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Anthropic Claude."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.claude_model
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Say ok"}],
            )
            return len(response.content) > 0
        except Exception:
            return False

    async def analyse(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
    ) -> LLMAnalysis:
        start = time.monotonic()

        try:
            user_prompt = build_user_prompt(alert, sentiment, self._settings.llm_user_context)

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.3,
            )

            raw = response.content[0].text if response.content else ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Claude analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self._model,
                latency_ms=latency,
                error=str(e),
            )
