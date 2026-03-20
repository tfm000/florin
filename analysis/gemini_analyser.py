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

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AlertSignal, FraudRiskScore, LLMAnalysis, SentimentData

logger = logging.getLogger(__name__)


class GeminiAnalyser(LLMAnalyser):
    """Cloud LLM analysis via Google Gemini."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model_name_str = settings.gemini_model
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._config = types.GenerateContentConfig(
            system_instruction=ANALYSIS_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=1024,
            response_mime_type="application/json",
        )

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name_str

    async def health_check(self) -> bool:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name_str,
                contents="Say 'ok'",
            )
            return response.text is not None
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

            response = await self._client.aio.models.generate_content(
                model=self._model_name_str,
                contents=user_prompt,
                config=self._config,
            )
            raw = response.text or ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model_name_str, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Gemini analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self._model_name_str,
                latency_ms=latency,
                error=str(e),
            )
