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
from dashboard.dependencies import get_data_provider_dep, get_settings_dep, get_yfinance_dep

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


class CompanyOfficer(BaseModel):
    name: str = ""
    title: str = ""
    age: int | None = None
    total_pay: float | None = None


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
    # Qualitative / descriptive
    long_business_summary: str = ""
    website: str = ""
    full_time_employees: int | None = None
    country: str = ""
    city: str = ""
    state: str = ""
    company_officers: list[CompanyOfficer] = []
    # Valuation ratios
    price_to_book: float | None = None
    peg_ratio: float | None = None
    enterprise_value: float | None = None
    enterprise_to_revenue: float | None = None
    enterprise_to_ebitda: float | None = None
    price_to_sales: float | None = None
    # EPS
    trailing_eps: float | None = None
    forward_eps: float | None = None
    # Analyst consensus
    target_mean_price: float | None = None
    target_high_price: float | None = None
    target_low_price: float | None = None
    analyst_count: int | None = None
    recommendation: str = ""
    # Balance sheet / liquidity
    current_ratio: float | None = None
    quick_ratio: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    operating_cashflow: float | None = None
    # Extra financials
    revenue: float | None = None
    net_income: float | None = None
    profit_margin: float | None = None
    operating_margin: float | None = None
    return_on_equity: float | None = None
    return_on_assets: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow: float | None = None
    earnings_growth: float | None = None
    revenue_growth: float | None = None
    gross_margins: float | None = None
    ebitda_margins: float | None = None
    ebitda: float | None = None
    gross_profits: float | None = None
    # Trading / per-share
    average_volume: int | None = None
    book_value: float | None = None
    revenue_per_share: float | None = None
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


class QuotePoint(BaseModel):
    """Price bar with optional bid/ask data."""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: float | None = None
    ask: float | None = None


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


def _fill_bid_ask(points: list[dict]) -> list[dict]:
    """Fill gaps in bid/ask data.

    Strategy:
    - If one of bid/ask is valid and the other is 0/None, infer from price and spread.
    - If both are missing, forward-fill from the last valid spread.
    """
    last_spread: float | None = None

    for pt in points:
        bid = pt.get("bid") or 0
        ask = pt.get("ask") or 0
        close = pt.get("close", 0)

        if bid > 0 and ask > 0:
            last_spread = ask - bid
            pt["bid"] = bid
            pt["ask"] = ask
        elif bid > 0 and ask <= 0 and close > 0:
            # Infer ask from bid + last spread, or mirror around close
            if last_spread is not None:
                pt["ask"] = round(bid + last_spread, 4)
            else:
                pt["ask"] = round(close + (close - bid), 4)
            pt["bid"] = bid
        elif ask > 0 and bid <= 0 and close > 0:
            if last_spread is not None:
                pt["bid"] = round(ask - last_spread, 4)
            else:
                pt["bid"] = round(close - (ask - close), 4)
            pt["ask"] = ask
        elif close > 0 and last_spread is not None:
            # Both missing — use close +/- half spread
            half = last_spread / 2
            pt["bid"] = round(close - half, 4)
            pt["ask"] = round(close + half, 4)
        else:
            pt["bid"] = None
            pt["ask"] = None

    return points


