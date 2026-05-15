"""Unit tests for Black-76 pricing and Greeks."""

from __future__ import annotations

import math

import numpy as np

from stats.options.pricing import (
    bs76_call,
    bs76_put,
    bs_vanna,
    bs_vega,
    bs_volga,
    intrinsic_call,
    intrinsic_put,
)


def test_pcp_synthetic() -> None:
    """Black-76 satisfies put-call parity: C − P = D · (F − K) exactly."""
    rng = np.random.default_rng(0)
    F = 100.0
    T = 0.5
    D = math.exp(-0.04 * T)
    K = np.linspace(70.0, 130.0, 13)
    sigma = np.clip(0.2 + 0.05 * rng.standard_normal(K.shape), 0.05, 0.6)
    C = bs76_call(F, K, T, sigma, D)
    P = bs76_put(F, K, T, sigma, D)
    np.testing.assert_allclose(C - P, D * (F - K), atol=1e-12)


def test_vega_positive() -> None:
    """Vega is non-negative on any valid (F, K, σ, T)."""
    rng = np.random.default_rng(1)
    F = 100.0 + rng.uniform(-20, 20, 20)
    K = 100.0 + rng.uniform(-30, 30, 20)
    sigma = rng.uniform(0.05, 0.6, 20)
    T = rng.uniform(0.05, 2.0, 20)
    D = np.exp(-0.04 * T)
    v = bs_vega(F, K, T, sigma, D)
    assert np.all(v >= 0.0)


def test_vanna_volga_finite_diff() -> None:
    """Analytic vanna and volga match mixed-/second central FD."""
    F = 100.0
    K = 95.0
    T = 0.5
    sigma = 0.25
    D = math.exp(-0.04 * T)
    h = 1e-4

    # Vanna = ∂²C / ∂K ∂σ via mixed central FD.
    fd_vanna = (
        bs76_call(F, K + h, T, sigma + h, D)
        - bs76_call(F, K + h, T, sigma - h, D)
        - bs76_call(F, K - h, T, sigma + h, D)
        + bs76_call(F, K - h, T, sigma - h, D)
    ) / (4.0 * h * h)
    assert math.isclose(
        float(bs_vanna(F, K, T, sigma, D)),
        float(fd_vanna),
        rel_tol=1e-4,
        abs_tol=1e-6,
    )

    # Volga = ∂²C / ∂σ² via second central FD.
    fd_volga = (
        bs76_call(F, K, T, sigma + h, D)
        - 2.0 * bs76_call(F, K, T, sigma, D)
        + bs76_call(F, K, T, sigma - h, D)
    ) / (h * h)
    assert math.isclose(
        float(bs_volga(F, K, T, sigma, D)),
        float(fd_volga),
        rel_tol=1e-3,
        abs_tol=1e-4,
    )


def test_intrinsic_bounds() -> None:
    F = 100.0
    K = np.array([80.0, 100.0, 120.0])
    D = 0.96
    np.testing.assert_allclose(
        intrinsic_call(F, K, D),
        D * np.array([20.0, 0.0, 0.0]),
    )
    np.testing.assert_allclose(
        intrinsic_put(F, K, D),
        D * np.array([0.0, 0.0, 20.0]),
    )


def test_call_above_intrinsic() -> None:
    """C ≥ D·(F − K)⁺ and C ≤ D·F (no-arbitrage bounds on the call price)."""
    F = 100.0
    T = 0.5
    D = math.exp(-0.03 * T)
    K = np.linspace(50.0, 150.0, 21)
    sigma = 0.3
    C = bs76_call(F, K, T, sigma, D)
    floor = intrinsic_call(F, K, D)
    cap = np.full_like(K, D * F)
    assert np.all(floor - 1e-10 <= C)
    assert np.all(cap + 1e-10 >= C)
