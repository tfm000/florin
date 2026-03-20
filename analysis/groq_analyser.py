"""
Groq analyser — ultra-fast cloud LLM inference.

Uses Groq's API with Llama 4 Scout for sub-second analysis.
~$0.0004 per report. Rate limits are generous on free tier.
"""

from __future__ import annotations

import logging
import time

from groq import AsyncGroq

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AlertSignal, FraudRiskScore, LLMAnalysis, SentimentData

logger = logging.getLogger(__name__)


class GroqAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Groq (Llama 4 Scout)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.groq_model
        self._client = AsyncGroq(api_key=settings.groq_api_key)

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_name(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        try:
            models = await self._client.models.list()
            return any(m.id == self._model for m in models.data)
        except Exception:
            return False

    async def analyse(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
        fraud_risk: FraudRiskScore,
    ) -> LLMAnalysis:
        start = time.monotonic()

        try:
            user_prompt = build_user_prompt(alert, sentiment, fraud_risk, self._settings.llm_user_context)

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content or ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Groq analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self._model,
                latency_ms=latency,
                error=str(e),
            )
