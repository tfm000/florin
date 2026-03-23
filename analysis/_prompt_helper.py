"""
Shared prompt building and response parsing for LLM analysers.

Provides three prompt builders:
  - ``build_announcement_prompt`` — formats Form 8-K filing data for LLM
  - ``build_sentiment_prompt`` — formats social/news sentiment data for LLM
  - ``build_consensus_prompt`` — formats individual analyst reports for the leader LLM

And a unified response parser:
  - ``parse_llm_response`` — extracts JSON from raw LLM output into AnalysisResult
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from config.constants import (
    ANNOUNCEMENT_USER_PROMPT,
    CONSENSUS_LEADER_USER_PROMPT,
    RESEARCH_ANALYSIS_PROMPT,
    SENTIMENT_USER_PROMPT,
)
from core.models import (
    AnalysisResult,
    AnalysisType,
    Form8KFiling,
    Recommendation,
    SentimentData,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_announcement_prompt(
    ticker: str,
    filings: list[Form8KFiling],
    user_context: str = "",
) -> str:
    """Build the user prompt for announcement (Form 8-K) analysis.

    Args:
        ticker: Stock symbol.
        filings: List of Form 8-K filings to include.
        user_context: Optional user-provided context.

    Returns:
        Formatted prompt string ready for the LLM.
    """
    filing_sections: list[str] = []
    for i, filing in enumerate(filings, 1):
        section = f"### Filing {i}"
        section += f"\n- Filed: {filing.filed_date.strftime('%Y-%m-%d')}"
        section += f"\n- Form Type: {filing.form_type}"
        if filing.description:
            section += f"\n- Description: {filing.description}"
        if filing.items:
            section += f"\n- 8-K Items: {', '.join(filing.items)}"
        if filing.accession_number:
            section += f"\n- Accession Number: {filing.accession_number}"
        if filing.text_content:
            section += f"\n\n#### Filing Text\n{filing.text_content}"
        else:
            section += "\n\n*(No text content available for this filing.)*"
        filing_sections.append(section)

    if not filing_sections:
        filings_text = "No Form 8-K filings found for this ticker."
    else:
        filings_text = "\n\n".join(filing_sections)

    return ANNOUNCEMENT_USER_PROMPT.format(
        ticker=ticker,
        filings_text=filings_text,
        user_context=user_context or "No additional context provided.",
    )


def build_sentiment_prompt(
    ticker: str,
    sentiment: SentimentData,
    alert_context: dict | None = None,
    user_context: str = "",
) -> str:
    """Build the user prompt for sentiment analysis.

    Args:
        ticker: Stock symbol.
        sentiment: Aggregated sentiment data from all sources.
        alert_context: Optional dict with price, change_pct, volume, avg_volume.
        user_context: Optional user-provided context.

    Returns:
        Formatted prompt string ready for the LLM.
    """
    ctx = alert_context or {}
    return SENTIMENT_USER_PROMPT.format(
        ticker=ticker,
        price=ctx.get("price", 0.0),
        change_pct=ctx.get("change_pct", 0.0),
        volume=ctx.get("volume", 0),
        avg_volume=ctx.get("avg_volume", 0),
        sentiment_summary=sentiment.to_summary(),
        user_context=user_context or "No additional context provided.",
    )


def build_consensus_prompt(
    ticker: str,
    analysis_type: str,
    individual_results: list[AnalysisResult],
) -> str:
    """Build the user prompt for the consensus leader LLM.

    Args:
        ticker: Stock symbol.
        analysis_type: "announcement" or "sentiment".
        individual_results: List of AnalysisResult from individual analysts.

    Returns:
        Formatted prompt string for the consensus leader.
    """
    reports: list[str] = []
    for i, result in enumerate(individual_results, 1):
        report = (
            f"### Analyst {i} ({result.provider}/{result.model})\n"
            f"- Score: {result.score}/10\n"
            f"- Confidence: {result.confidence:.0%}\n"
            f"- Recommendation: {result.recommendation.value}\n"
            f"- Bullish Signals: {', '.join(result.bullish_signals) or 'None'}\n"
            f"- Bearish Signals: {', '.join(result.bearish_signals) or 'None'}\n"
            f"- Key Points: {', '.join(result.key_points) or 'None'}\n"
            f"- Summary: {result.summary}\n"
        )
        reports.append(report)

    individual_reports = "\n".join(reports) if reports else "No analyst reports available."

    return CONSENSUS_LEADER_USER_PROMPT.format(
        ticker=ticker,
        analysis_type=analysis_type,
        individual_reports=individual_reports,
    )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def parse_llm_response(
    raw: str,
    provider: str,
    model: str,
    analysis_type: AnalysisType,
    latency_ms: int = 0,
) -> AnalysisResult:
    """Parse JSON response from any LLM into an AnalysisResult.

    Handles common JSON extraction issues:
    - Markdown code fences around JSON
    - Trailing commas
    - Partial responses

    Args:
        raw: Raw text response from the LLM.
        provider: Provider identifier (e.g. "openai").
        model: Model identifier (e.g. "gpt-4o-mini").
        analysis_type: The type of analysis this result represents.
        latency_ms: Time taken for the API call in milliseconds.

    Returns:
        Parsed AnalysisResult. On parse failure, returns a result with
        the ``error`` field set.
    """
    try:
        parsed = _extract_json(raw)

        # Map recommendation string to enum with fallback
        rec_str = parsed.get("recommendation", "HOLD")
        try:
            recommendation = Recommendation(rec_str)
        except ValueError:
            recommendation = Recommendation.HOLD

        # Clamp score to 0–10 range
        raw_score = float(parsed.get("score", 5.0))
        score = max(0.0, min(10.0, raw_score))

        # Clamp confidence to 0–1 range
        raw_confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, raw_confidence))

        return AnalysisResult(
            provider=provider,
            model=model,
            analysis_type=analysis_type,
            score=score,
            confidence=confidence,
            summary=parsed.get("summary", ""),
            key_points=parsed.get("key_points", []),
            bullish_signals=parsed.get("bullish_signals", []),
            bearish_signals=parsed.get("bearish_signals", []),
            recommendation=recommendation,
            raw_response=raw,
            latency_ms=latency_ms,
        )

    except Exception as e:
        logger.warning("Failed to parse LLM response from %s: %s", provider, e)
        return AnalysisResult(
            provider=provider,
            model=model,
            analysis_type=analysis_type,
            raw_response=raw,
            latency_ms=latency_ms,
            error=f"Failed to parse response: {e}",
        )


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> dict[str, Any]:
    """Extract JSON from an LLM response, handling common formatting issues.

    Attempts in order:
    1. Direct parse after stripping markdown code fences.
    2. Scan for '{' characters and attempt parse from each.
    3. Retry with trailing comma removal.

    Args:
        raw: Raw text that should contain a JSON object.

    Returns:
        Parsed dict from the JSON.

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    # Strip markdown code fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (possibly with language tag)
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text — find each '{' and attempt parse
    for i, ch in enumerate(cleaned):
        if ch == '{':
            try:
                return json.loads(cleaned[i:])
            except json.JSONDecodeError:
                # Try with trailing comma removal
                candidate = re.sub(r",\s*([}\]])", r"\1", cleaned[i:])
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    raise ValueError(f"Could not extract JSON from response: {cleaned[:200]}")


