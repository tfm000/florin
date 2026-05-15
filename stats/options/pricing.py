"""
Black-76 option pricing and Greeks.

Black-76 prices European-style options on a forward ``F``. Working in
forward space, the risk-free rate and dividend yield are absorbed into
``F``; only the discount factor ``D = e^{-rT}`` appears explicitly.

Formulas:
    d1, d2 = (ln(F/K) ± ½σ²T) / (σ√T)
    C(K)   = D · [F · Φ(d1) − K · Φ(d2)]
    P(K)   = D · [K · Φ(−d2) − F · Φ(−d1)]

Greeks (used by the RND pipeline):
    Vega   = ∂C/∂σ   = D · F · φ(d1) · √T   = D · K · φ(d2) · √T
    Vanna  = ∂²C/∂K∂σ = D · φ(d2) · d1 / σ
    Volga  = ∂²C/∂σ²  = D · K · φ(d2) · √T · d1 · d2 / σ

References:
    Black, F. (1976). The Pricing of Commodity Contracts.
        Journal of Financial Economics 3, 167–179.
    Shimko, D. (1993). Bounds of Probability. Risk 6(4) — for the
        chain-rule expansion that the SABR-branch RND uses.

Conventions: all inputs are NumPy-broadcasting friendly. ``sigma`` is in
decimal (0.2 = 20 %). ``T`` is in years.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def _d1_d2(
    F: float | np.ndarray,
    K: float | np.ndarray,
    T: float,
    sigma: float | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Black-76 d1, d2.

    Returns NaN entries wherever ``σ√T`` collapses to zero (T → 0 or
    σ → 0); callers should guard accordingly.
    """
    F_a = np.asarray(F, dtype=float)
    K_a = np.asarray(K, dtype=float)
    sig = np.asarray(sigma, dtype=float)
    sqrt_T = np.sqrt(T)
    denom = sig * sqrt_T
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(F_a / K_a) + 0.5 * sig * sig * T) / denom
        d2 = d1 - denom
    return d1, d2


def bs76_call(F, K, T: float, sigma, D: float) -> np.ndarray:
    """Black-76 European call price."""
    F_a = np.asarray(F, dtype=float)
    K_a = np.asarray(K, dtype=float)
    d1, d2 = _d1_d2(F_a, K_a, T, sigma)
    return D * (F_a * norm.cdf(d1) - K_a * norm.cdf(d2))


def bs76_put(F, K, T: float, sigma, D: float) -> np.ndarray:
    """Black-76 European put price."""
    F_a = np.asarray(F, dtype=float)
    K_a = np.asarray(K, dtype=float)
    d1, d2 = _d1_d2(F_a, K_a, T, sigma)
    return D * (K_a * norm.cdf(-d2) - F_a * norm.cdf(-d1))


def bs_vega(F, K, T: float, sigma, D: float) -> np.ndarray:
    """Vega = ∂C/∂σ.

    Two equivalent analytic forms (kept as one expression because
    the F·φ(d1) form is well-defined even when K → 0):
        D · F · φ(d1) · √T   ≡   D · K · φ(d2) · √T
    """
    F_a = np.asarray(F, dtype=float)
    d1, _ = _d1_d2(F_a, K, T, sigma)
    return D * F_a * norm.pdf(d1) * np.sqrt(T)


def bs_vanna(F, K, T: float, sigma, D: float) -> np.ndarray:
    """Cross-K-σ Greek: ∂²C/∂K∂σ = D · φ(d2) · d1 / σ.

    Derivation: ∂C/∂K|_σ = -D · Φ(d2); differentiating in σ and using
    ∂d2/∂σ = -d1/σ recovers the form above. Used by the Shimko closed-
    form RND on the SABR branch.
    """
    K_a = np.asarray(K, dtype=float)
    sig = np.asarray(sigma, dtype=float)
    d1, d2 = _d1_d2(F, K_a, T, sig)
    with np.errstate(divide="ignore", invalid="ignore"):
        return D * norm.pdf(d2) * d1 / sig


def bs_volga(F, K, T: float, sigma, D: float) -> np.ndarray:
    """Volga (vomma) = ∂²C/∂σ² = D · K · φ(d2) · √T · d1 · d2 / σ.

    Used by the Shimko closed-form RND on the SABR branch.
    """
    K_a = np.asarray(K, dtype=float)
    sig = np.asarray(sigma, dtype=float)
    d1, d2 = _d1_d2(F, K_a, T, sig)
    with np.errstate(divide="ignore", invalid="ignore"):
        return D * K_a * norm.pdf(d2) * np.sqrt(T) * d1 * d2 / sig


def intrinsic_call(F, K, D: float) -> np.ndarray:
    """Discounted intrinsic value of a European call on the forward."""
    F_a = np.asarray(F, dtype=float)
    K_a = np.asarray(K, dtype=float)
    return D * np.maximum(F_a - K_a, 0.0)


def intrinsic_put(F, K, D: float) -> np.ndarray:
    """Discounted intrinsic value of a European put on the forward."""
    F_a = np.asarray(F, dtype=float)
    K_a = np.asarray(K, dtype=float)
    return D * np.maximum(K_a - F_a, 0.0)
