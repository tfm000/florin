"""
Put-call parity — forward and rate extraction at one expiry.

Two entry points:

- :func:`fit_parity` runs the unconstrained two-parameter regression
  ``C − P = D·F − D·K + ε``, returning the chain-implied
  ``(D, F, r)``. **Only used now as a diagnostic** — the implied ``r``
  is reported as ``r_implied_raw`` so quants can see how far the chain
  drifts from the true rate, but the production pipeline never uses
  it for pricing (sub-cent bid-ask noise + tiny T amplifies into
  absurd annualised rates on short-DTE chains).

- :func:`fit_forward_at_rate` is the production path. With ``r``
  pinned to the externally-known risk-free rate (SOFR), the parity
  equation reduces per-strike to

      F_i  =  K_i  +  e^{r·T} · (C_i^mid − P_i^mid)

  and the inverse-spread²-weighted mean across the ATM band is a
  robust one-parameter estimator for ``F``. This both eliminates the
  noise-amplification problem on ``r`` *and* yields a more stable
  ``F`` than the two-parameter regression (the slope estimate, which
  was the noisy part, is replaced by a known constant).

References:
    Figlewski (2017). Risk Neutral Densities: A Review. NYU Stern.
    van Binsbergen, Diamond & Grotteria (2022). Risk-Free Interest
        Rates. JFE 143 (1), 1–29.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from core.exceptions import ValidationError
from stats.options.types import ParityFit

_D_FLOOR = 1e-6
_MAX_ITER = 5
_TOL_F = 1e-6
_MIN_COMMON_STRIKES = 3


def fit_parity(
    quotes: pd.DataFrame,
    spot: float,
    T: float,
    *,
    atm_band: float = 0.30,
    max_iter: int = _MAX_ITER,
    tol: float = _TOL_F,
) -> ParityFit:
    """Unconstrained two-parameter parity regression — diagnostic only.

    Returns the *chain-implied* ``(D, F, r)`` from the slope/intercept of
    ``C − P  vs  K``. The implied ``r`` is unreliable on short-DTE or
    illiquid chains (sub-cent bid-ask noise amplified by tiny T), so
    the production pipeline calls this purely to populate
    ``SurfaceFit.r_implied_raw`` for quant diagnostics, and uses
    :func:`fit_forward_at_rate` with an external SOFR rate for the
    actual ``F`` and ``D``.
    """
    if T <= 0:
        raise ValidationError(
            f"Put-call parity needs T > 0 (got T = {T:.6f} years). "
            "Expired or zero-DTE chains cannot be priced."
        )
    calls = quotes[quotes["is_call"]].set_index("strike")
    puts = quotes[~quotes["is_call"]].set_index("strike")
    common_K = calls.index.intersection(puts.index)
    if len(common_K) < _MIN_COMMON_STRIKES:
        raise ValueError(
            f"Need >= {_MIN_COMMON_STRIKES} strikes with both put and call "
            f"mids for parity regression (got {len(common_K)})"
        )

    K = np.asarray(common_K, dtype=float)
    diff = calls.loc[common_K, "mid"].to_numpy(dtype=float) - puts.loc[common_K, "mid"].to_numpy(
        dtype=float
    )
    spread_c = calls.loc[common_K, "spread"].to_numpy(dtype=float)
    spread_p = puts.loc[common_K, "spread"].to_numpy(dtype=float)
    half_sum = 0.5 * (spread_c + spread_p)
    weights = 1.0 / np.maximum(half_sum * half_sum, 1e-8)

    F = float(spot)
    D = 1.0
    r2 = 0.0
    resid_std = float("nan")
    n_iter = 0

    for iteration in range(1, max_iter + 1):
        n_iter = iteration
        F_prev = F
        lm = np.log(K / F)
        mask = np.abs(lm) <= atm_band
        if mask.sum() < _MIN_COMMON_STRIKES:
            mask = np.ones_like(K, dtype=bool)

        K_m = K[mask]
        y_m = diff[mask]
        w_m = weights[mask]

        A = np.column_stack([np.ones_like(K_m), K_m])
        WA = A * w_m[:, None]
        coefs = np.linalg.lstsq(WA, w_m * y_m, rcond=None)[0]
        alpha = float(coefs[0])
        beta = float(coefs[1])

        D = max(-beta, _D_FLOOR)
        F = alpha / D if D > 0 else float(spot)

        fitted = alpha + beta * K_m
        resid = y_m - fitted
        ss_res = float(np.sum(w_m * resid * resid))
        w_total = float(np.sum(w_m))
        y_mean = float(np.sum(w_m * y_m) / w_total) if w_total > 0 else 0.0
        ss_tot = float(np.sum(w_m * (y_m - y_mean) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        resid_std = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0

        rel_change = abs(F - F_prev) / max(abs(F_prev), _D_FLOOR)
        if rel_change < tol:
            break

    r = -np.log(D) / T if (T > 0 and D > 0) else 0.0

    return ParityFit(
        D=float(D),
        F=float(F),
        r=float(r),
        r2=float(r2),
        residual_std=float(resid_std),
        n_strikes=int(len(common_K)),
        n_iterations=int(n_iter),
    )


def fit_forward_at_rate(
    quotes: pd.DataFrame,
    spot: float,
    T: float,
    r: float,
    *,
    atm_band: float = 0.30,
    max_iter: int = _MAX_ITER,
    tol: float = _TOL_F,
) -> ParityFit:
    """Extract the forward ``F`` at a *fixed* external risk-free rate.

    With ``r`` pinned, ``D = e^{-r·T}`` is known and the parity
    equation becomes per-strike

        F_i  =  K_i + e^{r·T}·(C_i^mid − P_i^mid)

    so ``F`` is the inverse-spread²-weighted mean of ``F_i`` across the
    ATM band ``|log(K/F)| ≤ atm_band``. The band depends on ``F`` so
    we iterate to a fixed point (typically two passes — spot is
    already within bps of F for liquid US equity).

    Args:
        quotes: DataFrame with ``strike``, ``mid``, ``is_call``, ``spread``.
        spot:   underlying spot (initial F guess).
        T:      time to expiry in years.
        r:      externally-known annualised rate (decimal — SOFR).
        atm_band, max_iter, tol: identical semantics to :func:`fit_parity`.

    Returns:
        ``ParityFit`` with the fixed ``D, r`` and the chain-extracted
        ``F``. ``r2`` is the coefficient of determination of the
        per-strike ``F_i`` against their weighted mean (close to 1
        when the chain is clean; lower on noisy / mismatched-tick
        chains, but unlike the two-parameter regression a low R² here
        doesn't compromise ``F``).
    """
    if T <= 0:
        raise ValidationError(f"Parity needs T > 0 (got T = {T:.6f} years).")
    calls = quotes[quotes["is_call"]].set_index("strike")
    puts = quotes[~quotes["is_call"]].set_index("strike")
    common_K = calls.index.intersection(puts.index)
    if len(common_K) < _MIN_COMMON_STRIKES:
        raise ValueError(
            f"Need >= {_MIN_COMMON_STRIKES} strikes with both put and call "
            f"mids for forward extraction (got {len(common_K)})"
        )

    D = math.exp(-r * T)
    e_rT = math.exp(r * T)

    K = np.asarray(common_K, dtype=float)
    diff = calls.loc[common_K, "mid"].to_numpy(dtype=float) - puts.loc[common_K, "mid"].to_numpy(
        dtype=float
    )
    F_i = K + e_rT * diff
    spread_c = calls.loc[common_K, "spread"].to_numpy(dtype=float)
    spread_p = puts.loc[common_K, "spread"].to_numpy(dtype=float)
    half_sum = 0.5 * (spread_c + spread_p)
    weights = 1.0 / np.maximum(half_sum * half_sum, 1e-8)

    F = float(spot)
    resid_std = float("nan")
    r2 = 0.0
    n_iter = 0

    for iteration in range(1, max_iter + 1):
        n_iter = iteration
        F_prev = F
        lm = np.log(K / F)
        mask = np.abs(lm) <= atm_band
        if mask.sum() < _MIN_COMMON_STRIKES:
            mask = np.ones_like(K, dtype=bool)

        F_m = F_i[mask]
        w_m = weights[mask]

        w_total = float(np.sum(w_m))
        if w_total <= 0:
            F = float(spot)
            break
        F = float(np.sum(w_m * F_m) / w_total)

        # Weighted residual sum of squares of per-strike F estimates
        # around their weighted mean — a clean chain has all F_i ≈ F
        # so this is tiny; noisy chains produce dispersion but the
        # central F estimate remains unbiased.
        ss_res = float(np.sum(w_m * (F_m - F) ** 2))
        # Diagnostic: residual std of F_i.
        resid_std = float(np.sqrt(ss_res / w_total)) if w_total > 0 else 0.0
        # R² formulation informative for the fixed-rate path:
        # 1 − var(F_i)/var(K_i). Close to 1 when F_i is concentrated;
        # values near 0 flag a dispersive chain (but ``F`` is still
        # unbiased so this is purely diagnostic).
        var_K = float(np.sum(w_m * (K[mask] - np.mean(K[mask])) ** 2))
        r2 = 1.0 - (ss_res / var_K) if var_K > 0 else 0.0

        rel_change = abs(F - F_prev) / max(abs(F_prev), _D_FLOOR)
        if rel_change < tol:
            break

    return ParityFit(
        D=float(D),
        F=float(F),
        r=float(r),
        r2=float(r2),
        residual_std=float(resid_std),
        n_strikes=int(len(common_K)),
        n_iterations=int(n_iter),
    )
