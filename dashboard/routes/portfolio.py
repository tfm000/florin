"""
Portfolio management API — create model portfolios, analyse returns and risk.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from core.exceptions import ConflictError, NotFoundError
from dashboard.dependencies import get_db_session, get_data_provider_dep, get_yfinance_dep
from db.models import PortfolioHoldingORM, PortfolioORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portfolio"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PortfolioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    group: str | None = None
    description: str | None = None


class PortfolioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class HoldingUpdate(BaseModel):
    ticker: str = Field(..., min_length=1)
    weight: float = Field(..., ge=0, le=100)


class PortfolioResponse(BaseModel):
    id: str
    name: str
    group: str | None = None
    description: str | None = None
    holdings: list[dict] = []
    created_at: str = ""


class PortfolioAnalytics(BaseModel):
    portfolio_id: str
    period: str
    total_return: float = 0
    annualized_vol: float = 0
    sharpe: float = 0
    sortino: float = 0
    max_drawdown: float = 0
    var_95: float = 0
    cvar_95: float = 0


class IntradayAnalytics(BaseModel):
    portfolio_id: str
    interval: str
    daily_return: float = 0  # % return from open
    daily_vol: float = 0     # non-annualised volatility of intraday returns


class IntradayReturnPoint(BaseModel):
    timestamp: str
    portfolio: float  # cumulative return % from first bar


class IntradayReturnsResponse(BaseModel):
    portfolio_id: str
    interval: str
    returns: list[IntradayReturnPoint]


def _is_valid_pe_for_agg(val: float) -> bool:
    """Return True if a PE value should be included in portfolio-level aggregates.

    Negative PE ratios (from negative earnings) are excluded as they are not
    meaningful for portfolio-level analysis and distort averages.
    """
    return val > 0


class HoldingInfo(BaseModel):
    ticker: str
    weight: float
    sector: str = ""
    industry: str = ""
    pe_ratio: float | None = None
    forward_pe: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    market_cap: float | None = None
    current_price: float | None = None
    period_return: float | None = None
    period_vol: float | None = None


class HoldingsInfoResponse(BaseModel):
    portfolio_id: str
    holdings: list[HoldingInfo]
    weighted_pe: float | None = None
    weighted_forward_pe: float | None = None
    weighted_dividend_yield: float | None = None
    weighted_beta: float | None = None


class PortfolioReturnPoint(BaseModel):
    date: str
    portfolio: float  # cumulative return %


class PortfolioReturnsResponse(BaseModel):
    portfolio_id: str
    returns: list[PortfolioReturnPoint]


class PortfolioRegimePoint(BaseModel):
    date: str
    regime: int
    probability: float


class PortfolioRegimeStats(BaseModel):
    regime: int
    mean_return: float
    volatility: float
    count: int


class PortfolioRegimeResponse(BaseModel):
    portfolio_id: str
    n_regimes: int
    regimes: list[PortfolioRegimePoint]
    stats: list[PortfolioRegimeStats]


class PortfolioSummary(BaseModel):
    """Consolidated response: analytics + returns + holdings in one payload."""
    portfolio_id: str
    period: str
    analytics: PortfolioAnalytics
    returns: list[PortfolioReturnPoint]
    holdings: list[HoldingInfo]
    weighted_pe: float | None = None
    weighted_forward_pe: float | None = None
    weighted_dividend_yield: float | None = None
    weighted_beta: float | None = None
    avg_pe: float | None = None
    avg_forward_pe: float | None = None
    avg_dividend_yield: float | None = None
    avg_beta: float | None = None
    max_pe: float | None = None
    max_forward_pe: float | None = None
    max_dividend_yield: float | None = None
    max_beta: float | None = None
    min_pe: float | None = None
    min_forward_pe: float | None = None
    min_dividend_yield: float | None = None
    min_beta: float | None = None
    holdings_count: int = 0
    priceable_count: int = 0


class HoldingsInfoPageResponse(BaseModel):
    """Paginated holdings info for progressive enrichment."""
    portfolio_id: str
    holdings: list[HoldingInfo]
    offset: int
    limit: int
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_priceable_ticker(ticker: str) -> bool:
    """Return True if ticker is suitable for price history lookup.

    Filters out:
    - Bond descriptions (e.g. 'RIVN 3.625 10/15/30') which contain spaces.
    - CUSIP-like identifiers starting with a digit (e.g. '4I1').
    - Warrant/unit/rights suffixes that yfinance cannot resolve.

    Non-priceable holdings are still displayed in holdings tables.
    """
    if not ticker or " " in ticker:
        return False
    if ticker[0].isdigit():
        return False
    if any(s in ticker for s in ("-WT", "-WS", "-UN", "-RT")):
        return False
    return True


def _priceable_weights(holdings, rescale: float | None = None) -> dict[str, float]:
    """Build weight dict for priceable holdings as fractions.

    Args:
        holdings: ORM holding objects with .ticker and .weight (0-100 scale).
        rescale: If set, scale the filtered weights so they sum to this %
                 (e.g. 100 = renormalise to full allocation).
                 If None, use raw weights as-is (bond allocation is simply dropped).
    """
    raw = {h.ticker: h.weight for h in holdings if _is_priceable_ticker(h.ticker)}
    total = sum(raw.values())
    if total <= 0:
        return {}
    if rescale is not None and rescale > 0:
        factor = rescale / total
        return {t: (w * factor) / 100 for t, w in raw.items()}
    return {t: w / 100 for t, w in raw.items()}


async def _fetch_holdings(portfolio_id: str, session):
    """Load holdings ORM objects for a portfolio."""
    result = await session.execute(
        select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id)
    )
    return result.scalars().all()


def _build_portfolio_prices(tickers, weights, histories):
    """Build a synthetic portfolio price series from constituent histories.

    Uses simple returns weighted by portfolio weights, then cumulates
    into a price series starting at 100.  This produces a single price
    array that can be passed to ``compute_full_stats``.

    Returns (prices_array, common_dates) or (None, None) on insufficient data.
    """
    from stats.core import simple_returns

    date_sets = [{h["date"] for h in hist} for hist in histories if hist]
    if not date_sets or not all(date_sets):
        return None, None
    common = sorted(set.intersection(*date_sets))
    if len(common) < 10:
        return None, None

    port_simple = np.zeros(len(common) - 1)
    for i, hist in enumerate(histories):
        if not hist:
            continue
        t = tickers[i]
        w = weights.get(t, 0)
        price_map = {h["date"]: h["close"] for h in hist}
        prices = np.array([price_map[d] for d in common])
        rets = simple_returns(prices)
        port_simple += w * rets

    # Cumulate into a price series starting at 100
    port_prices = 100.0 * np.concatenate(([1.0], np.cumprod(1 + port_simple)))

    return port_prices, common


async def _fetch_histories(tickers, yf, period="1y", start="", end=""):
    """Fetch price histories for all tickers concurrently."""
    if start and end:
        return await asyncio.gather(*[yf.get_history(t, start=start, end=end) for t in tickers])
    return await asyncio.gather(*[yf.get_history(t, period=period) for t in tickers])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/portfolios", response_model=list[PortfolioResponse])
async def list_portfolios(session=Depends(get_db_session)):
    result = await session.execute(select(PortfolioORM).order_by(PortfolioORM.created_at.desc()))
    portfolios = result.scalars().all()

    if not portfolios:
        return []

    # Batch-fetch all holdings in one query to avoid N+1
    portfolio_ids = [p.id for p in portfolios]
    holdings_result = await session.execute(
        select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id.in_(portfolio_ids))
    )
    all_holdings = holdings_result.scalars().all()

    # Group holdings by portfolio_id
    holdings_by_portfolio: dict[str, list[dict]] = {}
    for h in all_holdings:
        holdings_by_portfolio.setdefault(h.portfolio_id, []).append(
            {"ticker": h.ticker, "weight": h.weight}
        )

    responses = []
    for p in portfolios:
        responses.append(PortfolioResponse(
            id=p.id, name=p.name, group=p.group, description=p.description,
            holdings=holdings_by_portfolio.get(p.id, []),
            created_at=str(p.created_at),
        ))
    return responses


@router.post("/portfolios", response_model=PortfolioResponse, status_code=201)
async def create_portfolio(req: PortfolioCreate, session=Depends(get_db_session)):
    existing = await session.execute(select(PortfolioORM).where(PortfolioORM.name == req.name))
    if existing.scalar():
        raise ConflictError(f"Portfolio '{req.name}' already exists")

    portfolio = PortfolioORM(name=req.name, group=req.group, description=req.description)
    session.add(portfolio)
    await session.commit()
    await session.refresh(portfolio)
    return PortfolioResponse(
        id=portfolio.id, name=portfolio.name, group=portfolio.group,
        description=portfolio.description, created_at=str(portfolio.created_at),
    )


@router.put("/portfolios/{portfolio_id}")
async def update_portfolio(
    portfolio_id: str,
    req: PortfolioUpdate,
    session=Depends(get_db_session),
):
    """Update portfolio metadata (name, description). 13F portfolios cannot rename."""
    result = await session.execute(select(PortfolioORM).where(PortfolioORM.id == portfolio_id))
    portfolio = result.scalar()
    if not portfolio:
        raise NotFoundError("Portfolio not found")

    is_13f = portfolio.group == "13F"

    if req.name is not None:
        if is_13f:
            raise HTTPException(403, "13F portfolio names cannot be changed")
        portfolio.name = req.name

    if req.description is not None:
        portfolio.description = req.description

    await session.commit()
    return {"status": "ok"}


@router.delete("/portfolios/{portfolio_id}")
async def delete_portfolio(portfolio_id: str, session=Depends(get_db_session)):
    result = await session.execute(select(PortfolioORM).where(PortfolioORM.id == portfolio_id))
    portfolio = result.scalar()
    if not portfolio:
        raise NotFoundError("Portfolio not found")

    await session.execute(delete(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id))
    await session.delete(portfolio)
    await session.commit()

    # Invalidate cache
    from dashboard.deps import get_db
    from dashboard.services.portfolio_cache import PortfolioCacheService
    try:
        await PortfolioCacheService(get_db()).invalidate(portfolio_id)
    except Exception:
        logger.warning("Failed to invalidate cache for deleted portfolio %s", portfolio_id)

    return {"status": "ok"}


@router.put("/portfolios/{portfolio_id}/holdings")
async def update_holdings(
    portfolio_id: str,
    holdings: list[HoldingUpdate],
    session=Depends(get_db_session),
):
    result = await session.execute(select(PortfolioORM).where(PortfolioORM.id == portfolio_id))
    portfolio = result.scalar()
    if not portfolio:
        raise NotFoundError("Portfolio not found")

    if portfolio.group == "13F":
        # Allow initial population but block subsequent modifications
        existing = await session.execute(
            select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id)
        )
        if existing.scalars().first() is not None:
            raise HTTPException(403, "13F portfolio holdings cannot be modified")

    # Replace all holdings
    await session.execute(delete(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id))
    for h in holdings:
        session.add(PortfolioHoldingORM(
            portfolio_id=portfolio_id, ticker=h.ticker.upper(), weight=h.weight,
        ))
    await session.commit()

    # Invalidate cache on holdings change
    from dashboard.deps import get_db
    from dashboard.services.portfolio_cache import PortfolioCacheService
    try:
        await PortfolioCacheService(get_db()).invalidate(portfolio_id)
    except Exception:
        logger.warning("Failed to invalidate cache for portfolio %s", portfolio_id)

    return {"status": "ok", "count": len(holdings)}


@router.get("/portfolios/{portfolio_id}/holdings-info", response_model=HoldingsInfoResponse)
async def get_holdings_info(
    portfolio_id: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Get enriched holdings data with sector/industry/fundamentals, per-holding return/vol, and weighted averages."""
    result = await session.execute(
        select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()
    if not holdings:
        return HoldingsInfoResponse(portfolio_id=portfolio_id, holdings=[])

    tickers = [h.ticker for h in holdings]
    weights = {h.ticker: h.weight for h in holdings}

    # Only fetch price data / info for priceable tickers (skip bonds)
    priceable = [_is_priceable_ticker(t) for t in tickers]
    priceable_tickers = [t for t, ok in zip(tickers, priceable) if ok]

    info_tasks = [yf.get_info(t) for t in priceable_tickers]
    history_tasks = list(_fetch_histories_coros(priceable_tickers, yf, period, start, end))
    all_results = await asyncio.gather(*info_tasks, *history_tasks)

    priceable_infos = all_results[:len(priceable_tickers)]
    priceable_histories = all_results[len(priceable_tickers):]

    # Build lookup maps for priceable results
    info_map = dict(zip(priceable_tickers, priceable_infos))
    history_map = dict(zip(priceable_tickers, priceable_histories))

    # Map back to full ticker list (non-priceable get empty defaults)
    infos = [info_map.get(t, {}) for t in tickers]
    histories = [history_map.get(t, []) for t in tickers]

    from stats.core import simple_pct_change, simple_returns, annualized_volatility

    holding_infos = []
    for i, info in enumerate(infos):
        t = tickers[i]
        hist = histories[i]

        # Compute per-holding return and vol
        p_return = None
        p_vol = None
        if hist and len(hist) >= 2:
            first_close = hist[0]["close"]
            last_close = hist[-1]["close"]
            result = simple_pct_change(last_close, first_close)
            if result is not None:
                p_return = round(result, 2)
            try:
                closes = np.array([h["close"] for h in hist])
                rets = simple_returns(closes)
                p_vol = round(annualized_volatility(rets), 2)
            except Exception:
                pass

        holding_infos.append(HoldingInfo(
            ticker=t,
            weight=weights[t],
            sector=info.get("sector", ""),
            industry=info.get("industry", ""),
            pe_ratio=info.get("pe_ratio"),
            forward_pe=info.get("forward_pe"),
            dividend_yield=info.get("dividend_yield"),
            beta=info.get("beta"),
            market_cap=info.get("market_cap"),
            current_price=info.get("current_price"),
            period_return=p_return,
            period_vol=p_vol,
        ))

    # Compute weighted averages (exclude nulls, renormalize weights)
    _pe_fields = {"pe_ratio", "forward_pe"}

    def _weighted_avg(field: str) -> float | None:
        is_pe = field in _pe_fields
        total_w = 0.0
        total_v = 0.0
        for h in holding_infos:
            val = getattr(h, field)
            if val is not None:
                if is_pe and not _is_valid_pe_for_agg(val):
                    continue
                w = h.weight / 100
                total_w += w
                total_v += w * val
        if total_w == 0:
            return None
        return round(total_v / total_w, 4)

    return HoldingsInfoResponse(
        portfolio_id=portfolio_id,
        holdings=holding_infos,
        weighted_pe=_weighted_avg("pe_ratio"),
        weighted_forward_pe=_weighted_avg("forward_pe"),
        weighted_dividend_yield=_weighted_avg("dividend_yield"),
        weighted_beta=_weighted_avg("beta"),
    )


def _fetch_histories_coros(tickers, yf, period, start, end):
    """Yield individual history coroutines (not gathered yet)."""
    for t in tickers:
        if start and end:
            yield yf.get_history(t, start=start, end=end)
        else:
            yield yf.get_history(t, period=period)


@router.get("/portfolios/{portfolio_id}/analytics", response_model=PortfolioAnalytics)
async def get_portfolio_analytics(
    portfolio_id: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    rescale_weights: float | None = Query(default=100, description="Rescale priceable weights to sum to this %. Null = use raw weights."),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Compute portfolio-level analytics from constituent returns."""
    holdings = await _fetch_holdings(portfolio_id, session)
    if not holdings:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    weights = _priceable_weights(holdings, rescale=rescale_weights)
    tickers = list(weights.keys())
    if not tickers:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    histories = await _fetch_histories(tickers, yf, period, start, end)

    # Fetch risk-free rate for portfolio's primary currency (USD default)
    from dashboard.deps import get_rf_fetcher
    rf_fetcher = get_rf_fetcher()

    # Pre-compute common dates so we can align rf rates
    port_prices, common = await asyncio.to_thread(
        _build_portfolio_prices, tickers, weights, histories,
    )
    if port_prices is None:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    # Fetch rf rates aligned to common dates (n-1 for returns)
    rf_daily = np.float64(0.0)
    if rf_fetcher and common:
        rf_full = await rf_fetcher.get_daily_rates("USD", common)
        rf_daily = rf_full[1:]  # align to returns (n-1)

    def _compute(prices, rf_daily_rates):
        from stats.core import compute_full_stats, total_return

        stats = compute_full_stats(prices, rf_daily_rates)

        total_ret = total_return(prices) or 0.0

        return {
            "total_return": round(total_ret, 2),
            "annualized_vol": round(stats.returns.annualized_volatility, 2),
            "sharpe": round(stats.risk_adjusted.sharpe, 4),
            "sortino": round(stats.risk_adjusted.sortino, 4),
            "max_drawdown": round(stats.drawdown.max_drawdown_pct, 2),
            "var_95": round(stats.var.var_95, 2),
            "cvar_95": round(stats.var.cvar_95, 2),
        }

    result = await asyncio.to_thread(_compute, port_prices, rf_daily)
    if result is None:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    return PortfolioAnalytics(portfolio_id=portfolio_id, period=period, **result)


@router.get("/portfolios/{portfolio_id}/returns", response_model=PortfolioReturnsResponse)
async def get_portfolio_returns(
    portfolio_id: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    prorated: bool = Query(default=False),
    rescale_weights: float | None = Query(default=100, description="Rescale priceable weights to sum to this %. Null = use raw weights."),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Compute portfolio cumulative return time series.

    prorated=False: only dates where ALL holdings have data (dropna).
    prorated=True: use all available dates, scale up weights for missing holdings.
    """
    empty = PortfolioReturnsResponse(portfolio_id=portfolio_id, returns=[])

    holdings = await _fetch_holdings(portfolio_id, session)
    if not holdings:
        return empty

    weights = _priceable_weights(holdings, rescale=rescale_weights)
    tickers = list(weights.keys())
    if not tickers:
        return empty

    histories = await _fetch_histories(tickers, yf, period, start, end)

    def _compute():
        # Build date → {ticker: close} map
        date_map: dict[str, dict[str, float]] = {}
        for i, hist in enumerate(histories):
            if not hist:
                continue
            t = tickers[i]
            for h in hist:
                d = h["date"][:10]
                if d not in date_map:
                    date_map[d] = {}
                date_map[d][t] = h["close"]

        if not date_map:
            return []

        all_dates = sorted(date_map.keys())
        if len(all_dates) < 2:
            return []

        # Find first price for each ticker
        first_prices: dict[str, float] = {}
        for t in tickers:
            for d in all_dates:
                price = date_map.get(d, {}).get(t)
                if price is not None and price > 0:
                    first_prices[t] = price
                    break

        # Target total weight for prorating (sum of all weights with history)
        target_total = sum(w for t, w in weights.items() if t in first_prices)

        from stats.core import simple_pct_change

        points = []
        for d in all_dates:
            port_return = 0.0
            active_weight = 0.0

            for t, w in weights.items():
                if t not in first_prices:
                    continue
                price = date_map.get(d, {}).get(t)
                if price is None:
                    # Missing data for this date → 0 return contribution
                    continue
                ret = simple_pct_change(price, first_prices[t]) or 0.0
                port_return += w * ret
                active_weight += w

            if prorated and active_weight > 0 and active_weight < target_total:
                port_return = port_return * (target_total / active_weight)

            points.append({
                "date": d,
                "portfolio": round(port_return, 2),
            })

        return points

    result = await asyncio.to_thread(_compute)
    return PortfolioReturnsResponse(
        portfolio_id=portfolio_id,
        returns=[PortfolioReturnPoint(**p) for p in result],
    )


@router.get("/portfolios/{portfolio_id}/regime", response_model=PortfolioRegimeResponse)
async def get_portfolio_regime(
    portfolio_id: str,
    n_regimes: int = Query(default=2, ge=2, le=3),
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    rescale_weights: float | None = Query(default=100, description="Rescale priceable weights to sum to this %. Null = use raw weights."),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Detect regimes on weighted portfolio returns using Markov switching."""
    empty = PortfolioRegimeResponse(
        portfolio_id=portfolio_id, n_regimes=n_regimes, regimes=[], stats=[],
    )

    holdings = await _fetch_holdings(portfolio_id, session)
    if not holdings:
        return empty

    weights = _priceable_weights(holdings, rescale=rescale_weights)
    tickers = list(weights.keys())
    if not tickers:
        return empty

    # Single fetch — reuses summary endpoint's 5y cache
    from data.yfinance_provider import _period_cutoff
    history_map = await yf.get_histories_batch(tickers, period="5y")
    max_histories = [history_map.get(t, []) for t in tickers]

    # Compute display cutoff from period — no second fetch
    if start:
        display_start = start
        display_end = end
    else:
        display_start = _period_cutoff(period) or ""
        display_end = ""

    def _compute():
        try:
            from stats.core import simple_returns
            from stats.regime import fit_markov_regimes

            port_prices, common = _build_portfolio_prices(tickers, weights, max_histories)
            if port_prices is None:
                return None

            # Simple returns scaled by 100 for numerical stability
            rets = simple_returns(port_prices)
            if not np.all(np.isfinite(rets)):
                return None
            scaled = rets * 100
            return_dates = common[1:]  # dates aligned to returns

            return fit_markov_regimes(
                scaled, return_dates, n_regimes,
                display_start=display_start, display_end=display_end,
            )
        except Exception:
            logger.exception("Portfolio regime computation failed")
            return None

    result = await asyncio.to_thread(_compute)
    if result is None:
        return empty

    return PortfolioRegimeResponse(
        portfolio_id=portfolio_id,
        n_regimes=n_regimes,
        regimes=[PortfolioRegimePoint(**r) for r in result["regimes"]],
        stats=[PortfolioRegimeStats(**s) for s in result["stats"]],
    )


# ---------------------------------------------------------------------------
# Consolidated summary endpoint
# ---------------------------------------------------------------------------

async def _compute_full_summary(
    portfolio_id: str,
    period: str,
    start: str,
    end: str,
    prorated: bool,
    rescale_weights: float | None,
    info_top_n: int,
    session,
    yf,
) -> tuple[PortfolioSummary, list[dict], list[dict]]:
    """Core computation: analytics + returns + holdings info.

    Returns (summary_for_requested_prorated_mode, prorated_returns, non_prorated_returns).
    Both return variants are computed so both can be cached in a single pass.
    """
    all_holdings = await _fetch_holdings(portfolio_id, session)
    empty_analytics = PortfolioAnalytics(portfolio_id=portfolio_id, period=period)
    empty = PortfolioSummary(
        portfolio_id=portfolio_id, period=period,
        analytics=empty_analytics, returns=[], holdings=[],
    )

    if not all_holdings:
        return empty, [], []

    weights = _priceable_weights(all_holdings, rescale=rescale_weights)
    tickers = list(weights.keys())
    all_tickers_raw = {h.ticker: h.weight for h in all_holdings}
    holdings_count = len(all_holdings)
    priceable_count = len(tickers)

    if not tickers:
        bond_holdings = [
            HoldingInfo(ticker=h.ticker, weight=h.weight)
            for h in all_holdings
        ]
        empty_with_bonds = PortfolioSummary(
            portfolio_id=portfolio_id, period=period,
            analytics=empty_analytics, returns=[], holdings=bond_holdings,
            holdings_count=holdings_count, priceable_count=0,
        )
        return empty_with_bonds, [], []

    # --- Single batch download for all priceable histories ---
    history_map = await yf.get_histories_batch(
        tickers, period=period, start=start, end=end,
    )

    # Sort tickers by weight descending for info enrichment priority
    tickers_by_weight = sorted(tickers, key=lambda t: weights.get(t, 0), reverse=True)
    top_n_tickers = tickers_by_weight[:info_top_n] if info_top_n > 0 else []

    # --- Parallel: fetch info for top N + risk-free rates ---
    from dashboard.deps import get_rf_fetcher
    rf_fetcher = get_rf_fetcher()

    # Build portfolio prices for analytics (needs to happen before rf fetch)
    histories_list = [history_map.get(t, []) for t in tickers]
    port_prices, common = await asyncio.to_thread(
        _build_portfolio_prices, tickers, weights, histories_list,
    )

    # Fetch info and rf rates in parallel
    rf_coro_result = None
    if port_prices is not None and rf_fetcher and common:
        info_result, rf_coro_result = await asyncio.gather(
            yf.get_info_batch(top_n_tickers) if top_n_tickers else _empty_dict(),
            rf_fetcher.get_daily_rates("USD", common),
        )
    else:
        info_result = await (yf.get_info_batch(top_n_tickers) if top_n_tickers else _empty_dict())

    # --- Compute analytics ---
    analytics_dict = None
    if port_prices is not None:
        rf_daily = np.float64(0.0)
        if rf_coro_result is not None:
            rf_daily = rf_coro_result[1:]  # align to returns (n-1)

        def _compute_analytics(prices, rf_daily_rates):
            from stats.core import compute_full_stats, total_return
            stats = compute_full_stats(prices, rf_daily_rates)
            total_ret = total_return(prices) or 0.0
            return {
                "total_return": round(total_ret, 2),
                "annualized_vol": round(stats.returns.annualized_volatility, 2),
                "sharpe": round(stats.risk_adjusted.sharpe, 4),
                "sortino": round(stats.risk_adjusted.sortino, 4),
                "max_drawdown": round(stats.drawdown.max_drawdown_pct, 2),
                "var_95": round(stats.var.var_95, 2),
                "cvar_95": round(stats.var.cvar_95, 2),
            }

        analytics_dict = await asyncio.to_thread(_compute_analytics, port_prices, rf_daily)

    analytics = PortfolioAnalytics(
        portfolio_id=portfolio_id, period=period,
        **(analytics_dict or {}),
    )

    # --- Compute cumulative returns (BOTH prorated and non-prorated) ---
    def _compute_returns_variant(do_prorate: bool) -> list[dict]:
        from stats.core import simple_pct_change

        date_map: dict[str, dict[str, float]] = {}
        for t in tickers:
            hist = history_map.get(t, [])
            for h in hist:
                d = h["date"][:10]
                if d not in date_map:
                    date_map[d] = {}
                date_map[d][t] = h["close"]

        if not date_map:
            return []

        all_dates = sorted(date_map.keys())
        if len(all_dates) < 2:
            return []

        first_prices: dict[str, float] = {}
        for t in tickers:
            for d in all_dates:
                price = date_map.get(d, {}).get(t)
                if price is not None and price > 0:
                    first_prices[t] = price
                    break

        target_total = sum(w for t, w in weights.items() if t in first_prices)

        points = []
        for d in all_dates:
            port_return = 0.0
            active_weight = 0.0

            for t, w in weights.items():
                if t not in first_prices:
                    continue
                price = date_map.get(d, {}).get(t)
                if price is None:
                    continue
                ret = simple_pct_change(price, first_prices[t]) or 0.0
                port_return += w * ret
                active_weight += w

            if do_prorate and active_weight > 0 and active_weight < target_total:
                port_return = port_return * (target_total / active_weight)

            points.append({"date": d, "portfolio": round(port_return, 2)})
        return points

    def _compute_both_returns():
        return _compute_returns_variant(False), _compute_returns_variant(True)

    non_prorated_points, prorated_points = await asyncio.to_thread(_compute_both_returns)

    # Select the variant the user requested
    return_points = prorated_points if prorated else non_prorated_points

    # --- Build holdings info ---
    def _build_holdings():
        from stats.core import simple_pct_change, simple_returns, annualized_volatility

        holding_infos = []
        for t in tickers_by_weight:
            raw_weight = all_tickers_raw.get(t, 0)
            hist = history_map.get(t, [])
            info = info_result.get(t, {})

            p_return = None
            p_vol = None
            if hist and len(hist) >= 2:
                first_close = hist[0]["close"]
                last_close = hist[-1]["close"]
                result = simple_pct_change(last_close, first_close)
                if result is not None:
                    p_return = round(result, 2)
                try:
                    closes = np.array([h["close"] for h in hist])
                    rets = simple_returns(closes)
                    p_vol = round(annualized_volatility(rets), 2)
                except Exception:
                    pass

            holding_infos.append(HoldingInfo(
                ticker=t, weight=raw_weight,
                sector=info.get("sector", ""),
                industry=info.get("industry", ""),
                pe_ratio=info.get("pe_ratio"),
                forward_pe=info.get("forward_pe"),
                dividend_yield=info.get("dividend_yield"),
                beta=info.get("beta"),
                market_cap=info.get("market_cap"),
                current_price=info.get("current_price"),
                period_return=p_return,
                period_vol=p_vol,
            ))

        # Append non-priceable holdings (bonds) at the end
        for h in all_holdings:
            if not _is_priceable_ticker(h.ticker):
                holding_infos.append(HoldingInfo(ticker=h.ticker, weight=h.weight))

        return holding_infos

    holding_infos = await asyncio.to_thread(_build_holdings)

    # Compute aggregate fundamentals
    _pe_fields = {"pe_ratio", "forward_pe"}

    def _vals(field: str) -> list[float]:
        is_pe = field in _pe_fields
        return [
            v for h in holding_infos
            if (v := getattr(h, field)) is not None
            and (not is_pe or _is_valid_pe_for_agg(v))
        ]

    def _weighted_avg(field: str) -> float | None:
        is_pe = field in _pe_fields
        total_w = 0.0
        total_v = 0.0
        for h in holding_infos:
            val = getattr(h, field)
            if val is not None:
                if is_pe and not _is_valid_pe_for_agg(val):
                    continue
                w = h.weight / 100
                total_w += w
                total_v += w * val
        if total_w == 0:
            return None
        return round(total_v / total_w, 4)

    def _simple_avg(field: str) -> float | None:
        v = _vals(field)
        return round(sum(v) / len(v), 4) if v else None

    def _max_val(field: str) -> float | None:
        v = _vals(field)
        return round(max(v), 4) if v else None

    def _min_val(field: str) -> float | None:
        v = _vals(field)
        return round(min(v), 4) if v else None

    summary = PortfolioSummary(
        portfolio_id=portfolio_id,
        period=period,
        analytics=analytics,
        returns=[PortfolioReturnPoint(**p) for p in return_points],
        holdings=holding_infos,
        weighted_pe=_weighted_avg("pe_ratio"),
        weighted_forward_pe=_weighted_avg("forward_pe"),
        weighted_dividend_yield=_weighted_avg("dividend_yield"),
        weighted_beta=_weighted_avg("beta"),
        avg_pe=_simple_avg("pe_ratio"),
        avg_forward_pe=_simple_avg("forward_pe"),
        avg_dividend_yield=_simple_avg("dividend_yield"),
        avg_beta=_simple_avg("beta"),
        max_pe=_max_val("pe_ratio"),
        max_forward_pe=_max_val("forward_pe"),
        max_dividend_yield=_max_val("dividend_yield"),
        max_beta=_max_val("beta"),
        min_pe=_min_val("pe_ratio"),
        min_forward_pe=_min_val("forward_pe"),
        min_dividend_yield=_min_val("dividend_yield"),
        min_beta=_min_val("beta"),
        holdings_count=holdings_count,
        priceable_count=priceable_count,
    )
    return summary, prorated_points, non_prorated_points


@router.get("/portfolios/{portfolio_id}/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(
    portfolio_id: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    prorated: bool = Query(default=False),
    rescale_weights: float | None = Query(default=100, description="Rescale priceable weights to sum to this %. Null = use raw weights."),
    info_top_n: int = Query(default=50, ge=0, description="Fetch info for top N holdings by weight. 0 = skip info enrichment."),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Consolidated portfolio analysis: analytics + cumulative returns + holdings info."""
    summary, _, _ = await _compute_full_summary(
        portfolio_id, period, start, end, prorated,
        rescale_weights, info_top_n, session, yf,
    )
    return summary


@router.get("/portfolios/{portfolio_id}/summary/stream")
async def stream_portfolio_summary(
    portfolio_id: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    prorated: bool = Query(default=False),
    rescale_weights: float | None = Query(default=100),
    info_top_n: int = Query(default=50, ge=0),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """SSE stream: emit cached data immediately, then fresh data after recomputation."""
    import json
    from fastapi.responses import StreamingResponse
    from dashboard.deps import get_db
    from dashboard.services.portfolio_cache import PortfolioCacheService

    cache_svc = PortfolioCacheService(get_db())

    async def event_generator():
        # Phase 1: try to serve from cache
        cached = await cache_svc.get_cached_summary(
            portfolio_id, period, prorated, start, end,
        )
        if cached:
            yield f"event: cached\ndata: {json.dumps(cached, default=str)}\n\n"
        else:
            yield f"event: loading\ndata: {{}}\n\n"

        # Phase 2: full recomputation
        try:
            summary, prorated_returns, non_prorated_returns = await _compute_full_summary(
                portfolio_id, period, start, end, prorated,
                rescale_weights, info_top_n, session, yf,
            )

            # Phase 3: save to cache
            summary_dict = summary.model_dump()
            try:
                await cache_svc.save_summary(
                    portfolio_id, summary_dict,
                    prorated_returns, non_prorated_returns,
                )
            except Exception:
                logger.warning("Failed to save portfolio cache for %s", portfolio_id, exc_info=True)

            # Phase 4: push fresh data
            yield f"event: fresh\ndata: {summary.model_dump_json()}\n\n"

        except Exception:
            logger.error("Failed to compute portfolio summary for %s", portfolio_id, exc_info=True)
            yield f"event: error\ndata: {{\"error\": \"Failed to compute summary\"}}\n\n"

        # Phase 5: signal completion
        yield f"event: done\ndata: {{}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def _empty_dict() -> dict:
    """Awaitable that returns an empty dict."""
    return {}


@router.get("/portfolios/{portfolio_id}/holdings-info-page", response_model=HoldingsInfoPageResponse)
async def get_holdings_info_page(
    portfolio_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Paginated holdings info for progressive enrichment.

    Returns HoldingInfo for tickers at positions [offset, offset+limit) sorted
    by weight descending. Price histories are likely cached from the /summary call.
    Info is fetched with throttling.
    """
    all_holdings = await _fetch_holdings(portfolio_id, session)
    if not all_holdings:
        return HoldingsInfoPageResponse(
            portfolio_id=portfolio_id, holdings=[],
            offset=offset, limit=limit, total=0,
        )

    # Sort priceable holdings by weight descending
    priceable = [h for h in all_holdings if _is_priceable_ticker(h.ticker)]
    priceable.sort(key=lambda h: h.weight, reverse=True)
    total = len(priceable)

    page = priceable[offset : offset + limit]
    if not page:
        return HoldingsInfoPageResponse(
            portfolio_id=portfolio_id, holdings=[],
            offset=offset, limit=limit, total=total,
        )

    page_tickers = [h.ticker for h in page]
    page_weights = {h.ticker: h.weight for h in page}

    # Fetch info and histories in parallel (histories likely cached from /summary)
    info_result, history_map = await asyncio.gather(
        yf.get_info_batch(page_tickers),
        yf.get_histories_batch(page_tickers, period=period, start=start, end=end),
    )

    from stats.core import simple_pct_change, simple_returns, annualized_volatility

    holding_infos = []
    for h in page:
        t = h.ticker
        info = info_result.get(t, {})
        hist = history_map.get(t, [])

        p_return = None
        p_vol = None
        if hist and len(hist) >= 2:
            first_close = hist[0]["close"]
            last_close = hist[-1]["close"]
            result = simple_pct_change(last_close, first_close)
            if result is not None:
                p_return = round(result, 2)
            try:
                closes = np.array([hh["close"] for hh in hist])
                rets = simple_returns(closes)
                p_vol = round(annualized_volatility(rets), 2)
            except Exception:
                pass

        holding_infos.append(HoldingInfo(
            ticker=t, weight=h.weight,
            sector=info.get("sector", ""),
            industry=info.get("industry", ""),
            pe_ratio=info.get("pe_ratio"),
            forward_pe=info.get("forward_pe"),
            dividend_yield=info.get("dividend_yield"),
            beta=info.get("beta"),
            market_cap=info.get("market_cap"),
            current_price=info.get("current_price"),
            period_return=p_return,
            period_vol=p_vol,
        ))

    return HoldingsInfoPageResponse(
        portfolio_id=portfolio_id,
        holdings=holding_infos,
        offset=offset,
        limit=limit,
        total=total,
    )


# ---------------------------------------------------------------------------
# Intraday endpoints (Alpaca live bars)
# ---------------------------------------------------------------------------

_VALID_INTERVALS = {"1Min", "5Min", "15Min", "30Min", "1Hour"}


@router.get("/portfolios/{portfolio_id}/intraday/returns", response_model=IntradayReturnsResponse)
async def get_intraday_returns(
    portfolio_id: str,
    interval: str = Query(default="5Min", description="Bar interval: 1Min, 5Min, 15Min, 30Min, 1Hour"),
    rescale_weights: float | None = Query(default=100),
    session=Depends(get_db_session),
    data_provider=Depends(get_data_provider_dep),
):
    """Intraday cumulative return series from Alpaca bars (today's session)."""
    if interval not in _VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval. Must be one of: {', '.join(sorted(_VALID_INTERVALS))}")

    empty = IntradayReturnsResponse(portfolio_id=portfolio_id, interval=interval, returns=[])

    holdings = await _fetch_holdings(portfolio_id, session)
    if not holdings:
        return empty

    weights = _priceable_weights(holdings, rescale=rescale_weights)
    tickers = list(weights.keys())
    if not tickers:
        return empty

    bars_by_ticker = await data_provider.get_intraday_bars(tickers, timeframe=interval)

    def _compute():
        # Build timestamp → {ticker: close} map
        ts_map: dict[str, dict[str, float]] = {}
        for t, bars in bars_by_ticker.items():
            for bar in bars:
                ts = bar["timestamp"]
                if ts not in ts_map:
                    ts_map[ts] = {}
                ts_map[ts][t] = bar["close"]

        if not ts_map:
            return []

        all_ts = sorted(ts_map.keys())

        # First price for each ticker
        first_prices: dict[str, float] = {}
        for t in tickers:
            for ts in all_ts:
                price = ts_map.get(ts, {}).get(t)
                if price is not None and price > 0:
                    first_prices[t] = price
                    break

        from stats.core import simple_pct_change

        points = []
        for ts in all_ts:
            port_return = 0.0
            total_weight = 0.0

            for t, w in weights.items():
                if t not in first_prices:
                    continue
                price = ts_map.get(ts, {}).get(t)
                if price is None:
                    continue
                ret = simple_pct_change(price, first_prices[t]) or 0.0
                port_return += w * ret
                total_weight += w

            if total_weight > 0:
                port_return = port_return / total_weight

            points.append({"timestamp": ts, "portfolio": round(port_return, 4)})

        return points

    result = await asyncio.to_thread(_compute)
    return IntradayReturnsResponse(
        portfolio_id=portfolio_id,
        interval=interval,
        returns=[IntradayReturnPoint(**p) for p in result],
    )


@router.get("/portfolios/{portfolio_id}/intraday/analytics", response_model=IntradayAnalytics)
async def get_intraday_analytics(
    portfolio_id: str,
    interval: str = Query(default="5Min"),
    rescale_weights: float | None = Query(default=100),
    session=Depends(get_db_session),
    data_provider=Depends(get_data_provider_dep),
):
    """Intraday analytics: daily return and daily vol (non-annualised)."""
    if interval not in _VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval. Must be one of: {', '.join(sorted(_VALID_INTERVALS))}")

    empty = IntradayAnalytics(portfolio_id=portfolio_id, interval=interval)

    holdings = await _fetch_holdings(portfolio_id, session)
    if not holdings:
        return empty

    weights = _priceable_weights(holdings, rescale=rescale_weights)
    tickers = list(weights.keys())
    if not tickers:
        return empty

    bars_by_ticker = await data_provider.get_intraday_bars(tickers, timeframe=interval)

    def _compute():
        # Build aligned portfolio bar returns
        ts_map: dict[str, dict[str, float]] = {}
        for t, bars in bars_by_ticker.items():
            for bar in bars:
                ts = bar["timestamp"]
                if ts not in ts_map:
                    ts_map[ts] = {}
                ts_map[ts][t] = bar["close"]

        if not ts_map:
            return None

        all_ts = sorted(ts_map.keys())
        if len(all_ts) < 2:
            return None

        # First and last portfolio value for daily return
        first_prices: dict[str, float] = {}
        for t in tickers:
            for ts in all_ts:
                price = ts_map.get(ts, {}).get(t)
                if price is not None and price > 0:
                    first_prices[t] = price
                    break

        # Daily return: weighted return from first bar to last bar
        from stats.core import simple_pct_change
        last_ts = all_ts[-1]
        daily_return = 0.0
        total_w = 0.0
        for t, w in weights.items():
            if t not in first_prices:
                continue
            last_price = ts_map.get(last_ts, {}).get(t)
            if last_price is None:
                continue
            ret = simple_pct_change(last_price, first_prices[t]) or 0.0
            daily_return += w * ret
            total_w += w
        if total_w > 0:
            daily_return /= total_w

        # Daily vol: std dev of bar-to-bar portfolio returns
        bar_returns = []
        for i in range(1, len(all_ts)):
            prev_ts, curr_ts = all_ts[i - 1], all_ts[i]
            port_ret = 0.0
            tw = 0.0
            for t, w in weights.items():
                p_prev = ts_map.get(prev_ts, {}).get(t)
                p_curr = ts_map.get(curr_ts, {}).get(t)
                if p_prev and p_curr and p_prev > 0:
                    port_ret += w * ((p_curr / p_prev) - 1)
                    tw += w
            if tw > 0:
                bar_returns.append(port_ret / tw * 100)

        daily_vol = 0.0
        if len(bar_returns) >= 2:
            mean = sum(bar_returns) / len(bar_returns)
            variance = sum((r - mean) ** 2 for r in bar_returns) / (len(bar_returns) - 1)
            daily_vol = variance ** 0.5

        return {"daily_return": round(daily_return, 4), "daily_vol": round(daily_vol, 4)}

    result = await asyncio.to_thread(_compute)
    if result is None:
        return empty

    return IntradayAnalytics(portfolio_id=portfolio_id, interval=interval, **result)
