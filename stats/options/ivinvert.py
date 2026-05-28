"""
Implied-volatility inversion: Newton-Raphson fast path + Brent fallback.

For each market mid price ``P`` at strike ``K`` solve

    BS76(F, K, T, σ, D) = P

for ``σ ∈ [10⁻⁴, 5.0]``. Newton-Raphson with the analytic vega Jacobian
converges in 4–8 iterations for in-bracket quotes; Brent's method is the
robust fallback when (a) NR steps leave the bracket, (b) vega vanishes
(deep OTM), or (c) the price is at the boundary of the no-arbitrage
band.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from stats.options.pricing import bs76_call, bs76_put, bs_vega

# Fast-path tuning.
_NR_MAX_ITER = 30
_NR_TOL = 1e-8
_BRACKET: tuple[float, float] = (1e-4, 5.0)
_VEGA_FLOOR = 1e-10
_NR_START_SIGMA = 0.30


def implied_vol_one(
    price: float,
    F: float,
    K: float,
    T: float,
    D: float,
    is_call: bool,
    bracket: tuple[float, float] = _BRACKET,
) -> float:
    """Invert one mid price to implied volatility.

    Returns ``NaN`` if the price violates Black-76 bounds, ``T ≤ 0``,
    or if neither NR nor Brent converges within the bracket.
    """
    if not np.isfinite(price) or price <= 0.0 or T <= 0.0:
        return float("nan")

    fn = bs76_call if is_call else bs76_put
    lo, hi = bracket

    # Reject prices outside the no-arbitrage envelope before any solver.
    f_lo = float(fn(F, K, T, lo, D)) - price
    f_hi = float(fn(F, K, T, hi, D)) - price
    if f_lo > 0.0 or f_hi < 0.0:
        return float("nan")

    # Newton-Raphson with vega Jacobian.
    sigma = _NR_START_SIGMA
    for _ in range(_NR_MAX_ITER):
        p = float(fn(F, K, T, sigma, D))
        diff = p - price
        if abs(diff) < _NR_TOL:
            return sigma
        v = float(bs_vega(F, K, T, sigma, D))
        if v <= _VEGA_FLOOR:
            break  # NR will diverge — let Brent finish the job.
        sigma_new = sigma - diff / v
        if sigma_new <= lo or sigma_new >= hi:
            break  # outside bracket — Brent takes over.
        sigma = sigma_new

    # Brent fallback. ``brentq`` requires a true sign change on [lo, hi],
    # which the f_lo / f_hi pre-check guarantees.
    try:
        return float(
            brentq(
                lambda s: float(fn(F, K, T, s, D)) - price,
                lo,
                hi,
                xtol=_NR_TOL,
                rtol=_NR_TOL,
                maxiter=200,
            )
        )
    except (ValueError, RuntimeError):
        return float("nan")


def invert_chain(quotes: pd.DataFrame, F: float, D: float, T: float) -> pd.DataFrame:
    """Add an ``iv`` column to ``quotes`` by inverting each mid price.

    Rows where IV inversion fails are dropped. The returned DataFrame is
    reindexed and otherwise unchanged.

    Expected input columns: ``strike``, ``mid``, ``is_call``.
    """
    out = quotes.copy()
    if len(out) == 0:
        out["iv"] = np.array([], dtype=float)
        return out
    ivs = np.empty(len(out), dtype=float)
    for i, row in enumerate(out.itertuples(index=False)):
        ivs[i] = implied_vol_one(
            float(row.mid),
            F,
            float(row.strike),
            T,
            D,
            bool(row.is_call),
        )
    out["iv"] = ivs
    return out.dropna(subset=["iv"]).reset_index(drop=True)
