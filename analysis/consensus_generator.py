"""
Multi-LLM consensus report generator (Mode 2).

Sends sentiment data to ALL configured LLMs concurrently,
collects individual reports, then sends all reports to a
meta-analyser LLM which synthesises a consensus view.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from analysis._prompt_helper import parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import ANALYSIS_SYSTEM_PROMPT, CONSENSUS_META_PROMPT
from config.settings import Settings
from core.models import (
    AlertSignal,
    AnalysisReport,
    LLMAnalysis,
    Recommendation,
    SentimentData,
)

logger = logging.getLogger(__name__)


class ConsensusGenerator:
    """
    Mode 2: Multi-LLM consensus report generation.

    1. Sends sentiment data to ALL enabled LLM providers concurrently
    2. Collects individual analysis results
    3. Sends all results to a meta-analyser (default: Claude)
    4. Meta-analyser synthesises agreement/disagreement into a consensus
    """

    def __init__(
        self,
        analysers: dict[str, LLMAnalyser],
        settings: Settings,
    ) -> None:
        self._analysers = analysers
        self._meta_provider = settings.llm_consensus_meta_provider.value

    async def generate(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
    ) -> AnalysisReport:
        """
        Generate a multi-LLM consensus report.

        Queries all available LLMs concurrently, then synthesises results.
        """
        # Step 1: Run all analysers concurrently
        analysis_tasks = {}
        for name, analyser in self._analysers.items():
            analysis_tasks[name] = analyser.analyse(alert, sentiment)

        logger.info(
            "Running consensus analysis for %s across %d LLMs: %s",
            alert.ticker, len(analysis_tasks), list(analysis_tasks.keys()),
        )

        results = await asyncio.gather(
            *analysis_tasks.values(), return_exceptions=True,
        )

        # Collect successful analyses
        individual_analyses: list[LLMAnalysis] = []
        for name, result in zip(analysis_tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("LLM %s failed in consensus: %s", name, result)
                individual_analyses.append(LLMAnalysis(
                    provider=name,
                    error=str(result),
                ))
            else:
                individual_analyses.append(result)

        successful = [a for a in individual_analyses if not a.error]

        if not successful:
            logger.error("All LLMs failed in consensus mode for %s", alert.ticker)
            return AnalysisReport(
                id=uuid4().hex[:16],
                ticker=alert.ticker,
                alert=alert,
                sentiment=sentiment,
                individual_analyses=individual_analyses,
                mode="consensus",
            )

        # Step 2: Run meta-analysis
        consensus = await self._run_meta_analysis(
            alert, individual_analyses, successful,
        )

        # Build final report
        report = AnalysisReport(
            id=uuid4().hex[:16],
            ticker=alert.ticker,
            alert=alert,
            sentiment=sentiment,
            individual_analyses=individual_analyses,
            consensus=consensus,
            final_recommendation=consensus.recommendation if consensus else Recommendation.HOLD,
            final_score=consensus.sentiment_score if consensus else 0.0,
            final_confidence=consensus.confidence if consensus else 0.0,
            mode="consensus",
        )

        logger.info(
            "Consensus report for %s: %s (score=%.1f, %d/%d LLMs succeeded)",
            alert.ticker,
            report.final_recommendation.value,
            report.final_score,
            len(successful),
            len(individual_analyses),
        )

        return report

    async def _run_meta_analysis(
        self,
        alert: AlertSignal,
        all_analyses: list[LLMAnalysis],
        successful: list[LLMAnalysis],
    ) -> LLMAnalysis | None:
        """
        Send individual reports to the meta-analyser for synthesis.

        If the meta-analyser is unavailable, falls back to simple averaging.
        """
        meta_analyser = self._analysers.get(self._meta_provider)

        if not meta_analyser:
            logger.warning(
                "Meta-analyser %s not available — using simple average",
                self._meta_provider,
            )
            return self._simple_average(successful)

        # Build the meta-prompt
        individual_reports = self._format_individual_reports(successful)
        meta_prompt = CONSENSUS_META_PROMPT.format(
            individual_reports=individual_reports,
        )

        start = time.monotonic()
        try:
            # Use the meta-analyser's underlying API directly
            # by wrapping the consensus prompt as a fake alert analysis
            if hasattr(meta_analyser, '_client'):
                raw = await self._call_meta_analyser(meta_analyser, meta_prompt)
                latency = int((time.monotonic() - start) * 1000)
                return parse_llm_response(
                    raw, f"{self._meta_provider}_meta",
                    meta_analyser.model_name, latency,
                )
        except Exception:
            logger.exception("Meta-analysis failed — falling back to simple average")

        return self._simple_average(successful)

    async def _call_meta_analyser(
        self, analyser: LLMAnalyser, prompt: str,
    ) -> str:
        """Call the meta-analyser's underlying API with the consensus prompt."""
        # Try Anthropic Claude
        if hasattr(analyser, '_client') and hasattr(analyser._client, 'messages'):
            response = await analyser._client.messages.create(
                model=analyser.model_name,
                max_tokens=1500,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.content[0].text if response.content else ""

        # Try Groq
        if hasattr(analyser, '_client') and hasattr(analyser._client, 'chat'):
            response = await analyser._client.chat.completions.create(
                model=analyser.model_name,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )
            return response.choices[0].message.content or ""

        raise RuntimeError(f"Unsupported meta-analyser type: {type(analyser)}")

    def _format_individual_reports(self, analyses: list[LLMAnalysis]) -> str:
        """Format individual analyses for the meta-prompt."""
        reports = []
        for i, analysis in enumerate(analyses, 1):
            report = (
                f"### Analyst {i} ({analysis.provider}/{analysis.model})\n"
                f"- Sentiment Score: {analysis.sentiment_score}/10\n"
                f"- Confidence: {analysis.confidence:.0%}\n"
                f"- Recommendation: {analysis.recommendation.value}\n"
                f"- Risk Level: {analysis.risk_level}/5\n"
                f"- Bullish Signals: {', '.join(analysis.bullish_signals) or 'None'}\n"
                f"- Bearish Signals: {', '.join(analysis.bearish_signals) or 'None'}\n"
                f"- Summary: {analysis.summary}\n"
            )
            reports.append(report)

        return "\n".join(reports)

    def _simple_average(self, analyses: list[LLMAnalysis]) -> LLMAnalysis:
        """Fallback: simple average of all successful analyses."""
        if not analyses:
            return LLMAnalysis(provider="consensus_avg", error="No analyses to average")

        avg_score = sum(a.sentiment_score for a in analyses) / len(analyses)
        avg_confidence = sum(a.confidence for a in analyses) / len(analyses)
        avg_risk = round(sum(a.risk_level for a in analyses) / len(analyses))

        # Majority vote on recommendation
        rec_counts: dict[Recommendation, int] = {}
        for a in analyses:
            rec_counts[a.recommendation] = rec_counts.get(a.recommendation, 0) + 1
        majority_rec = max(rec_counts, key=rec_counts.get)  # type: ignore[arg-type]

        all_bullish = []
        all_bearish = []
        for a in analyses:
            all_bullish.extend(a.bullish_signals)
            all_bearish.extend(a.bearish_signals)

        return LLMAnalysis(
            provider="consensus_avg",
            model=f"average_of_{len(analyses)}",
            sentiment_score=round(avg_score, 2),
            confidence=round(avg_confidence, 2),
            bullish_signals=list(set(all_bullish))[:5],
            bearish_signals=list(set(all_bearish))[:5],
            risk_level=avg_risk,
            recommendation=majority_rec,
            summary=f"Simple average consensus from {len(analyses)} LLMs. "
                    f"Avg score: {avg_score:.1f}, majority recommendation: {majority_rec.value}.",
        )
