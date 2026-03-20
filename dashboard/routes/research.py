"""
Research API endpoints — asset search, info, history, analysis, news, yield curves, rates.

All endpoints use Pydantic response models and FastAPI Depends() for DI.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.exceptions import ExternalServiceError, NotFoundError, ServiceUnavailableError
from dashboard.dependencies import get_settings_dep, get_yfinance_dep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"])


# =============================================================================
# Response schemas
# =============================================================================

class SearchResult(BaseModel):
    ticker: str
    name: str
    exchange: str
    type: str


class AssetInfo(BaseModel):
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    short_interest: float | None = None
    exchange: str = ""
    shares_outstanding: int | None = None
    current_price: float | None = None
    previous_close: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    currency: str = "USD"
    quote_type: str = ""
    # Performance metrics (joined)
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    return_1m: float | None = None
    return_6m: float | None = None
    return_1y: float | None = None
    return_3y: float | None = None


class HistoryPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class NewsItem(BaseModel):
    title: str
    publisher: str = ""
    url: str = ""
    published_at: str = ""
    summary: str = ""


class YieldCurveResponse(BaseModel):
    region: str
    curve: dict[str, float]


class PolicyRate(BaseModel):
    country: str
    central_bank: str
    rate: float
    currency: str


class MacroIndicator(BaseModel):
    price: float
    change_pct: float


class MacroSummary(BaseModel):
    indicators: dict[str, MacroIndicator]


class LLMAnalysisResponse(BaseModel):
    ticker: str
    provider: str = ""
    model: str = ""
    sentiment_score: float = 0.0
    confidence: float = 0.5
    bullish_signals: list[str] = []
    bearish_signals: list[str] = []
    recommendation: str = "HOLD"
    summary: str = ""
    key_factors: list[str] = []
    error: str | None = None


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/research/search", response_model=list[SearchResult])
async def search_assets(
    q: str = Query(..., min_length=1, max_length=30, description="Search query"),
    yf=Depends(get_yfinance_dep),
):
    """Search tickers by name or symbol."""
    results = await yf.search(q)
    return [SearchResult(**r) for r in results]


@router.get("/research/asset/{ticker}", response_model=AssetInfo)
async def get_asset_info(
    ticker: str,
    yf=Depends(get_yfinance_dep),
):
    """Full asset info with performance metrics."""
    info = await yf.get_info(ticker.upper())
    if not info.get("name") and not info.get("current_price"):
        raise NotFoundError(f"No data found for ticker {ticker.upper()}")

    performance = await yf.get_performance_metrics(ticker.upper())

    return AssetInfo(
        **{k: v for k, v in info.items() if k in AssetInfo.model_fields},
        sharpe_ratio=performance.get("sharpe_ratio"),
        max_drawdown_pct=performance.get("max_drawdown_pct"),
        return_1m=performance.get("return_1m"),
        return_6m=performance.get("return_6m"),
        return_1y=performance.get("return_1y"),
        return_3y=performance.get("return_3y"),
    )


@router.get("/research/asset/{ticker}/history", response_model=list[HistoryPoint])
async def get_asset_history(
    ticker: str,
    period: str = Query(default="1y", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$"),
    interval: str = Query(default="1d", pattern="^(1m|2m|5m|15m|30m|60m|90m|1h|1d|5d|1wk|1mo|3mo)$"),
    yf=Depends(get_yfinance_dep),
):
    """Historical OHLCV data."""
    history = await yf.get_history(ticker.upper(), period=period, interval=interval)
    return [HistoryPoint(**h) for h in history]


@router.post("/research/asset/{ticker}/analyse", response_model=LLMAnalysisResponse)
async def analyse_asset(
    ticker: str,
    yf=Depends(get_yfinance_dep),
    settings=Depends(get_settings_dep),
):
    """
    Generate an LLM analysis report for any asset.

    Enriches the prompt with macro context, news, and performance data.
    """
    from analysis._prompt_helper import build_research_prompt, parse_llm_response
    from dashboard.deps import get_settings as _get_settings

    ticker = ticker.upper()

    # Gather data concurrently
    import asyncio
    info_task = yf.get_info(ticker)
    perf_task = yf.get_performance_metrics(ticker)
    macro_task = yf.get_macro_summary()
    news_task = yf.get_news(ticker)

    info, performance, macro, news = await asyncio.gather(
        info_task, perf_task, macro_task, news_task
    )

    if not info.get("name") and not info.get("current_price"):
        raise NotFoundError(f"No data found for ticker {ticker}")

    # Build the prompt
    prompt = build_research_prompt(
        asset_info=info,
        performance=performance,
        macro=macro,
        news=news,
        user_context=settings.llm_user_context,
    )

    # Get the default analyser
    from dashboard.deps import _state
    analysers = _state.get("analysers", {})
    default_provider = settings.llm_default_provider.value

    analyser = analysers.get(default_provider)
    if not analyser:
        for name, a in analysers.items():
            if name != "finbert":
                analyser = a
                break

    if not analyser:
        raise ServiceUnavailableError("No LLM analysers available")

    # Build minimal objects for the analyser interface
    from config.constants import RESEARCH_ANALYSIS_SYSTEM_PROMPT
    from core.models import AlertSignal, FraudRiskScore, SentimentData

    # Use the analyser's raw call if available, otherwise go through analyse()
    import time
    start = time.monotonic()

    try:
        if hasattr(analyser, "_call_llm"):
            raw = await analyser._call_llm(RESEARCH_ANALYSIS_SYSTEM_PROMPT, prompt)
        elif hasattr(analyser, "_generate"):
            raw = await analyser._generate(RESEARCH_ANALYSIS_SYSTEM_PROMPT, prompt)
        else:
            # Fallback: construct minimal alert and use standard analyse()
            alert = AlertSignal(
                ticker=ticker,
                price=info.get("current_price") or 0.0,
                change_pct=0.0,
                volume=0,
            )
            sentiment = SentimentData()
            fraud_risk = FraudRiskScore()
            analysis = await analyser.analyse(alert, sentiment, fraud_risk)
            return LLMAnalysisResponse(
                ticker=ticker,
                provider=analysis.provider,
                model=analysis.model,
                sentiment_score=analysis.sentiment_score,
                confidence=analysis.confidence,
                bullish_signals=analysis.bullish_signals,
                bearish_signals=analysis.bearish_signals,
                recommendation=analysis.recommendation.value,
                summary=analysis.summary,
                key_factors=analysis.key_factors,
                error=analysis.error,
            )

        latency = int((time.monotonic() - start) * 1000)
        analysis = parse_llm_response(
            raw, analyser.provider_name, analyser.model_name, latency,
        )
    except Exception as e:
        logger.exception("LLM analysis failed for %s", ticker)
        raise ExternalServiceError(f"LLM analysis failed: {e}")

    return LLMAnalysisResponse(
        ticker=ticker,
        provider=analysis.provider,
        model=analysis.model,
        sentiment_score=analysis.sentiment_score,
        confidence=analysis.confidence,
        bullish_signals=analysis.bullish_signals,
        bearish_signals=analysis.bearish_signals,
        recommendation=analysis.recommendation.value,
        summary=analysis.summary,
        key_factors=analysis.key_factors,
        error=analysis.error,
    )


@router.get("/research/news", response_model=list[NewsItem])
async def get_market_news(
    ticker: str = Query(default="", description="Optional ticker for ticker-specific news"),
    yf=Depends(get_yfinance_dep),
):
    """
    Market news headlines.

    If ticker is provided, returns ticker-specific news from yfinance.
    Otherwise returns general market news from major index tickers.
    """
    if ticker:
        news = await yf.get_news(ticker.upper())
    else:
        # Aggregate news from major indices
        import asyncio
        results = await asyncio.gather(
            yf.get_news("^GSPC"),
            yf.get_news("^IXIC"),
            return_exceptions=True,
        )
        news = []
        for r in results:
            if isinstance(r, list):
                news.extend(r)
        # Deduplicate by title
        seen = set()
        unique = []
        for item in news:
            if item["title"] not in seen:
                seen.add(item["title"])
                unique.append(item)
        news = unique[:20]

    return [NewsItem(**n) for n in news]


@router.get("/research/yield-curve", response_model=YieldCurveResponse)
async def get_yield_curve(
    region: str = Query(default="US", pattern="^(US|UK|Japan|Europe)$"),
    yf=Depends(get_yfinance_dep),
):
    """Treasury yield curve data points."""
    data = await yf.get_yield_curve(region)
    return YieldCurveResponse(**data)


@router.get("/research/policy-rates", response_model=list[PolicyRate])
async def get_policy_rates(
    yf=Depends(get_yfinance_dep),
):
    """G10 central bank policy rates."""
    rates = await yf.get_g10_rates()
    return [PolicyRate(**r) for r in rates]


@router.get("/research/macro", response_model=MacroSummary)
async def get_macro_summary(
    yf=Depends(get_yfinance_dep),
):
    """Macro economic indicators (VIX, DXY, indices, oil, gold)."""
    data = await yf.get_macro_summary()
    indicators = {k: MacroIndicator(**v) for k, v in data.items()}
    return MacroSummary(indicators=indicators)
