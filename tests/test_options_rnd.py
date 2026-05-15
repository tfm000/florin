"""Unit tests for the closed-form RND paths."""

from __future__ import annotations

import math

import numpy as np

from stats.options.diagnostics import durrleman_g
from stats.options.rnd import (
    rnd_from_curve,
    rnd_with_uncertainty,
)
from stats.options.types import VolModel


def _make_flat_iv_grid(F: float, sigma: float, T: float, K_grid: np.ndarray):
    """Constant-σ smile and its derivatives — RND is exactly lognormal."""
    K = np.asarray(K_grid, dtype=float)
    n = K.size
    return (
        np.full(n, sigma),
        np.zeros(n),
        np.zeros(n),
    )


def _lognormal_density(K: np.ndarray, F: float, sigma: float, T: float) -> np.ndarray:
    """Closed-form risk-neutral lognormal density on K-space."""
    s = sigma * math.sqrt(T)
    d2 = (np.log(F / K) - 0.5 * sigma * sigma * T) / s
    return np.exp(-0.5 * d2 * d2) / (K * s * math.sqrt(2.0 * math.pi))


def test_gatheral_lognormal() -> None:
    """Flat-σ smile recovered RND via Gatheral path is exactly lognormal."""
    F = 100.0
    sigma = 0.20
    T = 0.5
    K_grid = np.linspace(20.0, 400.0, 1901)  # wide enough to keep tail
    sig, sp, spp = _make_flat_iv_grid(F, sigma, T, K_grid)
    rnd = rnd_from_curve(K_grid, sig, sp, spp, F, T, VolModel.SSVI)
    expected = _lognormal_density(K_grid, F, sigma, T)
    np.testing.assert_allclose(rnd.density, expected, rtol=1e-4, atol=1e-9)


def test_shimko_lognormal() -> None:
    """Same flat-σ smile via Shimko path also recovers the lognormal."""
    F = 100.0
    sigma = 0.20
    T = 0.5
    K_grid = np.linspace(20.0, 400.0, 1901)
    sig, sp, spp = _make_flat_iv_grid(F, sigma, T, K_grid)
    rnd = rnd_from_curve(K_grid, sig, sp, spp, F, T, VolModel.SABR)
    expected = _lognormal_density(K_grid, F, sigma, T)
    np.testing.assert_allclose(rnd.density, expected, rtol=1e-4, atol=1e-9)


def test_two_paths_agree_on_smile() -> None:
    """Gatheral and Shimko produce the same RND on the same smile.

    Uses a smooth synthetic smile that's small enough to keep both
    closed forms in their well-defined region.
    """
    F = 100.0
    T = 0.5
    K_grid = np.linspace(70.0, 140.0, 301)
    k = np.log(K_grid / F)
    # σ(k) = a + b·k + c·k² — easy analytic derivatives.
    a, b, c = 0.22, -0.06, 0.40
    sigma_k = a + b * k + c * k * k
    sig_prime_k = b + 2 * c * k
    sig_double_k = 2 * c * np.ones_like(k)

    # SSVI path: derivatives wrt k.
    rnd_g = rnd_from_curve(
        K_grid, sigma_k, sig_prime_k, sig_double_k, F, T, VolModel.SSVI,
        derivative_space="k",
    )
    # SABR path: convert k-derivatives to K-derivatives via chain rule.
    sig_prime_K = sig_prime_k / K_grid
    sig_double_K = (sig_double_k - sig_prime_k) / (K_grid * K_grid)
    rnd_s = rnd_from_curve(
        K_grid, sigma_k, sig_prime_K, sig_double_K, F, T, VolModel.SABR,
        derivative_space="K",
    )
    # Compare on the inner part of the grid (avoid wing renormalisation
    # artefacts).
    mask = slice(50, -50)
    np.testing.assert_allclose(rnd_g.density[mask], rnd_s.density[mask], rtol=1e-2, atol=1e-5)


def test_integral_one_and_mean_equals_F() -> None:
    """Sanity gates from plan §10: ∫q = 1 ± 1e-3 and E[K] = F ± 1e-3·F."""
    F = 100.0
    sigma = 0.25
    T = 0.5
    K_grid = np.linspace(30.0, 300.0, 501)  # wide grid to cover tails
    sig, sp, spp = _make_flat_iv_grid(F, sigma, T, K_grid)
    rnd = rnd_from_curve(K_grid, sig, sp, spp, F, T, VolModel.SSVI)
    assert abs(rnd.integral - 1.0) < 1e-3
    assert abs(rnd.mean - F) / F < 1e-3


def test_uncertainty_band_collapses_to_zero_at_zero_variance() -> None:
    """A degenerate sample set (all samples identical) gives a zero-width
    band: lo == median == hi."""
    F = 100.0
    sigma = 0.20
    T = 0.5
    K_grid = np.linspace(60.0, 160.0, 201)
    sig, sp, spp = _make_flat_iv_grid(F, sigma, T, K_grid)
    n_samples = 20
    sig_samples = np.tile(sig, (n_samples, 1))
    sp_samples = np.tile(sp, (n_samples, 1))
    spp_samples = np.tile(spp, (n_samples, 1))
    band = rnd_with_uncertainty(
        K_grid, sig_samples, sp_samples, spp_samples, F, T, VolModel.SSVI
    )
    np.testing.assert_allclose(band.density_lo90, band.density_median, atol=1e-12)
    np.testing.assert_allclose(band.density_hi90, band.density_median, atol=1e-12)


def test_durrleman_clean_on_flat() -> None:
    """On a flat-σ smile, the Durrleman g equals 1 − w² · (1/w + 1/4) / 4
    + 0 = (always > 0). Concretely, g(0) = 1."""
    sigma = 0.20
    T = 0.5
    k = np.linspace(-0.5, 0.5, 201)
    w = np.full_like(k, sigma ** 2 * T)
    g = durrleman_g(k, w, np.zeros_like(k), np.zeros_like(k))
    # For w' = w'' = 0 and constant w, g(k) reduces to (1 − 0)² − 0 + 0 = 1.
    np.testing.assert_allclose(g, 1.0, atol=1e-12)


def test_durrleman_negative_under_arb() -> None:
    """An IV curve with too-steep skew triggers negative Durrleman g
    (butterfly arbitrage)."""
    k = np.linspace(-0.5, 0.5, 401)
    # Construct (w, w', w'') with very large w' and small w'' so the
    # middle term dominates. (w_value implies σ²T = 0.04, e.g. σ=√0.08 / √T.)
    w = np.full_like(k, 0.04)
    w_prime = np.full_like(k, 5.0)  # absurdly steep
    w_double = np.zeros_like(k)
    g = durrleman_g(k, w, w_prime, w_double)
    assert np.min(g) < 0.0
