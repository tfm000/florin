"""
Risk-neutral density extraction — two closed-form paths.

We never compute ``∂²C/∂K²`` numerically on market quotes — the second
difference of noisy mids gives catastrophic RNDs. Instead the smooth
hybrid σ-curve (parametric + GP-residual mean / samples) is fed into a
closed-form expression that respects the structure of the
parametrisation.

**Gatheral (SSVI branch).** With ``w(k) = σ²(k)·T`` analytic from the
SSVI fit::

    d₂(k) = −k / √w(k) − ½ · √w(k)
    g(k)  = (1 − k·w'(k) / (2·w(k)))²
            − w'(k)² / 4 · (1 / w(k) + 1/4)
            + w''(k) / 2
    p(k)  = g(k) / √(2π·w(k)) · exp(−d₂(k)² / 2)
    q(K)  = p(k(K)) / K                                  (k = log(K / F))

(Gatheral, *The Volatility Surface* ch. 3; Gatheral-Jacquier 2014. The
``g(k)`` factor is exactly Durrleman's butterfly indicator.)

**Shimko (SABR branch).** Chain-rule expansion of ``∂²C/∂K²``::

    q(K) = φ(d₂) · { 1/(K·σ·√T)
                   + 2·(d₁/σ)·σ'(K)
                   + (K·√T·d₁·d₂/σ)·(σ'(K))²
                   + (K·√T)·σ''(K) }

with ``d₁,₂ = [ln(F/K) ± ½σ²T]/(σ√T)``. The ``e^{rT}`` from
Breeden–Litzenberger cancels each BS ``D = e^{-rT}``.

Uncertainty propagation. Per posterior GP sample of (σ, σ', σ''):

    1. Compute q_s(K_grid).
    2. Clip q_s ← max(q_s, 0).
    3. Renormalise q_s ← q_s / ∫q_s dK.

Median + 68 % / 90 % percentile bands across samples form the credible
intervals.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from stats.options.types import RND, RNDBand, VolModel


def _summarise_density(K_grid: np.ndarray, density: np.ndarray) -> tuple[float, float, float]:
    """Trapezoidal integrals: ``(∫q, E[K], Var(K))``."""
    integral = float(np.trapezoid(density, K_grid))
    if integral > 0:
        mean = float(np.trapezoid(K_grid * density, K_grid) / integral)
        var = float(np.trapezoid((K_grid - mean) ** 2 * density, K_grid) / integral)
    else:
        mean = float("nan")
        var = float("nan")
    return integral, mean, var


def rnd_gatheral_one(
    k: np.ndarray,
    w: np.ndarray,
    w_prime: np.ndarray,
    w_double: np.ndarray,
    K_grid: np.ndarray,
) -> np.ndarray:
    """One-sample Gatheral RND from total variance derivatives."""
    safe_w = np.maximum(w, 1e-12)
    d2 = -k / np.sqrt(safe_w) - 0.5 * np.sqrt(safe_w)
    g = (
        (1.0 - k * w_prime / (2.0 * safe_w)) ** 2
        - (w_prime * w_prime) / 4.0 * (1.0 / safe_w + 0.25)
        + w_double / 2.0
    )
    p_k = g / np.sqrt(2.0 * np.pi * safe_w) * np.exp(-d2 * d2 / 2.0)
    return p_k / np.asarray(K_grid, dtype=float)


def rnd_shimko_one(
    K_grid: np.ndarray,
    sigma: np.ndarray,
    sigma_prime: np.ndarray,
    sigma_double: np.ndarray,
    F: float,
    T: float,
) -> np.ndarray:
    """One-sample Shimko RND from σ(K) derivatives.

    ``sigma_prime`` and ``sigma_double`` are wrt ``K``.
    """
    K = np.asarray(K_grid, dtype=float)
    sqrt_T = np.sqrt(T)
    sig = np.maximum(np.asarray(sigma, dtype=float), 1e-8)
    sigsqrtT = sig * sqrt_T
    d1 = (np.log(F / K) + 0.5 * sig * sig * T) / sigsqrtT
    d2 = d1 - sigsqrtT
    phi_d2 = norm.pdf(d2)
    term_1 = 1.0 / (K * sigsqrtT)
    term_2 = 2.0 * (d1 / sig) * sigma_prime
    term_3 = (K * sqrt_T * d1 * d2 / sig) * (sigma_prime * sigma_prime)
    term_4 = K * sqrt_T * sigma_double
    return phi_d2 * (term_1 + term_2 + term_3 + term_4)


def _clip_and_renormalise(
    densities: np.ndarray, K_grid: np.ndarray
) -> tuple[np.ndarray, int]:
    """Clip negatives to zero and rescale each row to integrate to 1.

    Returns the new density matrix and the count of samples that
    required clipping (``q < 0`` somewhere before clipping).
    """
    bad = densities < 0
    n_neg = int(np.any(bad, axis=1).sum())
    out = np.maximum(densities, 0.0)
    integrals = np.trapezoid(out, K_grid, axis=1)
    valid = integrals > 0
    out[valid] = out[valid] / integrals[valid, None]
    return out, n_neg


def rnd_with_uncertainty(
    K_grid: np.ndarray,
    sigma_samples: np.ndarray,
    sigma_prime_samples: np.ndarray,
    sigma_double_samples: np.ndarray,
    F: float,
    T: float,
    model: VolModel,
    *,
    derivative_space: str = "auto",
) -> RNDBand:
    """Per-sample RND extraction with credible-band aggregation.

    Args:
        K_grid: strike grid on which σ and its derivatives are evaluated.
        sigma_samples:        (n_samples, n_grid) hybrid IV curves.
        sigma_prime_samples:  derivative of σ. ``derivative_space``
                              controls whether this is dσ/dk (k-space)
                              or dσ/dK (K-space) — see below.
        sigma_double_samples: second derivative of σ.
        F:    parity-implied forward.
        T:    time to expiry (years).
        model:  ``VolModel.SSVI`` → Gatheral closed form (k-space).
                ``VolModel.SABR`` → Shimko closed form (K-space).
        derivative_space:  ``'auto'`` (default — pick based on model:
            SSVI → ``'k'``, SABR → ``'K'``), ``'k'`` (derivatives are
            wrt ``k = log(K/F)``), or ``'K'`` (derivatives wrt ``K``).

    Returns:
        ``RNDBand`` with median and 68 % / 90 % credible intervals.
    """
    K = np.asarray(K_grid, dtype=float)
    k = np.log(K / F)
    n_samples = sigma_samples.shape[0]
    densities = np.empty_like(sigma_samples)

    if derivative_space == "auto":
        space = "k" if model == VolModel.SSVI else "K"
    else:
        space = derivative_space

    for s in range(n_samples):
        sigma = sigma_samples[s]
        sp = sigma_prime_samples[s]
        spp = sigma_double_samples[s]

        if model == VolModel.SSVI:
            # Gatheral needs (w, w', w'') wrt k.
            if space == "K":
                # Convert K-derivatives to k-derivatives:
                # dσ/dk = K · dσ/dK
                # d²σ/dk² = K · (K·d²σ/dK² + dσ/dK) = K²·d²σ/dK² + K·dσ/dK
                sp_k = K * sp
                spp_k = K * K * spp + K * sp
            else:
                sp_k = sp
                spp_k = spp
            w = T * sigma * sigma
            wp = 2.0 * T * sigma * sp_k
            wpp = 2.0 * T * (sp_k * sp_k + sigma * spp_k)
            q = rnd_gatheral_one(k, w, wp, wpp, K)
        else:
            # Shimko needs (σ, σ', σ'') wrt K.
            if space == "k":
                # k = log(K/F). dσ/dK = dσ/dk · 1/K.
                # d²σ/dK² = (d²σ/dk² − dσ/dk) / K².
                sp_K = sp / K
                spp_K = (spp - sp) / (K * K)
            else:
                sp_K = sp
                spp_K = spp
            q = rnd_shimko_one(K, sigma, sp_K, spp_K, F, T)

        densities[s] = q

    densities, n_neg = _clip_and_renormalise(densities, K)

    median = np.median(densities, axis=0)
    lo68 = np.quantile(densities, 0.16, axis=0)
    hi68 = np.quantile(densities, 0.84, axis=0)
    lo90 = np.quantile(densities, 0.05, axis=0)
    hi90 = np.quantile(densities, 0.95, axis=0)

    integral, mean, _ = _summarise_density(K, median)
    diagnostics = {
        "n_neg_clipped": n_neg,
        "median_integral": integral,
        "median_mean": mean,
        "mean_recovery_pct": (mean - F) / F * 100.0 if F > 0 else float("nan"),
        "F": float(F),
    }

    return RNDBand(
        K_grid=K,
        density_median=median,
        density_lo68=lo68,
        density_hi68=hi68,
        density_lo90=lo90,
        density_hi90=hi90,
        n_samples=n_samples,
        method="gatheral" if model == VolModel.SSVI else "shimko",
        diagnostics=diagnostics,
    )


def rnd_from_curve(
    K_grid: np.ndarray,
    sigma: np.ndarray,
    sigma_prime: np.ndarray,
    sigma_double: np.ndarray,
    F: float,
    T: float,
    model: VolModel,
    *,
    derivative_space: str = "auto",
) -> RND:
    """Single-curve RND (no uncertainty) — used for sanity checks /
    tests and as the fallback median when GP samples are unavailable."""
    band = rnd_with_uncertainty(
        K_grid,
        sigma[None, :],
        sigma_prime[None, :],
        sigma_double[None, :],
        F,
        T,
        model,
        derivative_space=derivative_space,
    )
    integral, mean, var = _summarise_density(K_grid, band.density_median)
    return RND(
        K_grid=band.K_grid,
        density=band.density_median,
        integral=integral,
        mean=mean,
        variance=var,
        method=band.method,
        diagnostics=band.diagnostics,
    )
