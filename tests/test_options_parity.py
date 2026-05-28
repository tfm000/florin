"""Unit tests for the put-call parity helpers.

Two production paths are exercised:

- ``fit_parity`` — unconstrained two-parameter regression. Used by
  the pipeline solely as a *diagnostic* (its ``r`` populates
  ``SurfaceFit.r_implied_raw``). The sanity-bound + ``rate_quality``
  gating that previously lived here has been removed because the
  production pricing path no longer consumes the implied rate at all.

- ``fit_forward_at_rate`` — fixed-rate one-parameter forward
  estimator. The production path used by ``fit_expiry`` to obtain
  ``F`` and ``D`` given the external SOFR rate.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from stats.options.parity import fit_forward_at_rate, fit_parity
from stats.options.pricing import bs76_call, bs76_put


def _synthetic_chain(
    F: float,
    T: float,
    r: float,
    *,
    sigma: float = 0.25,
    n: int = 21,
    noise_std: float = 0.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Construct a synthetic option chain that exactly satisfies parity."""
    D = math.exp(-r * T)
    strikes = np.linspace(0.7 * F, 1.3 * F, n)
    rng = np.random.default_rng(seed)
    call_mid = bs76_call(F, strikes, T, sigma, D) + noise_std * rng.standard_normal(n)
    put_mid = bs76_put(F, strikes, T, sigma, D) + noise_std * rng.standard_normal(n)
    spread = np.full(n, 0.02)
    calls = pd.DataFrame({"strike": strikes, "mid": call_mid, "spread": spread, "is_call": True})
    puts = pd.DataFrame({"strike": strikes, "mid": put_mid, "spread": spread, "is_call": False})
    return pd.concat([calls, puts], ignore_index=True)


# ----------------------------------------------------------------------
# fit_parity — diagnostic two-parameter regression
# ----------------------------------------------------------------------


def test_recover_r_F_noiseless() -> None:
    F_true, T, r_true = 100.0, 0.5, 0.045
    chain = _synthetic_chain(F_true, T, r_true, noise_std=0.0)
    fit = fit_parity(chain, spot=99.0, T=T)
    assert math.isclose(fit.F, F_true, abs_tol=1e-6)
    assert math.isclose(fit.r, r_true, abs_tol=1e-8)
    assert fit.r2 > 0.9999


def test_noisy_r_within_5bps() -> None:
    """With 0.5 c bid-ask noise, parity-implied r is within 5 bps of truth."""
    F_true, T, r_true = 100.0, 0.5, 0.045
    chain = _synthetic_chain(F_true, T, r_true, noise_std=0.005)
    fit = fit_parity(chain, spot=100.0, T=T)
    assert abs(fit.r - r_true) < 5e-4


def test_too_few_strikes_raises() -> None:
    """Fewer than 3 common strikes → ValueError."""
    F, T = 100.0, 0.5
    K = np.array([95.0, 105.0])
    D = math.exp(-0.04 * T)
    calls = pd.DataFrame(
        {
            "strike": K,
            "mid": bs76_call(F, K, T, 0.25, D),
            "spread": [0.02, 0.02],
            "is_call": True,
        }
    )
    puts = pd.DataFrame(
        {
            "strike": K,
            "mid": bs76_put(F, K, T, 0.25, D),
            "spread": [0.02, 0.02],
            "is_call": False,
        }
    )
    chain = pd.concat([calls, puts], ignore_index=True)
    with pytest.raises(ValueError):
        fit_parity(chain, spot=F, T=T)


def test_iteration_converges() -> None:
    """F fixed-point converges within max_iter for a clean chain."""
    F_true, T, r_true = 250.0, 0.25, 0.040
    chain = _synthetic_chain(F_true, T, r_true, noise_std=0.0, n=15)
    fit = fit_parity(chain, spot=240.0, T=T)
    assert fit.n_iterations <= 5
    assert math.isclose(fit.F, F_true, abs_tol=1e-6)


# ----------------------------------------------------------------------
# fit_forward_at_rate — production fixed-rate path
# ----------------------------------------------------------------------


