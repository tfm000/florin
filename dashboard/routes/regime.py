"""
Regime switching detection via statsmodels Markov regression.

Two modes:
1. Self-regime: detect regimes from the asset's own returns
2. Benchmark-regime: detect regimes from another asset, overlay onto the target
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep
from stats.regime import fit_markov_regimes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["regime"])


class RegimePoint(BaseModel):
    date: str
    regime: int
    probability: float


class RegimeStats(BaseModel):
    regime: int
    mean_return: float
    volatility: float
    count: int  # number of days in this regime


class RegimeResponse(BaseModel):
    ticker: str
    source_ticker: str
    n_regimes: int
    regimes: list[RegimePoint]
    stats: list[RegimeStats]


# Approximate annualized trading periods per interval
_ANNUALIZE_FACTOR = {
    "1m": 252 * 390,  # ~390 one-minute bars per trading day × 252 days
    "5m": 252 * 78,  # ~78 five-minute bars per day
    "15m": 252 * 26,
    "30m": 252 * 13,
    "60m": 252 * 6.5,
    "1h": 252 * 6.5,
    "1d": 252,
}


@router.get("/regime/{ticker}", response_model=RegimeResponse)
async def detect_regimes(
    ticker: str,
    source: str = Query(
        default="", description="Benchmark ticker for regime detection (empty = self)"
    ),
    n_regimes: int = Query(default=2, ge=2, le=3),
    period: str = Query(
        default="1y", description="Display range (model always fits on max history for daily)"
    ),
    interval: str = Query(default="1d", description="Data interval — matches chart frequency"),
    start: str = Query(default="", description="Custom start YYYY-MM-DD"),
    end: str = Query(default="", description="Custom end YYYY-MM-DD"),
    yf=Depends(get_yfinance_dep),
):
    """Detect market regimes using Markov switching regression.

    For daily data the model is fit on FULL available history (max) for accuracy.
    For intraday data the model is fit on whatever the period provides (limited history).
    The source/benchmark ticker is always fetched at the same interval.
    """
    ticker = ticker.upper()
    source_ticker = source.upper() if source else ticker
    is_intraday = interval != "1d"

    # Fetch history — max for daily, requested period for intraday
    from data.yfinance_provider import _period_cutoff

    if is_intraday:
        full_history = await yf.get_history(source_ticker, period=period, interval=interval)
    else:
        full_history = await yf.get_history(source_ticker, period="max")

    if not full_history or len(full_history) < 30:
        return RegimeResponse(
            ticker=ticker,
            source_ticker=source_ticker,
            n_regimes=n_regimes,
            regimes=[],
            stats=[],
        )

    # Compute display cutoff from period — no second fetch (daily only)
    if is_intraday:
        display_start = ""
        display_end = ""
    elif start:
        display_start = start
        display_end = end
    else:
        display_start = _period_cutoff(period) or ""
        display_end = ""

    annualize = _ANNUALIZE_FACTOR.get(interval, 252)

    def _compute():
        closes = [h["close"] for h in full_history if h["close"] > 0]
        dates = [h["date"] for h in full_history if h["close"] > 0]

        if len(closes) < 30:
            return None

        # Simple returns scaled by 100 for numerical stability
        # closes are pre-filtered to > 0, so division is always safe
        simple_rets = (
            np.array([(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]) * 100
        )

        return fit_markov_regimes(
            simple_rets,
            dates[1:],
            n_regimes,
            display_start=display_start,
            display_end=display_end,
            annualize_factor=annualize,
        )

    result = await asyncio.to_thread(_compute)
    if result is None:
        return RegimeResponse(
            ticker=ticker,
            source_ticker=source_ticker,
            n_regimes=n_regimes,
            regimes=[],
            stats=[],
        )

    return RegimeResponse(
        ticker=ticker,
        source_ticker=source_ticker,
        n_regimes=n_regimes,
        regimes=[RegimePoint(**r) for r in result["regimes"]],
        stats=[RegimeStats(**s) for s in result["stats"]],
    )
