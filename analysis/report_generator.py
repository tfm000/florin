"""
Single-LLM report generator (single mode).

Runs one configured LLM analyser on the requested analysis type(s)
and produces an AnalysisReport. Supports announcement analysis,
sentiment analysis, or both.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from analysis.base import LLMAnalyser
from config.settings import Settings
from core.models import (
    AlertSignal,
    AnalysisReport,
    AnalysisResult,
    Form8KFiling,
    Recommendation,
    SentimentData,
)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Single-model report generator.

    Sends data to one configured LLM provider and produces an
    AnalysisReport with the analysis results. Supports running
    announcement analysis, sentiment analysis, or both concurrently.

    Args:
        analysers: Dict mapping provider name to LLMAnalyser instance.
        settings: Application settings for provider selection.
    """

    def __init__(
        self,
        analysers: dict[str, LLMAnalyser],
        settings: Settings,
    ) -> None:
        self._analysers = analysers
        self._default_provider = settings.llm_default_provider.value
        self._user_context = settings.llm_user_context

    async def generate(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
        filings: list[Form8KFiling] | None = None,
        analysis_types: list[str] | None = None,
    ) -> AnalysisReport:
        """Generate a single-LLM analysis report.

        Args:
            alert: The momentum alert signal.
            sentiment: Aggregated sentiment data.
            filings: Optional Form 8-K filings for announcement analysis.
            analysis_types: List of analysis types to run. Defaults to
                ["announcement", "sentiment"]. Pass ["announcement"] or
                ["sentiment"] to run only one type.

        Returns:
            AnalysisReport with results for the requested analysis types.
        """
        if analysis_types is None:
            analysis_types = ["announcement", "sentiment"]

        # Select the analyser
        analyser = self._analysers.get(self._default_provider)
        if not analyser:
            # Fall back to first available analyser
            for _name, a in self._analysers.items():
                analyser = a
                break

        if not analyser:
            logger.error("No LLM analysers available for report generation")
            return AnalysisReport(
                id=uuid4().hex[:16],
                ticker=alert.ticker,
                alert=alert,
                sentiment=sentiment,
                filings=filings or [],
                mode="single",
            )

        logger.info(
            "Generating single-LLM report for %s via %s (types=%s)",
            alert.ticker, analyser.provider_name, analysis_types,
        )

        # Build alert context for sentiment prompts
        alert_context = {
            "price": alert.price,
            "change_pct": alert.change_pct,
            "volume": alert.volume,
            "avg_volume": alert.avg_volume,
        }

        # Run requested analysis types concurrently
        announcement_result: AnalysisResult | None = None
        sentiment_result: AnalysisResult | None = None

        tasks: dict[str, asyncio.Task] = {}

        if "announcement" in analysis_types and filings:
            tasks["announcement"] = asyncio.create_task(
                analyser.analyse_announcements(alert.ticker, filings, self._user_context)
            )

        if "sentiment" in analysis_types:
            tasks["sentiment"] = asyncio.create_task(
                analyser.analyse_sentiment(
                    alert.ticker, sentiment, alert_context, self._user_context,
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    logger.error("Analysis %s failed: %s", key, result)
                    error_result = AnalysisResult(
                        provider=analyser.provider_name,
                        model=analyser.model_name,
                        error=str(result),
                    )
                    if key == "announcement":
                        announcement_result = error_result
                    else:
                        sentiment_result = error_result
                else:
                    if key == "announcement":
                        announcement_result = result
                    else:
                        sentiment_result = result

        # Determine final scores and recommendation
        best = sentiment_result or announcement_result
        final_rec = best.recommendation if best and not best.error else Recommendation.HOLD
        final_conf = best.confidence if best and not best.error else 0.0

        report = AnalysisReport(
            id=uuid4().hex[:16],
            ticker=alert.ticker,
            alert=alert,
            sentiment=sentiment,
            filings=filings or [],
            announcement_analysis=announcement_result,
            sentiment_analysis=sentiment_result,
            announcement_score=announcement_result.score if announcement_result and not announcement_result.error else None,
            sentiment_score=sentiment_result.score if sentiment_result and not sentiment_result.error else None,
            final_recommendation=final_rec,
            final_confidence=final_conf,
            mode="single",
        )

        logger.info(
            "Report generated for %s: rec=%s, announcement_score=%s, sentiment_score=%s",
            alert.ticker,
            final_rec.value,
            report.announcement_score,
            report.sentiment_score,
        )

        return report
