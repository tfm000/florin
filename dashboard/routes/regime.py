"""
Regime switching detection via statsmodels Markov regression.

Two modes:
1. Self-regime: detect regimes from the asset's own returns
2. Benchmark-regime: detect regimes from another asset, overlay onto the target
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_yfinance_dep

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

    # Always fit on max history for best regime estimation
    full_history = await yf.get_history(source_ticker, period="max")

    if not full_history or len(full_history) < 30:
        return RegimeResponse(
            ticker=ticker, source_ticker=source_ticker, n_regimes=n_regimes,
            regimes=[], stats=[],
        )

    # Determine the display cutoff dates
    if start:
        display_start = start
        display_end = end
    else:
        display_history = await yf.get_history(source_ticker, period=period)
        display_start = display_history[0]["date"][:10] if display_history else ""
        display_end = ""

    def _compute():
        import numpy as np
        from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

        closes = [h["close"] for h in full_history if h["close"] > 0]
        dates = [h["date"] for h in full_history if h["close"] > 0]

        if len(closes) < 30:
            return None

        # Daily log returns from FULL history
        log_returns = np.array([
            np.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
        ]) * 100  # Scale for numerical stability

        return_dates = dates[1:]

        try:
            model = MarkovRegression(
                log_returns, k_regimes=n_regimes, trend="c", switching_variance=True,
            )
            result = model.fit(maxiter=200, disp=False)

            # Get smoothed regime probabilities
            # Can be a DataFrame or numpy array depending on statsmodels version
            smoothed = result.smoothed_marginal_probabilities
            probs = smoothed.values if hasattr(smoothed, 'values') else np.array(smoothed)
            regime_assignments = probs.argmax(axis=1)
            regime_probs = probs.max(axis=1)

            # Filter to display range only (model was fit on full history)
            regimes = []
            display_indices = []
            for i in range(len(return_dates)):
                date_str = return_dates[i][:10] if len(return_dates[i]) > 10 else return_dates[i]
                if display_start and date_str < display_start:
                    continue
                if display_end and date_str > display_end:
                    continue
                display_indices.append(i)
                regimes.append({
                    "date": date_str,
                    "regime": int(regime_assignments[i]),
                    "probability": round(float(regime_probs[i]), 4),
                })

            # Compute per-regime stats from the FULL history
            # (regime characteristics should reflect all available data, not just the display window)
            stats = []
            for r in range(n_regimes):
                mask = regime_assignments == r
                if mask.sum() == 0:
                    continue
                regime_rets = log_returns[mask] / 100  # Unscale
                stats.append({
                    "regime": r,
                    "mean_return": round(float(np.mean(regime_rets)) * 252 * 100, 2),  # Annualized %
                    "volatility": round(float(np.std(regime_rets)) * np.sqrt(252) * 100, 2),
                    "count": int(mask.sum()),
                })

            # Sort regimes by volatility (low vol = regime 0)
            stats.sort(key=lambda s: s["volatility"])
            regime_map = {s["regime"]: i for i, s in enumerate(stats)}
            for s in stats:
                s["regime"] = regime_map[s["regime"]]
            for r in regimes:
                r["regime"] = regime_map.get(r["regime"], r["regime"])

            return {"regimes": regimes, "stats": stats}

        except Exception:
            logger.exception("Markov regime switching failed for %s", source_ticker)
            return None

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