@router.get("/research/asset/{ticker}/quotes", response_model=list[QuotePoint])
async def get_asset_quotes(
    ticker: str,
    period: str = Query(default="1y"),
    interval: str = Query(default="1d"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    yf=Depends(get_yfinance_dep),
):
    """OHLCV + bid/ask data (interday via yfinance, current bid/ask snapshot)."""
    tick = ticker.upper()
    if start and end:
        history = await yf.get_history(tick, start=start, end=end, interval=interval)
    else:
        history = await yf.get_history(tick, period=period, interval=interval)

    if not history:
        return []

    # Get current bid/ask from yfinance info
    info = await yf.get_info(tick)
    current_bid = info.get("bid") or 0
    current_ask = info.get("ask") or 0

    # Build points — only the last bar gets the current bid/ask
    points = []
    for i, h in enumerate(history):
        pt = {**h}
        if i == len(history) - 1 and current_bid > 0 and current_ask > 0:
            pt["bid"] = current_bid
            pt["ask"] = current_ask
        else:
            pt["bid"] = None
            pt["ask"] = None
        points.append(pt)

    return [QuotePoint(**p) for p in points]


@router.get("/research/asset/{ticker}/quotes/intraday", response_model=list[QuotePoint])
async def get_asset_intraday_quotes(
    ticker: str,
    interval: str = Query(default="5Min", pattern="^(1Min|5Min|15Min|30Min|1Hour)$"),
    data_provider=Depends(get_data_provider_dep),
):
    """Intraday OHLCV + bid/ask data from Alpaca."""
    tick = ticker.upper()

    # Fetch bars and quotes concurrently
    import asyncio
    bars_task = data_provider.get_intraday_bars([tick], timeframe=interval)
    quotes_task = data_provider.get_intraday_quotes(tick)
    bars_result, raw_quotes = await asyncio.gather(bars_task, quotes_task)

    bars = bars_result.get(tick, [])
    if not bars:
        return []

    # Build a lookup: for each bar timestamp, find the closest quote
    # by bucketing quotes into bar intervals
    from datetime import datetime, timedelta

    # Parse bar timestamps
    _INTERVAL_SECONDS = {
        "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800, "1Hour": 3600,
    }
    interval_secs = _INTERVAL_SECONDS.get(interval, 300)

    # Build quote lookup keyed by bar timestamp
    quote_by_bar: dict[str, dict] = {}
    for q in raw_quotes:
        qt = datetime.fromisoformat(q["timestamp"].replace("Z", "+00:00"))
        # Floor to bar boundary
        epoch = int(qt.timestamp())
        bar_epoch = epoch - (epoch % interval_secs)
        bar_key = datetime.fromtimestamp(bar_epoch, tz=qt.tzinfo).isoformat()

        # Keep the latest quote per bar
        if bar_key not in quote_by_bar or q["timestamp"] > quote_by_bar[bar_key]["timestamp"]:
            quote_by_bar[bar_key] = q

    # Merge bars + quotes
    points = []
    for bar in bars:
        ts = bar["timestamp"]
        # Try exact match, then normalised key
        q = quote_by_bar.get(ts, {})
        if not q:
            bt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            epoch = int(bt.timestamp())
            bar_epoch = epoch - (epoch % interval_secs)
            norm_key = datetime.fromtimestamp(bar_epoch, tz=bt.tzinfo).isoformat()
            q = quote_by_bar.get(norm_key, {})

        points.append({
            "date": ts,
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
            "bid": q.get("bid", 0) if q.get("bid", 0) > 0 else None,
            "ask": q.get("ask", 0) if q.get("ask", 0) > 0 else None,
        })

    # Fill gaps
    _fill_bid_ask(points)

    return [QuotePoint(**p) for p in points]


@router.post("/research/asset/{ticker}/analyse", response_model=LLMAnalysisResponse)
async def analyse_asset(
    ticker: str,
    mode: str = Query(default="all", pattern="^(all|legitimate)$"),
    yf=Depends(get_yfinance_dep),
    settings=Depends(get_settings_dep),
):
    """
    Generate an LLM analysis report for any asset.

    Enriches the prompt with macro context, news, performance data, and sentiment.
    mode="all" uses all sentiment sources; mode="legitimate" excludes Reddit/StockTwits.
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

    # Build a minimal AlertSignal and fetch real sentiment data
    from core.models import AlertSignal, FraudRiskScore, SentimentData

    alert = AlertSignal(
        ticker=ticker,
        price=info.get("current_price") or 0.0,
        change_pct=0.0,
        volume=0,
    )

    # Fetch sentiment from aggregator (with source filtering)
    sentiment_agg = _state.get("sentiment_aggregator")
    if sentiment_agg:
        try:
            company_name = info.get("name", "")
            if mode == "legitimate":
                sentiment = await sentiment_agg.fetch_filtered(
                    ticker, company_name, ["SEC EDGAR", "News"]
                )
            else:
                sentiment = await sentiment_agg.fetch(ticker, company_name)
        except Exception as e:
            logger.warning("Sentiment fetch failed for %s: %s", ticker, e)
            sentiment = SentimentData(ticker=ticker)
    else:
        sentiment = SentimentData(ticker=ticker)

    fraud_risk = FraudRiskScore(ticker=ticker)

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