# ---------------------------------------------------------------------------
# Research prompt builder (kept for research tab)
# ---------------------------------------------------------------------------


def build_research_prompt(
    asset_info: dict,
    performance: dict,
    macro: dict,
    news: list[dict],
    user_context: str = "",
) -> str:
    """Build prompt for research analysis (any asset).

    Args:
        asset_info: Dict with ticker, name, sector, industry, market_cap, etc.
        performance: Dict with sharpe_ratio, max_drawdown_pct, return_*, etc.
        macro: Dict of macro indicators with price and change_pct.
        news: List of news article dicts with title and publisher.
        user_context: Optional user-provided context.

    Returns:
        Formatted prompt string for the research analysis.
    """
    # Format performance metrics
    perf_lines = []
    if performance:
        for key, label in [
            ("sharpe_ratio", "Sharpe Ratio"),
            ("max_drawdown_pct", "Max Drawdown"),
            ("return_1m", "1M Return"),
            ("return_6m", "6M Return"),
            ("return_1y", "1Y Return"),
            ("return_3y", "3Y Return"),
        ]:
            val = performance.get(key)
            if val is not None:
                if "return" in key or "drawdown" in key:
                    perf_lines.append(f"- {label}: {val:+.2f}%")
                else:
                    perf_lines.append(f"- {label}: {val:.2f}")
    performance_summary = "\n".join(perf_lines) if perf_lines else "No performance data available."

    # Format macro context
    macro_lines = []
    for label, data in macro.items():
        if isinstance(data, dict):
            price = data.get("price", "N/A")
            change = data.get("change_pct", 0)
            macro_lines.append(f"- {label}: {price} ({change:+.2f}%)")
    macro_summary = "\n".join(macro_lines) if macro_lines else "No macro data available."

    # Format news
    news_lines = []
    for article in news[:8]:
        title = article.get("title", "")
        publisher = article.get("publisher", "")
        if title:
            news_lines.append(f"- {title} ({publisher})")
    news_summary = "\n".join(news_lines) if news_lines else "No recent news found."

    # Format values for the prompt
    def _fmt(val: Any, prefix: str = "", suffix: str = "") -> str:
        if val is None:
            return "N/A"
        return f"{prefix}{val}{suffix}"

    return RESEARCH_ANALYSIS_PROMPT.format(
        ticker=asset_info.get("ticker", ""),
        name=asset_info.get("name", ""),
        sector=asset_info.get("sector", "N/A"),
        industry=asset_info.get("industry", "N/A"),
        market_cap=_fmt(asset_info.get("market_cap")),
        current_price=_fmt(asset_info.get("current_price"), prefix="$"),
        pe_ratio=_fmt(asset_info.get("pe_ratio")),
        short_interest=_fmt(asset_info.get("short_interest")),
        performance_summary=performance_summary,
        macro_summary=macro_summary,
        news_summary=news_summary,
        user_context=user_context or "No additional context provided.",
    )
