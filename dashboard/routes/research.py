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


class YieldCurveHistoryResponse(BaseModel):
    dates: list[str]
    tenors: dict[str, list[float | None]]


class IVSkewPoint(BaseModel):
    strike: float
    moneyness: float = 0.0
    call_iv: float | None = None
    put_iv: float | None = None
    raw_call_iv: float | None = None
    raw_put_iv: float | None = None
    vol: float | None = None
    spread: float | None = None


class IVTermPoint(BaseModel):
    expiry: str
    call_iv: float
    put_iv: float
    spread: float


class PutCallIVResponse(BaseModel):
    ticker: str
    spot: float
    skew_expiry: str = ""
    available_expiries: list[str] = []
    skew: list[IVSkewPoint]
    term_structure: list[IVTermPoint]


class MacroIndicator(BaseModel):
    ticker: str = ""
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
    start: str = Query(default="", description="Custom start date (YYYY-MM-DD)"),
    end: str = Query(default="", description="Custom end date (YYYY-MM-DD)"),
    yf=Depends(get_yfinance_dep),
):
    """Historical OHLCV data. Use start/end for custom date ranges, or period for presets."""
    if start and end:
        history = await yf.get_history(ticker.upper(), start=start, end=end, interval=interval)
    else:
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

    # Get the available analysers
    from dashboard.deps import _state
    analysers = _state.get("analysers", {})
    default_provider = settings.llm_default_provider.value

    analyser = analysers.get(default_provider)
    if not analyser:
        # Try any non-finbert analyser
        for name, a in analysers.items():
            if name != "finbert":
                analyser = a
                break

    if not analyser:
        raise ServiceUnavailableError(
            "No LLM analysers available. Configure Groq, Claude, Gemini, or start Ollama."
        )

    # Build a minimal AlertSignal and empty sentiment/fraud for the standard analyse() interface
    from core.models import AlertSignal, FraudRiskScore, SentimentData

    alert = AlertSignal(
        ticker=ticker,
        price=info.get("current_price") or 0.0,
        change_pct=0.0,
        volume=0,
    )
    sentiment = SentimentData()
    fraud_risk = FraudRiskScore()

    try:
        analysis = await analyser.analyse(alert, sentiment, fraud_risk)
    except Exception as e:
        logger.exception("LLM analysis failed for %s", ticker)
        # Return error in response body rather than 502, so the frontend can show it
        return LLMAnalysisResponse(
            ticker=ticker,
            provider=getattr(analyser, "provider_name", "unknown"),
            error=f"LLM connection failed: {e}",
        )

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
    region: str = Query(default="US"),
    yf=Depends(get_yfinance_dep),
):
    """US Treasury yield curve data points."""
    data = await yf.get_yield_curve("US")
    return YieldCurveResponse(**data)


@router.get("/research/yield-curve/history", response_model=YieldCurveHistoryResponse)
async def get_yield_curve_history(
    period: str = Query(default="1y", pattern="^(1mo|3mo|6mo|1y|2y|5y)$"),
    yf=Depends(get_yfinance_dep),
):
    """Historical US Treasury yield curves over time."""
    data = await yf.get_yield_curve_history(period)
    return YieldCurveHistoryResponse(**data)


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


# =============================================================================
# Holders
# =============================================================================

class HolderEntry(BaseModel):
    holder: str
    shares: int = 0
    value: float = 0
    pct_held: float = 0
    pct_change: float = 0
    date_reported: str = ""


class MajorHolderBreakdown(BaseModel):
    insiders_pct: float = 0
    institutions_pct: float = 0
    institutions_float_pct: float = 0
    institutions_count: int = 0


class HoldersResponse(BaseModel):
    ticker: str
    major: MajorHolderBreakdown | None = None
    institutional: list[HolderEntry] = []
    mutual_fund: list[HolderEntry] = []


@router.get("/research/holders/{ticker}", response_model=HoldersResponse)
async def get_holders(
    ticker: str,
    yf=Depends(get_yfinance_dep),
):
    """Top institutional and mutual fund holders for a ticker."""
    data = await yf.get_holders(ticker.upper())
    return HoldersResponse(ticker=ticker.upper(), **data)


@router.get("/research/iv-spread", response_model=PutCallIVResponse)
async def get_put_call_iv_spread(
    ticker: str = Query(default="SPY", description="Equity ticker (default SPY)"),
    expiry: str = Query(default="", description="Specific expiry date (YYYY-MM-DD), empty for auto-select"),
    yf=Depends(get_yfinance_dep),
):
    """Put-call implied volatility spread: skew across strikes and term structure."""
    data = await yf.get_put_call_iv_spread(ticker.upper(), expiry=expiry or None)
    return PutCallIVResponse(**data)
