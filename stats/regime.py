"""
Markov regime switching — shared fitting logic.

Used by both the single-asset ``/regime/{ticker}`` endpoint and the
portfolio-level ``/portfolios/{id}/regime`` endpoint.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def fit_markov_regimes(
    log_returns_scaled: np.ndarray,
    dates: list[str],
    n_regimes: int = 2,
    display_start: str = "",
    display_end: str = "",
) -> dict | None:
    """Fit a Markov switching regression and return regime assignments.

    Parameters
    ----------
    log_returns_scaled : np.ndarray
        Daily log returns **already scaled by 100** for numerical stability.
        Length must match ``len(dates)``.
    dates : list[str]
        ISO date strings aligned to ``log_returns_scaled``.
    n_regimes : int
        Number of regimes (2 or 3).
    display_start / display_end : str
        Optional YYYY-MM-DD bounds.  The model is always fit on the full
        series; only the returned ``regimes`` list is filtered to this window.

    Returns
    -------
    dict with keys ``regimes`` (list[dict]) and ``stats`` (list[dict]),
    or ``None`` on failure / insufficient data.
    """
    if len(log_returns_scaled) < 30:
        return None

    try:
        from statsmodels.tsa.regime_switching.markov_regression import (
            MarkovRegression,
        )

        model = MarkovRegression(
            log_returns_scaled,
            k_regimes=n_regimes,
            trend="c",
            switching_variance=True,
        )
        result = model.fit(maxiter=200, disp=False)

        smoothed = result.smoothed_marginal_probabilities
        probs = smoothed.values if hasattr(smoothed, "values") else np.array(smoothed)
        regime_assignments = probs.argmax(axis=1)
        regime_probs = probs.max(axis=1)

        # Filter to display range (model was fit on full history)
        regimes: list[dict] = []
        for i in range(len(dates)):
            date_str = dates[i][:10] if len(dates[i]) > 10 else dates[i]
            if display_start and date_str < display_start:
                continue
            if display_end and date_str > display_end:
                continue
            regimes.append({
                "date": date_str,
                "regime": int(regime_assignments[i]),
                "probability": round(float(regime_probs[i]), 4),
            })

        # Per-regime stats from FULL history
        stats: list[dict] = []
        for r in range(n_regimes):
            mask = regime_assignments == r
            if mask.sum() == 0:
                continue
            regime_rets = log_returns_scaled[mask] / 100  # unscale
            stats.append({
                "regime": r,
                "mean_return": round(float(np.mean(regime_rets)) * 252 * 100, 2),
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
        logger.exception("Markov regime switching failed")
        return None