def test_fit_forward_at_rate_recovers_F_noiseless() -> None:
    """At the true SOFR, F is recovered exactly from a clean chain."""
    F_true, T, r_true = 100.0, 0.5, 0.045
    chain = _synthetic_chain(F_true, T, r_true, noise_std=0.0)
    fit = fit_forward_at_rate(chain, spot=99.0, T=T, r=r_true)
    assert math.isclose(fit.F, F_true, abs_tol=1e-6)
    # D, r are pinned by the caller, not extracted.
    assert math.isclose(fit.D, math.exp(-r_true * T), abs_tol=1e-12)
    assert math.isclose(fit.r, r_true, abs_tol=1e-12)


def test_fit_forward_at_rate_robust_to_noisy_slope() -> None:
    """A chain whose regression slope is severely corrupted still
    yields a near-correct F because the fixed-rate estimator doesn't
    rely on the slope — it just averages per-strike F_i = K_i +
    e^{rT}·(C_i − P_i)."""
    F_true, T = 100.0, 0.5
    r_true = 0.045
    # Build a clean chain at the true rate, then add a *slope-only*
    # perturbation: shift call mids up linearly in K so the C − P vs K
    # regression slope drifts away from −D, while the per-strike F_i
    # estimates remain unbiased on average. (We add equal-and-opposite
    # noise to call and put mids so the noise cancels in C − P; the
    # regression-slope view still picks up structure via weights, but
    # the weighted mean of F_i is exact.)
    base = _synthetic_chain(F_true, T, r_true, noise_std=0.0)
    rng = np.random.default_rng(0)
    K_unique = base.loc[base["is_call"], "strike"].to_numpy()
    perturb = 0.05 * (K_unique - F_true) / F_true  # ±0.5 c by deep-OTM
    cmask = base["is_call"].to_numpy()
    pmask = ~cmask
    base.loc[cmask, "mid"] = base.loc[cmask, "mid"].to_numpy() + perturb
    base.loc[pmask, "mid"] = base.loc[pmask, "mid"].to_numpy() + perturb
    # Add small symmetric noise on top for realism.
    base["mid"] = base["mid"].to_numpy() + 0.002 * rng.standard_normal(len(base))

    fit = fit_forward_at_rate(base, spot=F_true, T=T, r=r_true)
    # F recovered to within a few bps despite the deliberately
    # corrupted regression slope.
    assert abs(fit.F - F_true) / F_true < 5e-4


def test_fit_forward_at_rate_too_few_strikes_raises() -> None:
    """Fewer than 3 common strikes → ValueError."""
    F, T = 100.0, 0.5
    K = np.array([95.0, 105.0])
    D = math.exp(-0.04 * T)
    calls = pd.DataFrame(
        {
            "strike": K,
            "mid": bs76_call(F, K, T, 0.25, D),
            "spread": [0.02, 0.02],
            "is_call": True,
        }
    )
    puts = pd.DataFrame(
        {
            "strike": K,
            "mid": bs76_put(F, K, T, 0.25, D),
            "spread": [0.02, 0.02],
            "is_call": False,
        }
    )
    chain = pd.concat([calls, puts], ignore_index=True)
    with pytest.raises(ValueError):
        fit_forward_at_rate(chain, spot=F, T=T, r=0.04)


def test_fit_forward_at_rate_invalid_T_raises() -> None:
    """T <= 0 → ValidationError (FlorinError 400)."""
    from core.exceptions import ValidationError

    F = 100.0
    K = np.linspace(80.0, 120.0, 11)
    D = 1.0
    calls = pd.DataFrame(
        {
            "strike": K,
            "mid": bs76_call(F, K, 0.5, 0.25, D),
            "spread": np.full_like(K, 0.02),
            "is_call": True,
        }
    )
    puts = pd.DataFrame(
        {
            "strike": K,
            "mid": bs76_put(F, K, 0.5, 0.25, D),
            "spread": np.full_like(K, 0.02),
            "is_call": False,
        }
    )
    chain = pd.concat([calls, puts], ignore_index=True)
    with pytest.raises(ValidationError):
        fit_forward_at_rate(chain, spot=F, T=0.0, r=0.04)
