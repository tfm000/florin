"""
Portfolio management API — create model portfolios, analyse returns and risk.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from core.exceptions import ConflictError, NotFoundError
from dashboard.dependencies import get_db_session, get_yfinance_dep
from db.models import PortfolioHoldingORM, PortfolioORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portfolio"])


class PortfolioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    group: str | None = None


class HoldingUpdate(BaseModel):
    ticker: str = Field(..., min_length=1)
    weight: float = Field(..., ge=0, le=100)


class PortfolioResponse(BaseModel):
    id: str
    name: str
    group: str | None = None
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


@router.get("/portfolios", response_model=list[PortfolioResponse])
async def list_portfolios(session=Depends(get_db_session)):
    result = await session.execute(select(PortfolioORM).order_by(PortfolioORM.created_at.desc()))
    portfolios = result.scalars().all()

    responses = []
    for p in portfolios:
        holdings_result = await session.execute(
            select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == p.id)
        )
        holdings = [{"ticker": h.ticker, "weight": h.weight} for h in holdings_result.scalars().all()]
        responses.append(PortfolioResponse(
            id=p.id, name=p.name, group=p.group,
            holdings=holdings, created_at=str(p.created_at),
        ))
    return responses


@router.post("/portfolios", response_model=PortfolioResponse, status_code=201)
async def create_portfolio(req: PortfolioCreate, session=Depends(get_db_session)):
    existing = await session.execute(select(PortfolioORM).where(PortfolioORM.name == req.name))
    if existing.scalar():
        raise ConflictError(f"Portfolio '{req.name}' already exists")

    portfolio = PortfolioORM(name=req.name, group=req.group)
    session.add(portfolio)
    await session.commit()
    await session.refresh(portfolio)
    return PortfolioResponse(
        id=portfolio.id, name=portfolio.name, group=portfolio.group,
        created_at=str(portfolio.created_at),
    )


@router.delete("/portfolios/{portfolio_id}")
async def delete_portfolio(portfolio_id: str, session=Depends(get_db_session)):
    result = await session.execute(select(PortfolioORM).where(PortfolioORM.id == portfolio_id))
    portfolio = result.scalar()
    if not portfolio:
        raise NotFoundError("Portfolio not found")

    await session.execute(delete(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id))
    await session.delete(portfolio)
    await session.commit()
    return {"status": "ok"}


@router.put("/portfolios/{portfolio_id}/holdings")
async def update_holdings(
    portfolio_id: str,
    holdings: list[HoldingUpdate],
    session=Depends(get_db_session),
):
    result = await session.execute(select(PortfolioORM).where(PortfolioORM.id == portfolio_id))
    if not result.scalar():
        raise NotFoundError("Portfolio not found")

    # Replace all holdings
    await session.execute(delete(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id))
    for h in holdings:
        session.add(PortfolioHoldingORM(
            portfolio_id=portfolio_id, ticker=h.ticker.upper(), weight=h.weight,
        ))
    await session.commit()
    return {"status": "ok", "count": len(holdings)}


@router.get("/portfolios/{portfolio_id}/analytics", response_model=PortfolioAnalytics)
async def get_portfolio_analytics(
    portfolio_id: str,
    period: str = Query(default="1y"),
    session=Depends(get_db_session),
    yf=Depends(get_yfinance_dep),
):
    """Compute portfolio-level analytics from constituent returns."""
    result = await session.execute(
        select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()
    if not holdings:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    # Fetch histories concurrently
    tickers = [h.ticker for h in holdings]
    weights = {h.ticker: h.weight / 100 for h in holdings}

    histories = await asyncio.gather(*[yf.get_history(t, period=period) for t in tickers])

    # Fetch risk-free rate for portfolio's primary currency (USD default)
    from dashboard.deps import get_rf_fetcher
    rf_fetcher = get_rf_fetcher()

    def _compute(rf_daily_rates):
        import numpy as np
        from stats.core import (
            log_returns, annualized_volatility,
            sharpe_ratio, sortino_ratio,
            max_drawdown_from_log_returns, historical_var, historical_cvar,
        )

        # Find common dates
        date_sets = [{h["date"] for h in hist} for hist in histories if hist]
        if not date_sets or not all(date_sets):
            return None
        common = sorted(set.intersection(*date_sets))
        if len(common) < 10:
            return None

        # Build weighted portfolio log returns
        port_returns = np.zeros(len(common) - 1)
        for i, hist in enumerate(histories):
            if not hist:
                continue
            t = tickers[i]
            w = weights.get(t, 0)
            price_map = {h["date"]: h["close"] for h in hist}
            prices = np.array([price_map[d] for d in common])
            rets = log_returns(prices)
            port_returns += w * rets

        # Convert to simple returns for risk-adjusted metrics
        port_simple = np.exp(port_returns) - 1

        ann_vol = annualized_volatility(port_returns)
        sharpe = sharpe_ratio(port_simple, rf_daily_rates)
        sortino = sortino_ratio(port_simple, rf_daily_rates)
        dd = max_drawdown_from_log_returns(port_returns)
        total_ret = (np.exp(np.sum(port_returns)) - 1) * 100

        var_95 = historical_var(port_simple, confidence=0.95)
        cvar_95 = historical_cvar(port_simple, confidence=0.95)

        return {
            "total_return": round(total_ret, 2),
            "annualized_vol": round(ann_vol, 2),
            "sharpe": round(float(sharpe), 4),
            "sortino": round(float(sortino), 4),
            "max_drawdown": round(-dd.max_drawdown_pct, 2),
            "var_95": round(var_95, 4),
            "cvar_95": round(cvar_95, 4),
        }

    # Get rf daily rates (aligned to common dates minus first)
    rf_daily = np.float64(0.0)
    if rf_fetcher:
        # Use dates from the first ticker's history as proxy for common dates
        all_dates = sorted({h["date"] for h in histories[0]}) if histories[0] else []
        if all_dates:
            rf_full = await rf_fetcher.get_daily_rates("USD", all_dates)
            rf_daily = rf_full[1:]  # align to returns (n-1)

    result = await asyncio.to_thread(_compute, rf_daily)
    if result is None:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    return PortfolioAnalytics(portfolio_id=portfolio_id, period=period, **result)
