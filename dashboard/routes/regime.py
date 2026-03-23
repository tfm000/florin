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


@router.get("/regime/{ticker}", response_model=RegimeResponse)
async def detect_regimes(
    ticker: str,
    source: str = Query(default="", description="Benchmark ticker for regime detection (empty = self)"),
    n_regimes: int = Query(default=2, ge=2, le=3),
    period: str = Query(default="1y", description="Display range (model always fits on max history)"),
    start: str = Query(default="", description="Custom start YYYY-MM-DD"),
    end: str = Query(default="", description="Custom end YYYY-MM-DD"),
    yf=Depends(get_yfinance_dep),
):
    """Detect market regimes using Markov switching regression.

    The model is always fit on the FULL available history (max) for accuracy.
    Only the regimes within the requested display period are returned.
    """
    ticker = ticker.upper()
    source_ticker = source.upper() if source else ticker

    # Single fetch — max history for regime fitting
    from data.yfinance_provider import _period_cutoff
    full_history = await yf.get_history(source_ticker, period="max")

    if not full_history or len(full_history) < 30:
        return RegimeResponse(
            ticker=ticker, source_ticker=source_ticker, n_regimes=n_regimes,
            regimes=[], stats=[],
        )

    # Compute display cutoff from period — no second fetch
    if start:
        display_start = start
        display_end = end
    else:
        display_start = _period_cutoff(period) or ""
        display_end = ""

    def _compute():
        closes = [h["close"] for h in full_history if h["close"] > 0]
        dates = [h["date"] for h in full_history if h["close"] > 0]

        if len(closes) < 30:
            return None

        log_rets = np.array([
            np.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
        ]) * 100  # Scale for numerical stability

        return fit_markov_regimes(
            log_rets, dates[1:], n_regimes,
            display_start=display_start, display_end=display_end,
        )

    result = await asyncio.to_thread(_compute)
    if result is None:
        return RegimeResponse(
            ticker=ticker, source_ticker=source_ticker, n_regimes=n_regimes,
            regimes=[], stats=[],
        )

    return RegimeResponse(
        ticker=ticker,
        source_ticker=source_ticker,
        n_regimes=n_regimes,
        regimes=[RegimePoint(**r) for r in result["regimes"]],
        stats=[RegimeStats(**s) for s in result["stats"]],
    )
