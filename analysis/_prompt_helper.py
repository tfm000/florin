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

from config.constants import ANALYSIS_SYSTEM_PROMPT, SINGLE_REPORT_PROMPT
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

    # Try to find JSON object in the text
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try removing trailing commas
    no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(no_trailing)
    except json.JSONDecodeError:
        pass

    raise ValueError(f"Could not extract JSON from response: {cleaned[:200]}")
