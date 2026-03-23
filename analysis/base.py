"""
Abstract interface for LLM analysis providers.

Implementations: GroqAnalyser, GeminiAnalyser, ClaudeAnalyser
All produce the same LLMAnalysis output — fully interchangeable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import AlertSignal, LLMAnalysis, SentimentData


class LLMAnalyser(ABC):
    """
    Interface for any LLM-based stock analysis provider.

    Given an alert + sentiment data, produces a structured LLMAnalysis
    with recommendation and reasoning.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier for this provider (e.g., 'groq', 'claude')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model being used (e.g., 'llama-4-scout-17b-16e-instruct')."""
        ...

    @abstractmethod
    async def analyse(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
    ) -> LLMAnalysis:
        """
        Generate analysis for a stock alert.

        Must return LLMAnalysis even on failure (with error field set).
        Should never raise — errors are captured in the response.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this LLM provider is available and responding."""
        ...

    async def __aenter__(self) -> LLMAnalyser:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass
