"""
Multi-LLM consensus report generator (consensus mode).

Sends data to ALL configured LLMs concurrently for the same analysis type,
collects individual reports, then sends all reports to a leader LLM which
synthesises a consensus view noting variance in analyst opinion.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from analysis._prompt_helper import build_consensus_prompt, parse_llm_response
from analysis.base import LLMAnalyser
from config.constants import CONSENSUS_LEADER_SYSTEM_PROMPT
from config.settings import Settings
from core.models import (
    AlertSignal,
    AnalysisReport,
    AnalysisResult,
    AnalysisType,
    Form8KFiling,
    Recommendation,
    SentimentData,
)

logger = logging.getLogger(__name__)


class ConsensusGenerator:
    """Multi-model consensus report generator.

    Workflow:
    1. Run all enabled LLM analysers concurrently on the same analysis task.
    2. Collect individual results (including errors).
    3. Send successful results to a designated leader LLM for synthesis.
    4. Leader produces a consensus score/summary noting analyst variance.

    If the leader fails, falls back to simple averaging of individual results.

    Args:
        analysers: Dict mapping provider name to LLMAnalyser instance.
        settings: Application settings for leader model selection.
    """

    def __init__(
        self,
        analysers: dict[str, LLMAnalyser],
        settings: Settings,
    ) -> None:
        self._analysers = analysers
        self._meta_provider = settings.llm_consensus_meta_provider.value
        # Model ID for the consensus leader (from DB model registry)
        self._leader_model_id = settings.llm_consensus_leader_model_id
        self._user_context = settings.llm_user_context

    async def generate(
        self,
        alert: AlertSignal,
        sentiment: SentimentData,
        filings: list[Form8KFiling] | None = None,
        analysis_types: list[str] | None = None,
    ) -> AnalysisReport:
        """Generate a multi-LLM consensus report.

        Args:
            alert: The momentum alert signal.
            sentiment: Aggregated sentiment data.
            filings: Optional Form 8-K filings for announcement analysis.
            analysis_types: Which analysis types to run. Defaults to both.

        Returns:
            AnalysisReport with individual + consensus results.
        """
        if analysis_types is None:
            analysis_types = ["announcement", "sentiment"]

        alert_context = {
            "price": alert.price,
            "change_pct": alert.change_pct,
            "volume": alert.volume,
            "avg_volume": alert.avg_volume,
        }

        # Results containers
        announcement_analyses: list[AnalysisResult] = []
        sentiment_analyses: list[AnalysisResult] = []
        announcement_consensus: AnalysisResult | None = None
        sentiment_consensus: AnalysisResult | None = None

        # Run announcement analysis across all models
        if "announcement" in analysis_types and filings:
            announcement_analyses = await self._run_all_models(
                analysis_type=AnalysisType.ANNOUNCEMENT,
                ticker=alert.ticker,
                filings=filings,
            )
            successful = [a for a in announcement_analyses if not a.error]
            if len(successful) >= 2:
                announcement_consensus = await self._run_leader(
                    alert.ticker,
                    "announcement",
                    successful,
                )
            elif len(successful) == 1:
                # Only 1 model — use its result directly, note in summary
                single = successful[0]
                announcement_consensus = AnalysisResult(
                    provider=f"{single.provider}_solo",
                    model=single.model,
                    analysis_type=AnalysisType.ANNOUNCEMENT,
                    score=single.score,
                    confidence=single.confidence,
                    summary=(
                        "Single analyst result (consensus requested but only 1 "
                        f"model available). {single.summary}"
                    ),
                    key_points=single.key_points,
                    bullish_signals=single.bullish_signals,
                    bearish_signals=single.bearish_signals,
                    recommendation=single.recommendation,
                )

        # Run sentiment analysis across all models
        if "sentiment" in analysis_types:
            sentiment_analyses = await self._run_all_models(
                analysis_type=AnalysisType.SENTIMENT,
                ticker=alert.ticker,
                sentiment=sentiment,
                alert_context=alert_context,
            )
            successful = [a for a in sentiment_analyses if not a.error]
            if len(successful) >= 2:
                sentiment_consensus = await self._run_leader(
                    alert.ticker,
                    "sentiment",
                    successful,
                )
            elif len(successful) == 1:
                single = successful[0]
                sentiment_consensus = AnalysisResult(
                    provider=f"{single.provider}_solo",
                    model=single.model,
                    analysis_type=AnalysisType.SENTIMENT,
                    score=single.score,
                    confidence=single.confidence,
                    summary=(
                        "Single analyst result (consensus requested but only 1 "
                        f"model available). {single.summary}"
                    ),
                    key_points=single.key_points,
                    bullish_signals=single.bullish_signals,
                    bearish_signals=single.bearish_signals,
                    recommendation=single.recommendation,
                )

        # Determine final scores
        best = sentiment_consensus or announcement_consensus
        final_rec = best.recommendation if best and not best.error else Recommendation.HOLD
        final_conf = best.confidence if best and not best.error else 0.0

        report = AnalysisReport(
            id=uuid4().hex[:16],
            ticker=alert.ticker,
            alert=alert,
            sentiment=sentiment,
            filings=filings or [],
            announcement_analyses=announcement_analyses,
            sentiment_analyses=sentiment_analyses,
            announcement_consensus=announcement_consensus,
            sentiment_consensus=sentiment_consensus,
            announcement_score=(
                announcement_consensus.score
                if announcement_consensus and not announcement_consensus.error
                else None
            ),
            sentiment_score=(
                sentiment_consensus.score
                if sentiment_consensus and not sentiment_consensus.error
                else None
            ),
            final_recommendation=final_rec,
            final_confidence=final_conf,
            mode="consensus",
        )

        logger.info(
            "Consensus report for %s: rec=%s, %d announcement analysts, %d sentiment analysts",
            alert.ticker,
            final_rec.value,
            len(announcement_analyses),
            len(sentiment_analyses),
        )

        return report

    async def _run_all_models(
        self,
        analysis_type: AnalysisType,
        ticker: str,
        filings: list[Form8KFiling] | None = None,
        sentiment: SentimentData | None = None,
        alert_context: dict | None = None,
    ) -> list[AnalysisResult]:
        """Run all enabled models on the same analysis task concurrently.

        Args:
            analysis_type: ANNOUNCEMENT or SENTIMENT.
            ticker: Stock symbol.
            filings: Filings for announcement analysis.
            sentiment: Sentiment data for sentiment analysis.
            alert_context: Price/volume context for sentiment analysis.

        Returns:
            List of AnalysisResult from all models (including errors).
        """
        tasks: dict[str, asyncio.Task] = {}

        for name, analyser in self._analysers.items():
            if analysis_type == AnalysisType.ANNOUNCEMENT and filings is not None:
                tasks[name] = asyncio.create_task(
                    analyser.analyse_announcements(
                        ticker,
                        filings,
                        self._user_context,
                    )
                )
            elif analysis_type == AnalysisType.SENTIMENT and sentiment is not None:
                tasks[name] = asyncio.create_task(
                    analyser.analyse_sentiment(
                        ticker,
                        sentiment,
                        alert_context,
                        self._user_context,
                    )
                )

        if not tasks:
            return []

        logger.info(
            "Running %s consensus for %s across %d LLMs: %s",
            analysis_type.value,
            ticker,
            len(tasks),
            list(tasks.keys()),
        )

        raw_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        results: list[AnalysisResult] = []
        for name, raw in zip(tasks.keys(), raw_results, strict=True):
            if isinstance(raw, Exception):
                logger.warning("LLM %s failed in consensus: %s", name, raw)
                results.append(
                    AnalysisResult(
                        provider=name,
                        analysis_type=analysis_type,
                        error=str(raw),
                    )
                )
            else:
                results.append(raw)

        return results

    async def _run_leader(
        self,
        ticker: str,
        analysis_type_str: str,
        individual_results: list[AnalysisResult],
    ) -> AnalysisResult | None:
        """Run the leader LLM to synthesise individual reports into consensus.

        Args:
            ticker: Stock symbol.
            analysis_type_str: "announcement" or "sentiment".
            individual_results: Successful results from individual analysts.

        Returns:
            Consensus AnalysisResult from the leader, or simple average fallback.
        """
        # Try model ID first (DB registry), then legacy provider name
        leader = None
        if self._leader_model_id:
            leader = self._analysers.get(self._leader_model_id)
        if not leader:
            leader = self._analysers.get(self._meta_provider)
        if not leader:
            logger.warning(
                "Leader LLM not available (id=%s, provider=%s) — using simple average",
                self._leader_model_id,
                self._meta_provider,
            )
            return self._simple_average(individual_results, analysis_type_str)

        consensus_prompt = build_consensus_prompt(
            ticker,
            analysis_type_str,
            individual_results,
        )

        analysis_type = (
            AnalysisType.ANNOUNCEMENT
            if analysis_type_str == "announcement"
            else AnalysisType.SENTIMENT
        )

        start = time.monotonic()
        try:
            raw = await self._call_leader_api(leader, consensus_prompt)
            latency = int((time.monotonic() - start) * 1000)
            return parse_llm_response(
                raw,
                f"{self._meta_provider}_leader",
                leader.model_name,
                analysis_type,
                latency,
            )
        except Exception:
            logger.exception("Leader consensus failed — falling back to simple average")
            return self._simple_average(individual_results, analysis_type_str)

    async def _call_leader_api(
        self,
        leader: LLMAnalyser,
        prompt: str,
    ) -> str:
        """Call the leader LLM's underlying API with the consensus prompt.

        Handles Claude CLI (claude-agent-sdk), OpenAI-compatible
        (chat.completions), and Gemini providers.

        Args:
            leader: The LLMAnalyser instance to use as leader.
            prompt: The formatted consensus prompt.

        Returns:
            Raw text response from the leader LLM.

        Raises:
            RuntimeError: If the leader analyser type is unsupported.
        """
        # Try Claude CLI (claude-agent-sdk)
        if getattr(leader, "_is_claude_agent_sdk", False):
            return await leader._query_claude(CONSENSUS_LEADER_SYSTEM_PROMPT, prompt)

        # Try OpenAI-compatible (Groq, OpenRouter)
        if hasattr(leader, "_client") and hasattr(leader._client, "chat"):
            response = await leader._client.chat.completions.create(
                model=leader.model_name,
                messages=[
                    {"role": "system", "content": CONSENSUS_LEADER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or ""

        # Try Gemini
        if hasattr(leader, "_client") and hasattr(leader._client, "aio"):
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=CONSENSUS_LEADER_SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=4096,
                response_mime_type="application/json",
            )
            response = await leader._client.aio.models.generate_content(
                model=leader.model_name,
                contents=prompt,
                config=config,
            )
            return response.text or ""

        raise RuntimeError(f"Unsupported leader analyser type: {type(leader)}")

    def _simple_average(
        self,
        analyses: list[AnalysisResult],
        analysis_type_str: str,
    ) -> AnalysisResult:
        """Fallback: simple average of all successful analyses.

        Args:
            analyses: List of successful AnalysisResult objects.
            analysis_type_str: "announcement" or "sentiment".

        Returns:
            Averaged AnalysisResult.
        """
        analysis_type = (
            AnalysisType.ANNOUNCEMENT
            if analysis_type_str == "announcement"
            else AnalysisType.SENTIMENT
        )

        if not analyses:
            return AnalysisResult(
                provider="consensus_avg",
                analysis_type=analysis_type,
                error="No analyses to average",
            )

        avg_score = sum(a.score for a in analyses) / len(analyses)
        avg_confidence = sum(a.confidence for a in analyses) / len(analyses)

        # Majority vote on recommendation
        rec_counts: dict[Recommendation, int] = {}
        for a in analyses:
            rec_counts[a.recommendation] = rec_counts.get(a.recommendation, 0) + 1
        majority_rec = max(rec_counts, key=rec_counts.get)  # type: ignore[arg-type]

        all_bullish: list[str] = []
        all_bearish: list[str] = []
        all_key_points: list[str] = []
        for a in analyses:
            all_bullish.extend(a.bullish_signals)
            all_bearish.extend(a.bearish_signals)
            all_key_points.extend(a.key_points)

        return AnalysisResult(
            provider="consensus_avg",
            model=f"average_of_{len(analyses)}",
            analysis_type=analysis_type,
            score=round(avg_score, 2),
            confidence=round(avg_confidence, 2),
            bullish_signals=list(set(all_bullish))[:5],
            bearish_signals=list(set(all_bearish))[:5],
            key_points=list(set(all_key_points))[:5],
            recommendation=majority_rec,
            summary=(
                f"Simple average consensus from {len(analyses)} analysts. "
                f"Avg score: {avg_score:.1f}/10, "
                f"majority recommendation: {majority_rec.value}."
            ),
        )
