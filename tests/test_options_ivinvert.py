"""Unit tests for implied-volatility inversion."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from stats.options.ivinvert import implied_vol_one, invert_chain
from stats.options.pricing import bs76_call, bs76_put


def test_roundtrip_call() -> None:
    F = 100.0
    K = 95.0
    T = 0.5
    sigma_true = 0.25
    D = math.exp(-0.04 * T)
    price = float(bs76_call(F, K, T, sigma_true, D))
    sigma = implied_vol_one(price, F, K, T, D, is_call=True)
    assert math.isclose(sigma, sigma_true, abs_tol=1e-7)


def test_roundtrip_put() -> None:
    F = 100.0
    K = 105.0
    T = 0.5
    sigma_true = 0.32
    D = math.exp(-0.04 * T)
    price = float(bs76_put(F, K, T, sigma_true, D))
    sigma = implied_vol_one(price, F, K, T, D, is_call=False)
    assert math.isclose(sigma, sigma_true, abs_tol=1e-7)


def test_roundtrip_grid() -> None:
    """Round-trip 60 random (K, σ) combos with NR fast path.

    Skips deep-OTM low-σ combinations where the BS price collapses below
    1 e−6 — the round-trip is mathematically singular there and the
    realistic chain quality filter (rel-spread ≤ 25 %) drops those
    quotes before they reach the inverter.
    """
    rng = np.random.default_rng(42)
    F = 100.0
    T = 0.5
    D = math.exp(-0.04 * T)
    Ks = rng.uniform(70.0, 130.0, 60)
    sigmas = rng.uniform(0.10, 0.80, 60)
    for K, s in zip(Ks, sigmas, strict=True):
        price = float(bs76_call(F, float(K), T, float(s), D))
        if price < 1e-6:
            continue  # below numerical-noise floor
        recovered = implied_vol_one(price, F, float(K), T, D, is_call=True)
        assert math.isclose(recovered, float(s), abs_tol=1e-7)


def test_oob_price_below_intrinsic() -> None:
    F = 100.0
    K = 95.0
    T = 0.5
    D = math.exp(-0.04 * T)
    # Price below intrinsic floor → NaN.
    assert math.isnan(implied_vol_one(0.5 * D * (F - K), F, K, T, D, is_call=True))


def test_oob_price_above_cap() -> None:
    F = 100.0
    K = 95.0
    T = 0.5
    D = math.exp(-0.04 * T)
    # Price above D·F cap → NaN.
    assert math.isnan(implied_vol_one(1.5 * D * F, F, K, T, D, is_call=True))


def test_zero_T_returns_nan() -> None:
    assert math.isnan(implied_vol_one(1.0, 100.0, 100.0, 0.0, 1.0, is_call=True))


def test_invert_chain_smile() -> None:
    """A whole smile round-trips through invert_chain."""
    F = 100.0
    T = 0.5
    D = math.exp(-0.04 * T)
    strikes = np.linspace(80.0, 120.0, 9)
    sigma_smile = 0.20 + 0.05 * (strikes - F) ** 2 / F**2  # gentle smile
    quotes = pd.DataFrame(
        {
            "strike": strikes,
            "mid": bs76_call(F, strikes, T, sigma_smile, D),
            "spread": 0.02 * np.ones_like(strikes),
            "is_call": True,
        }
    )
    out = invert_chain(quotes, F, D, T)
    np.testing.assert_allclose(out["iv"].to_numpy(), sigma_smile, atol=1e-7)
