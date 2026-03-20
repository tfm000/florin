"""
Single-LLM report generator (Mode 1).

Takes sentiment data + fraud risk assessment, sends to a single
configured LLM, and generates a formatted AnalysisReport.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from analysis.base import LLMAnalyser
from config.settings import LLMProvider, Settings
from core.models import (
    AlertSignal,
    AnalysisReport,
    FraudRiskScore,
    SentimentData,
)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Mode 1: Single-LLM report generation.

    Sends sentiment data to one configured LLM provider and
    produces an AnalysisReport with the final recommendation.
    """

    def __init__(
        self,
        analysers: dict[str, LLMAnalyser],
        settings: Settings,
    ) -> None:
        self._analysers = analysers
        self._default_provider = settings.llm_default_provider.value

    async def generate(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
        fraud_risk: FraudRiskScore,
    ) -> AnalysisReport:
        """
        Generate a single-LLM analysis report.

        Falls back to other providers if the default is unavailable.
        """
        # Try the default provider first
        analyser = self._analysers.get(self._default_provider)
        if not analyser:
            # Fall back to first available analyser (excluding finbert)
            for name, a in self._analysers.items():
                if name != "finbert":
                    analyser = a
                    break

        if not analyser:
            logger.error("No LLM analysers available for report generation")
            return AnalysisReport(
                id=uuid4().hex[:16],
                ticker=alert.ticker,
                alert=alert,
                sentiment=sentiment,
                fraud_risk=fraud_risk,
                mode="single",
            )

        logger.info(
            "Generating single-LLM report for %s via %s",
            alert.ticker, analyser.provider_name,
        )

        analysis = await analyser.analyse(alert, sentiment, fraud_risk)

        report = AnalysisReport(
            id=uuid4().hex[:16],
            ticker=alert.ticker,
            alert=alert,
            sentiment=sentiment,
            fraud_risk=fraud_risk,
            primary_analysis=analysis,
            final_recommendation=analysis.recommendation,
            final_score=analysis.sentiment_score,
            final_confidence=analysis.confidence,
            mode="single",
        )

        logger.info(
            "Report generated for %s: %s (score=%.1f, confidence=%.0f%%)",
            alert.ticker,
            analysis.recommendation.value,
            analysis.sentiment_score,
            analysis.confidence * 100,
        )

        return report
