"""
Ollama analyser — local LLM via Ollama.

Default model: llama3.2:8b (configurable).
Connects to local Ollama instance at http://localhost:11434.

Slower than cloud APIs but free, private, and capable of
full analytical reports with reasoning.
"""

from __future__ import annotations

import logging
import time

import ollama as ollama_client

from analysis._prompt_helper import build_user_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT
from config.settings import Settings
from core.models import AlertSignal, FraudRiskScore, LLMAnalysis, SentimentData

logger = logging.getLogger(__name__)

OLLAMA_TIMEOUT_SECONDS = 60


class OllamaAnalyser(LLMAnalyser):
    """Local LLM analysis via Ollama."""

    def __init__(self, settings: Settings) -> None:
        self._host = settings.ollama_base_url
        self._model = settings.ollama_model
        self._client = ollama_client.AsyncClient(host=self._host)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        try:
            models = await self._client.list()
            available = [m.model for m in models.models]
            return self._model in available or any(
                self._model.split(":")[0] in m for m in available
            )
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
            user_prompt = build_user_prompt(alert, sentiment, fraud_risk)

            response = await self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": 0.3},
            )

            raw = response.message.content or ""
            latency = int((time.monotonic() - start) * 1000)

            return parse_llm_response(raw, self.provider_name, self._model, latency)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.exception("Ollama analysis failed")
            return LLMAnalysis(
                provider=self.provider_name,
                model=self._model,
                latency_ms=latency,
                error=str(e),
            )
