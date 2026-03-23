"""
Shared prompt building and response parsing for LLM analysers.

All cloud LLM analysers (Groq, Gemini, Claude, Ollama) use the same
prompt template from config/constants.py and expect the same JSON output.
This module centralises that logic.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from config.constants import (
    ANALYSIS_SYSTEM_PROMPT,
    RESEARCH_ANALYSIS_PROMPT,
    SINGLE_REPORT_PROMPT,
)
from core.models import (
    AlertSignal,
    FraudRisk,
    FraudRiskScore,
    LLMAnalysis,
    Recommendation,
    SentimentData,
)

logger = logging.getLogger(__name__)


def build_user_prompt(
    alert: AlertSignal,
    sentiment: SentimentData,
    fraud_risk: FraudRiskScore,
    user_context: str = "",
) -> str:
    """Build the user prompt from alert, sentiment, and fraud data."""
    # SEC summary from filings
    sec_lines = []
    for filing in sentiment.sec_filings[:5]:
        sec_lines.append(
            f"- {filing.form_type} ({filing.description}) filed {filing.filed_date.strftime('%Y-%m-%d')}"
        )
        if filing.insider_name:
            sec_lines.append(f"  Insider: {filing.insider_name} — {filing.transaction_type}")
    sec_summary = "\n".join(sec_lines) if sec_lines else "No recent SEC filings found."

    return SINGLE_REPORT_PROMPT.format(
        ticker=alert.ticker,
        price=alert.price,
        change_pct=alert.change_pct,
        volume=alert.volume,
        avg_volume=alert.avg_volume,
        sentiment_summary=sentiment.to_summary(),
        sec_summary=sec_summary,
        fraud_summary=fraud_risk.to_summary(),
        user_context=user_context or "No additional context provided.",
    )


def parse_llm_response(
    raw: str,
    provider: str,
    model: str,
    latency_ms: int = 0,
) -> LLMAnalysis:
    """
    Parse JSON response from any LLM into an LLMAnalysis.

    Handles common JSON extraction issues:
    - Markdown code fences around JSON
    - Trailing commas
    - Partial responses
    """
    try:
        parsed = _extract_json(raw)

        # Map string values to enums with fallbacks
        rec_str = parsed.get("recommendation", "HOLD")
        try:
            recommendation = Recommendation(rec_str)
        except ValueError:
            recommendation = Recommendation.HOLD

        fraud_str = parsed.get("fraud_risk", "LOW")
        try:
            fraud_risk = FraudRisk(fraud_str)
        except ValueError:
            fraud_risk = FraudRisk.LOW

        return LLMAnalysis(
            provider=provider,
            model=model,
            sentiment_score=float(parsed.get("sentiment_score", 0.0)),
            confidence=float(parsed.get("confidence", 0.5)),
            bullish_signals=parsed.get("bullish_signals", []),
            bearish_signals=parsed.get("bearish_signals", []),
            risk_level=int(parsed.get("risk_level", 3)),
            fraud_risk=fraud_risk,
            recommendation=recommendation,
            summary=parsed.get("summary", ""),
            key_factors=parsed.get("key_factors", []),
            raw_response=raw,
            latency_ms=latency_ms,
        )

    except Exception as e:
        logger.warning("Failed to parse LLM response from %s: %s", provider, e)
        return LLMAnalysis(
            provider=provider,
            model=model,
            raw_response=raw,
            latency_ms=latency_ms,
            error=f"Failed to parse response: {e}",
        )


def _extract_json(raw: str) -> dict[str, Any]:
    """Extract JSON from an LLM response, handling common formatting issues."""
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


def build_research_prompt(
    asset_info: dict,
    performance: dict,
    macro: dict,
    news: list[dict],
    user_context: str = "",
) -> str:
    """Build prompt for research analysis (any asset, not just penny stocks)."""
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
    def _fmt(val, prefix="", suffix=""):
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
