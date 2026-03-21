"""
Risk metrics API — VaR, CVaR (historical + parametric), risk-free rates.

Historical VaR/CVaR from empirical return distribution.
Parametric VaR/CVaR via copulax Student-t distribution fit.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep

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


# Risk-free rate mapping: currency → yfinance ticker or G10 rate
_RISK_FREE_MAP = {
    "USD": ("^IRX", "3M T-Bill"),  # 3-month T-bill yield
    "GBP": (None, "SONIA"),        # Use G10 rate
    "EUR": (None, "ESTR"),
    "JPY": (None, "TONAR"),
    "CAD": (None, "BoC Rate"),
    "AUD": (None, "RBA Rate"),
    "CHF": (None, "SNB Rate"),
}

_G10_RATES = {
    "GBP": 4.50, "EUR": 2.65, "JPY": 0.50,
    "CAD": 2.75, "AUD": 4.10, "CHF": 0.25,
    "SEK": 2.25, "NOK": 4.50, "NZD": 3.75,
}


@router.get("/risk/rate", response_model=RiskFreeRateResponse)
async def get_risk_free_rate(
    currency: str = Query(default="USD"),
    yf=Depends(get_yfinance_dep),
):
    """Get the risk-free rate for a given currency."""
    currency = currency.upper()

    if currency == "USD":
        # Fetch 3M T-bill from yield curve data (already cached)
        try:
            curve = await yf.get_yield_curve("US")
            rate = curve.get("curve", {}).get("3M", 4.5)
            return RiskFreeRateResponse(currency="USD", rate=rate, source="3M T-Bill (^IRX)")
        except Exception:
            return RiskFreeRateResponse(currency="USD", rate=4.5, source="Default")

    if currency in _G10_RATES:
        return RiskFreeRateResponse(
            currency=currency,
            rate=_G10_RATES[currency],
            source=f"G10 policy rate ({_RISK_FREE_MAP.get(currency, (None, 'Unknown'))[1]})",
        )

    return RiskFreeRateResponse(currency=currency, rate=4.5, source="Default (USD proxy)")


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

    if not history or len(history) < 10:
        return RiskMetricsResponse(
            ticker=ticker, period=period, trading_days=0,
            annualized_return=0, annualized_vol=0,
            historical=VaRResult(var_95=0, var_99=0, cvar_95=0, cvar_99=0),
            risk_free_rate=0, sharpe=0, sortino=0,
        )

    # Get risk-free rate
    info = await yf.get_info(ticker)
    currency = info.get("currency", "USD")
    rf_resp = await get_risk_free_rate(currency, yf)
    rf_daily = rf_resp.rate / 100 / 252  # Annualized % → daily decimal

    def _compute():
        import numpy as np

        closes = [h["close"] for h in history if h["close"] > 0]
        if len(closes) < 10:
            return None

        # Daily simple returns
        simple_returns = np.array([
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
        ])

        # Daily log returns
        log_returns = np.log(1 + simple_returns)

        n = len(log_returns)
        ann_ret = np.mean(simple_returns) * 252 * 100
        ann_vol = np.std(simple_returns, ddof=1) * np.sqrt(252) * 100

        # Sharpe/Sortino use simple (arithmetic) excess returns
        excess = simple_returns - rf_daily
        mean_excess = np.mean(excess)
        std_excess = np.std(excess, ddof=1)
        sharpe = (mean_excess / std_excess * np.sqrt(252)) \
            if std_excess > 0 else 0

        # Sortino: downside deviation of simple excess returns
        downside = excess[excess < 0]
        downside_std = np.sqrt(np.mean(downside ** 2)) \
            if len(downside) > 0 else std_excess
        sortino = (mean_excess / downside_std * np.sqrt(252)) \
            if downside_std > 0 else 0

        # Historical VaR/CVaR
        var_95 = float(np.percentile(simple_returns, 5)) * 100
        var_99 = float(np.percentile(simple_returns, 1)) * 100
        cvar_95 = float(np.mean(
            simple_returns[simple_returns <= np.percentile(simple_returns, 5)]
        )) * 100
        cvar_99 = float(np.mean(
            simple_returns[simple_returns <= np.percentile(simple_returns, 1)]
        )) * 100

        hist_var = VaRResult(
            var_95=round(var_95, 4), var_99=round(var_99, 4),
            cvar_95=round(cvar_95, 4), cvar_99=round(cvar_99, 4),
        )

        # Parametric via copulax Student-t fit on log returns
        param_var = None
        p_ann_ret = None
        p_ann_vol = None
        p_sharpe = None
        p_sortino = None
        try:
            from copulax.univariate import student_t

            fitted = student_t.fit(log_returns)

            # Sample once, project back to simple return space
            log_samples = np.array(fitted.rvs(10_000))
            simple_samples = np.exp(log_samples) - 1

            # Parametric return/vol/Sharpe/Sortino in simple return space
            p_ann_ret = float(np.mean(simple_samples)) * 252 * 100
            p_ann_vol = float(np.std(simple_samples, ddof=1)) \
                * np.sqrt(252) * 100

            excess_samples = simple_samples - rf_daily
            mean_ex = np.mean(excess_samples)
            std_ex = np.std(excess_samples, ddof=1)
            p_sharpe = (mean_ex / std_ex * np.sqrt(252)) \
                if std_ex > 0 else 0

            ds = excess_samples[excess_samples < 0]
            ds_std = np.sqrt(np.mean(ds ** 2)) \
                if len(ds) > 0 else std_ex
            p_sortino = (mean_ex / ds_std * np.sqrt(252)) \
                if ds_std > 0 else 0

            # Parametric VaR/CVaR
            log_var_95 = float(fitted.ppf(0.05))
            log_var_99 = float(fitted.ppf(0.01))
            p_var_95 = (np.exp(log_var_95) - 1) * 100
            p_var_99 = (np.exp(log_var_99) - 1) * 100

            sv95 = np.exp(log_var_95) - 1
            sv99 = np.exp(log_var_99) - 1
            m95 = simple_samples <= sv95
            m99 = simple_samples <= sv99
            p_cvar_95 = float(simple_samples[m95].mean()) * 100 \
                if m95.any() else p_var_95
            p_cvar_99 = float(simple_samples[m99].mean()) * 100 \
                if m99.any() else p_var_99

            param_var = VaRResult(
                var_95=round(p_var_95, 4),
                var_99=round(p_var_99, 4),
                cvar_95=round(p_cvar_95, 4),
                cvar_99=round(p_cvar_99, 4),
            )
        except Exception:
            logger.exception(
                "copulax Student-t fitting failed for %s", ticker,
            )

        return {
            "ann_ret": round(ann_ret, 2),
            "ann_vol": round(ann_vol, 2),
            "hist_var": hist_var,
            "param_var": param_var,
            "sharpe": round(float(sharpe), 4),
            "sortino": round(float(sortino), 4),
            "p_ann_ret": round(float(p_ann_ret), 2)
            if p_ann_ret is not None else None,
            "p_ann_vol": round(float(p_ann_vol), 2)
            if p_ann_vol is not None else None,
            "p_sharpe": round(float(p_sharpe), 4)
            if p_sharpe is not None else None,
            "p_sortino": round(float(p_sortino), 4)
            if p_sortino is not None else None,
            "n": n,
        }

    result = await asyncio.to_thread(_compute)
    if result is None:
        return RiskMetricsResponse(
            ticker=ticker, period=period, trading_days=0,
            annualized_return=0, annualized_vol=0,
            historical=VaRResult(var_95=0, var_99=0, cvar_95=0, cvar_99=0),
            risk_free_rate=rf_resp.rate, sharpe=0, sortino=0,
        )

    return RiskMetricsResponse(
        ticker=ticker,
        period=start and end and f"{start} to {end}" or period,
        trading_days=result["n"],
        annualized_return=result["ann_ret"],
        annualized_vol=result["ann_vol"],
        historical=result["hist_var"],
        parametric=result["param_var"],
        risk_free_rate=rf_resp.rate,
        sharpe=result["sharpe"],
        sortino=result["sortino"],
        parametric_return=result["p_ann_ret"],
        parametric_vol=result["p_ann_vol"],
        parametric_sharpe=result["p_sharpe"],
        parametric_sortino=result["p_sortino"],
    )
