"""
Risk metrics API — VaR, CVaR (historical + parametric), risk-free rates.

Delegates all computation to the ``stats`` module.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep
from dashboard.deps import get_rf_fetcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["risk"])


class RiskFreeRateResponse(BaseModel):
    currency: str
    rate: float
    source: str


class VaRResult(BaseModel):
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float


class RiskMetricsResponse(BaseModel):
    ticker: str
    period: str
    trading_days: int
    annualized_return: float
    annualized_vol: float
    historical: VaRResult
    parametric: VaRResult | None = None
    risk_free_rate: float
    sharpe: float
    sortino: float
    parametric_return: float | None = None
    parametric_vol: float | None = None
    parametric_sharpe: float | None = None
    parametric_sortino: float | None = None


@router.get("/risk/rate", response_model=RiskFreeRateResponse)
async def get_risk_free_rate(
    currency: str = Query(default="USD"),
):
    """Get the current risk-free rate for a currency."""
    rf_fetcher = get_rf_fetcher()
    if rf_fetcher is None:
        return RiskFreeRateResponse(
            currency=currency.upper(), rate=0.0, source="unavailable",
        )

    rate, source = await rf_fetcher.get_current_rate(currency)
    return RiskFreeRateResponse(
        currency=currency.upper(), rate=rate, source=source,
    )


@router.get("/risk/{ticker}", response_model=RiskMetricsResponse)
async def get_risk_metrics(
    ticker: str,
    period: str = Query(default="1y"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    yf=Depends(get_yfinance_dep),
):
    """Compute VaR, CVaR, Sharpe, Sortino for an asset."""
    ticker = ticker.upper()

    # Fetch history
    if start and end:
        history = await yf.get_history(ticker, start=start, end=end)
    else:
        history = await yf.get_history(ticker, period=period)

    empty = RiskMetricsResponse(
        ticker=ticker, period=period, trading_days=0,
        annualized_return=0, annualized_vol=0,
        historical=VaRResult(var_95=0, var_99=0, cvar_95=0, cvar_99=0),
        risk_free_rate=0, sharpe=0, sortino=0,
    )

    if not history or len(history) < 10:
        return empty

    # Get risk-free rate time series
    info = await yf.get_info(ticker)
    currency = info.get("currency", "USD")

    rf_fetcher = get_rf_fetcher()
    dates = [h["date"] for h in history if h["close"] > 0]
    if rf_fetcher and dates:
        rf_daily = await rf_fetcher.get_daily_rates(currency, dates)
        # rf_daily has len(dates), but returns have len(dates)-1
        rf_daily_for_returns = rf_daily[1:]
    else:
        rf_daily_for_returns = np.float64(0.0)

    # Get current rate for the response field
    rf_rate = 0.0
    if rf_fetcher:
        rf_rate, _ = await rf_fetcher.get_current_rate(currency)

    def _compute():
        from stats.core import (
            simple_returns, log_returns,
            compute_return_stats, compute_risk_adjusted, var_cvar,
        )
        from stats.parametric import fit_student_t

        closes = np.array([h["close"] for h in history if h["close"] > 0])
        if len(closes) < 10:
            return None

        rets = simple_returns(closes)
        log_rets = log_returns(closes)

        ret_stats = compute_return_stats(rets)
        risk_adj = compute_risk_adjusted(rets, rf_daily_for_returns)
        var_stats = var_cvar(rets)

        hist_var = VaRResult(
            var_95=round(var_stats.var_95, 4),
            var_99=round(var_stats.var_99, 4),
            cvar_95=round(var_stats.cvar_95, 4),
            cvar_99=round(var_stats.cvar_99, 4),
        )

        # Parametric Student-t
        param = fit_student_t(log_rets, rf_daily_for_returns)
        param_var = None
        p_ann_ret = None
        p_ann_vol = None
        p_sharpe = None
        p_sortino = None
        if param is not None:
            param_var = VaRResult(
                var_95=param.var.var_95,
                var_99=param.var.var_99,
                cvar_95=param.var.cvar_95,
                cvar_99=param.var.cvar_99,
            )
            p_ann_ret = param.annualized_return
            p_ann_vol = param.annualized_volatility
            p_sharpe = param.sharpe
            p_sortino = param.sortino

        return {
            "ann_ret": round(ret_stats.annualized_return, 2),
            "ann_vol": round(ret_stats.annualized_volatility, 2),
            "hist_var": hist_var,
            "param_var": param_var,
            "sharpe": round(risk_adj.sharpe, 4),
            "sortino": round(risk_adj.sortino, 4),
            "p_ann_ret": p_ann_ret,
            "p_ann_vol": p_ann_vol,
            "p_sharpe": p_sharpe,
            "p_sortino": p_sortino,
            "n": ret_stats.trading_days,
        }

    result = await asyncio.to_thread(_compute)
    if result is None:
        empty.risk_free_rate = rf_rate
        return empty

    return RiskMetricsResponse(
        ticker=ticker,
        period=f"{start} to {end}" if start and end else period,
        trading_days=result["n"],
        annualized_return=result["ann_ret"],
        annualized_vol=result["ann_vol"],
        historical=result["hist_var"],
        parametric=result["param_var"],
        risk_free_rate=rf_rate,
        sharpe=result["sharpe"],
        sortino=result["sortino"],
        parametric_return=result["p_ann_ret"],
        parametric_vol=result["p_ann_vol"],
        parametric_sharpe=result["p_sharpe"],
        parametric_sortino=result["p_sortino"],
    )
