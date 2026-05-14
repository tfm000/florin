"""GET /api/stats — Trading statistics and performance metrics."""

from __future__ import annotations

import asyncio

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from dashboard.dependencies import get_yfinance_dep
from dashboard.deps import get_db, get_rf_fetcher
from db.models import TradeORM

router = APIRouter(tags=["stats"])


class ReturnsStatsResponse(BaseModel):
    ticker: str
    period: str
    trading_days: int
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    max_drawdown: float
    mean_daily_pct: float
    std_dev_daily_pct: float
    skewness: float
    excess_kurtosis: float
    var_95_pct: float
    cvar_95_pct: float


@router.get("/stats/returns/{ticker}", response_model=ReturnsStatsResponse)
async def get_returns_stats(
    ticker: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    yf=Depends(get_yfinance_dep),
):
    """Compute return and distribution statistics for an asset.

    Replaces client-side JS computation in QuantitativeTab and
    ReturnsHistogram with canonical server-side stats.
    """
    ticker = ticker.upper()

    if start and end:
        history = await yf.get_history(ticker, start=start, end=end)
    else:
        history = await yf.get_history(ticker, period=period)

    if not history or len(history) < 2:
        return ReturnsStatsResponse(
            ticker=ticker,
            period=period,
            trading_days=0,
            total_return=0,
            annualized_return=0,
            annualized_volatility=0,
            sharpe=0,
            max_drawdown=0,
            mean_daily_pct=0,
            std_dev_daily_pct=0,
            skewness=0,
            excess_kurtosis=0,
            var_95_pct=0,
            cvar_95_pct=0,
        )

    # Get risk-free rate
    info = await yf.get_info(ticker)
    currency = info.get("currency", "USD")
    rf_fetcher = get_rf_fetcher()

    dates = [h["date"] for h in history if h["close"] > 0]
    rf_daily = np.float64(0.0)
    if rf_fetcher and dates:
        rf_full = await rf_fetcher.get_daily_rates(currency, dates)
        rf_daily = rf_full[1:]  # align to returns (n-1)

    def _compute():
        from stats.core import compute_full_stats

        closes = np.array([h["close"] for h in history if h["close"] > 0])
        if len(closes) < 2:
            return None

        stats = compute_full_stats(closes, rf_daily)
        total_ret = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0.0

        return ReturnsStatsResponse(
            ticker=ticker,
            period=f"{start} to {end}" if start and end else period,
            trading_days=stats.returns.trading_days,
            total_return=round(total_ret, 2),
            annualized_return=round(stats.returns.annualized_return, 2),
            annualized_volatility=round(
                stats.returns.annualized_volatility,
                2,
            ),
            sharpe=round(stats.risk_adjusted.sharpe, 2),
            max_drawdown=round(stats.drawdown.max_drawdown_pct, 2),
            mean_daily_pct=round(stats.distribution.mean, 3),
            std_dev_daily_pct=round(stats.distribution.std_dev, 3),
            skewness=round(stats.distribution.skewness, 3),
            excess_kurtosis=round(stats.distribution.excess_kurtosis, 3),
            var_95_pct=round(stats.var.var_95, 3),
            cvar_95_pct=round(stats.var.cvar_95, 3),
        )

    result = await asyncio.to_thread(_compute)
    if result is None:
        return ReturnsStatsResponse(
            ticker=ticker,
            period=period,
            trading_days=0,
            total_return=0,
            annualized_return=0,
            annualized_volatility=0,
            sharpe=0,
            max_drawdown=0,
            mean_daily_pct=0,
            std_dev_daily_pct=0,
            skewness=0,
            excess_kurtosis=0,
            var_95_pct=0,
            cvar_95_pct=0,
        )
    return result


@router.get("/stats")
async def get_stats():
    """Get aggregated trading statistics."""
    db = get_db()
    async with db.session() as session:
        # Total trades
        total_result = await session.execute(select(func.count(TradeORM.id)))
        total_trades = total_result.scalar() or 0

        if total_trades == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl_per_trade": 0.0,
                "best_trade_pnl": 0.0,
                "worst_trade_pnl": 0.0,
            }

        # Closing trades with P&L
        closing_query = select(TradeORM).where(
            TradeORM.is_closing_trade.is_(True),
            TradeORM.realised_pnl.isnot(None),
        )
        result = await session.execute(closing_query)
        closing_trades = result.scalars().all()

        winning = [t for t in closing_trades if t.realised_pnl and t.realised_pnl > 0]
        losing = [t for t in closing_trades if t.realised_pnl and t.realised_pnl < 0]
        total_pnl = sum(t.realised_pnl for t in closing_trades if t.realised_pnl)

        win_count = len(winning)
        lose_count = len(losing)
        round_trips = win_count + lose_count
        win_rate = (win_count / round_trips * 100) if round_trips > 0 else 0.0

        pnl_values = [t.realised_pnl for t in closing_trades if t.realised_pnl is not None]

    return {
        "total_trades": total_trades,
        "round_trip_trades": round_trips,
        "winning_trades": win_count,
        "losing_trades": lose_count,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / round_trips, 2) if round_trips > 0 else 0.0,
        "best_trade_pnl": round(max(pnl_values), 2) if pnl_values else 0.0,
        "worst_trade_pnl": round(min(pnl_values), 2) if pnl_values else 0.0,
    }
