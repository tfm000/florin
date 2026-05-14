"""
Abstract interface for LLM analysis providers.

Implementations: GroqAnalyser, GeminiAnalyser, ClaudeAnalyser (CLI), OpenRouterAnalyser
All produce AnalysisResult output with 0–10 scoring — fully interchangeable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import AnalysisResult, Form8KFiling, SentimentData


class LLMAnalyser(ABC):
    """
    Interface for any LLM-based stock analysis provider.

    Supports two analysis types:
    - **Announcement analysis**: Analyse SEC Form 8-K filings for a ticker.
    - **Sentiment analysis**: Analyse social/news sentiment for a ticker.

    Both return an ``AnalysisResult`` with a 0–10 score.
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
    async def analyse_announcements(
        self,
        ticker: str,
        filings: list[Form8KFiling],
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse SEC Form 8-K filings for a ticker.

        Args:
            ticker: Stock symbol (e.g. "AAPL").
            filings: One or more Form 8-K filings to analyse.
            user_context: Optional user-provided context to include in the prompt.

        Returns:
            AnalysisResult with analysis_type=ANNOUNCEMENT. On failure the
            ``error`` field is populated and the result is still returned.
            Should never raise — errors are captured in the response.
        """
        ...

    @abstractmethod
    async def analyse_sentiment(
        self,
        ticker: str,
        sentiment: SentimentData,
        alert_context: dict | None = None,
        user_context: str = "",
    ) -> AnalysisResult:
        """Analyse market sentiment from social/news sources for a ticker.

        Args:
            ticker: Stock symbol (e.g. "AAPL").
            sentiment: Aggregated sentiment data (Reddit, ApeWisdom, Alpha Vantage,
                web search, news).
            alert_context: Optional dict with price, change_pct, volume, avg_volume.
            user_context: Optional user-provided context to include in the prompt.

        Returns:
            AnalysisResult with analysis_type=SENTIMENT. On failure the
            ``error`` field is populated and the result is still returned.
            Should never raise — errors are captured in the response.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this LLM provider is available and responding."""
        ...

    async def __aenter__(self) -> LLMAnalyser:
        return self

    async def __aexit__(self, *args: object) -> None:  # noqa: B027 — optional teardown hook
        """No-op by default; subclasses that need teardown may override this."""
