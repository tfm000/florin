"""
Portfolio management API — create model portfolios, analyse returns and risk.
"""

from __future__ import annotations

import asyncio
import logging

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


class HoldingUpdate(BaseModel):
    ticker: str = Field(..., min_length=1)
    weight: float = Field(..., ge=0, le=100)


class PortfolioResponse(BaseModel):
    id: str
    name: str
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
            id=p.id, name=p.name, holdings=holdings, created_at=str(p.created_at),
        ))
    return responses


@router.post("/portfolios", response_model=PortfolioResponse, status_code=201)
async def create_portfolio(req: PortfolioCreate, session=Depends(get_db_session)):
    existing = await session.execute(select(PortfolioORM).where(PortfolioORM.name == req.name))
    if existing.scalar():
        raise ConflictError(f"Portfolio '{req.name}' already exists")

    portfolio = PortfolioORM(name=req.name)
    session.add(portfolio)
    await session.commit()
    await session.refresh(portfolio)
    return PortfolioResponse(id=portfolio.id, name=portfolio.name, created_at=str(portfolio.created_at))


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

    def _compute():
        import numpy as np

        # Find common dates
        date_sets = [{h["date"] for h in hist} for hist in histories if hist]
        if not date_sets or not all(date_sets):
            return None
        common = sorted(set.intersection(*date_sets))
        if len(common) < 10:
            return None

        # Build weighted portfolio returns
        port_returns = np.zeros(len(common) - 1)
        for i, hist in enumerate(histories):
            if not hist:
                continue
            ticker = tickers[i]
            w = weights.get(ticker, 0)
            price_map = {h["date"]: h["close"] for h in hist}
            prices = [price_map[d] for d in common]
            rets = np.array([np.log(prices[j] / prices[j - 1]) for j in range(1, len(prices))])
            port_returns += w * rets

        n = len(port_returns)
        mean = np.mean(port_returns)
        std = np.std(port_returns, ddof=1)
        ann_vol = std * np.sqrt(252) * 100

        # Risk-free rate (approximate)
        rf_daily = 0.045 / 252

        sharpe = ((mean - rf_daily) / std * np.sqrt(252)) if std > 0 else 0
        downside = port_returns[port_returns < rf_daily] - rf_daily
        down_std = np.sqrt(np.mean(downside ** 2)) if len(downside) > 0 else std
        sortino = ((mean - rf_daily) / down_std * np.sqrt(252)) if down_std > 0 else 0

        # Max drawdown
        cum = np.cumsum(port_returns)
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        max_dd = float(np.min(dd)) * 100

        # Total return
        total_ret = (np.exp(np.sum(port_returns)) - 1) * 100

        # Historical VaR/CVaR
        var_95 = (np.exp(np.percentile(port_returns, 5)) - 1) * 100
        mask = port_returns <= np.percentile(port_returns, 5)
        cvar_95 = (np.exp(np.mean(port_returns[mask])) - 1) * 100 if mask.any() else var_95

        return {
            "total_return": round(total_ret, 2),
            "annualized_vol": round(ann_vol, 2),
            "sharpe": round(float(sharpe), 4),
            "sortino": round(float(sortino), 4),
            "max_drawdown": round(max_dd, 2),
            "var_95": round(var_95, 4),
            "cvar_95": round(cvar_95, 4),
        }

    result = await asyncio.to_thread(_compute)
    if result is None:
        return PortfolioAnalytics(portfolio_id=portfolio_id, period=period)

    return PortfolioAnalytics(portfolio_id=portfolio_id, period=period, **result)
