"""End-to-end pipeline tests on synthetic chains."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from stats.options.pipeline import fit_expiry
from stats.options.pricing import bs76_call, bs76_put
from stats.options.ssvi import ssvi_iv
from stats.options.types import AssetClass, VolModel


def _build_synthetic_chain(
    F: float,
    T: float,
    r: float,
    iv_fn,
    *,
    n_strikes: int = 21,
    spread_abs: float = 0.05,
    rng_seed: int = 0,
) -> tuple[pd.DataFrame, float]:
    """Build a put-and-call chain that satisfies parity exactly under
    ``iv_fn`` (a callable K → σ).

    Returns ``(quotes_df, spot)`` where spot is set equal to F so that the
    parity fit converges in one iteration.
    """
    rng = np.random.default_rng(rng_seed)
    D = math.exp(-r * T)
    K = np.linspace(0.6 * F, 1.4 * F, n_strikes)
    sigma = np.asarray(iv_fn(K))
    call_mid = np.asarray(bs76_call(F, K, T, sigma, D))
    put_mid = np.asarray(bs76_put(F, K, T, sigma, D))
    # Add a tiny noise so the bid-ask is informative for GP heteroscedasticity.
    call_noise = 0.001 * rng.standard_normal(n_strikes)
    put_noise = 0.001 * rng.standard_normal(n_strikes)
    spread = np.full(n_strikes, spread_abs)
    bid_c = call_mid - spread / 2
    ask_c = call_mid + spread / 2
    bid_p = put_mid - spread / 2
    ask_p = put_mid + spread / 2
    calls = pd.DataFrame(
        {
            "strike": K,
            "bid": bid_c,
            "ask": ask_c,
            "mid": call_mid + call_noise,
            "last": call_mid + call_noise,
            "volume": np.full(n_strikes, 500),
            "oi": np.full(n_strikes, 500),
            "iv_yahoo": sigma,
            "is_call": True,
            "contract_symbol": [f"X{i}C" for i in range(n_strikes)],
            "spread": ask_c - bid_c,
        }
    )
    puts = pd.DataFrame(
        {
            "strike": K,
            "bid": bid_p,
            "ask": ask_p,
            "mid": put_mid + put_noise,
            "last": put_mid + put_noise,
            "volume": np.full(n_strikes, 500),
            "oi": np.full(n_strikes, 500),
            "iv_yahoo": sigma,
            "is_call": False,
            "contract_symbol": [f"X{i}P" for i in range(n_strikes)],
            "spread": ask_p - bid_p,
        }
    )
    return pd.concat([calls, puts], ignore_index=True), F


def test_end_to_end_synthetic_ssvi() -> None:
    """SSVI path on a true-SSVI smile — should pass every sanity gate."""
    F_true = 100.0
    T = 0.5
    r_true = 0.04
    ssvi_params = dict(theta_T=0.04, rho=-0.4, eta=0.5, gamma=0.3)

    def iv_fn(K):
        return ssvi_iv(np.log(np.asarray(K) / F_true), **ssvi_params, T=T)

    quotes, spot = _build_synthetic_chain(F_true, T, r_true, iv_fn)
    fit = fit_expiry(
        quotes,
        ticker="SYN",
        expiry="2026-12-31",
        T=T,
        spot=spot,
        r_external=r_true,
        model=VolModel.SSVI,
        asset_class=AssetClass.EQUITY,
        n_grid=200,
        gp_samples=100,
    )

    # F recovered from the chain at the externally-pinned r.
    assert abs(fit.F - F_true) / F_true < 1e-3
    # r is always the external value — no chain extraction.
    assert fit.r == pytest.approx(r_true)
    # r_implied_raw (diagnostic) still close to truth on a clean chain.
    assert abs(fit.r_implied_raw - r_true) < 5e-4

    # Parametric fit RMSE tiny.
    assert fit.iv_fit.rmse_iv < 5e-4
    # SSVI butterfly margin positive.
    assert fit.iv_fit.ssvi.butterfly_margin > 0
    # Durrleman g ≥ 0 by construction.
    assert fit.arbitrage.durrleman_min > -1e-6
    # No (or vanishingly few) negative density clips.
    assert fit.arbitrage.n_neg_clipped <= 1
    # ∫q ≈ 1 and E[K] ≈ F.
    assert abs(fit.arbitrage.integral_q - 1.0) < 1e-2
    assert abs(fit.arbitrage.mean_recovery_pct) < 1.0  # %


def test_end_to_end_synthetic_sabr() -> None:
    """SABR path on a true-SABR smile."""
    F_true = 100.0
    T = 0.5
    r_true = 0.04
    sabr = dict(alpha=0.22, beta=1.0, rho=-0.4, nu=0.5)

    from stats.options.sabr import hagan_lognormal_iv

    def iv_fn(K):
        return hagan_lognormal_iv(F_true, np.asarray(K), T, **sabr)

    quotes, spot = _build_synthetic_chain(F_true, T, r_true, iv_fn)
    fit = fit_expiry(
        quotes,
        ticker="SYN",
        expiry="2026-12-31",
        T=T,
        spot=spot,
        r_external=r_true,
        model=VolModel.SABR,
        asset_class=AssetClass.EQUITY,
        n_grid=200,
        gp_samples=100,
    )

    assert abs(fit.F - F_true) / F_true < 1e-3
    assert fit.r == pytest.approx(r_true)
    assert abs(fit.r_implied_raw - r_true) < 5e-4
    assert fit.iv_fit.rmse_iv < 5e-4
    assert math.isclose(fit.iv_fit.sabr.beta, 1.0, abs_tol=1e-12)
    assert abs(fit.arbitrage.integral_q - 1.0) < 1e-2


def test_otm_only_enforced() -> None:
    """ITM quotes are filtered out before parametric calibration.

    The market_quotes DataFrame in the result must contain only OTM
    options: puts strictly below F and calls at or above F.
    """
    F_true = 100.0
    T = 0.5
    r_true = 0.04

    def iv_fn(K):
        return np.full_like(np.asarray(K, dtype=float), 0.20)

    quotes, spot = _build_synthetic_chain(F_true, T, r_true, iv_fn)
    fit = fit_expiry(
        quotes,
        ticker="SYN",
        expiry="2026-12-31",
        T=T,
        spot=spot,
        r_external=r_true,
        model=VolModel.SSVI,
        gp_samples=50,
    )
    mq = fit.market_quotes
    is_call = mq["is_call"].to_numpy(dtype=bool)
    strike = mq["strike"].to_numpy(dtype=float)
    # Calls all at K ≥ F; puts all at K < F.
    assert np.all(strike[is_call] >= fit.F - 1e-9)
    assert np.all(strike[~is_call] < fit.F + 1e-9)


def test_validation_error_for_bad_inputs() -> None:
    """Pipeline entry rejects T <= 0, spot <= 0, and empty quote frames
    with typed ValidationError (→ HTTP 400)."""
    import pandas as pd

    from core.exceptions import ValidationError

    # Empty frame.
    with pytest.raises(ValidationError):
        fit_expiry(
            pd.DataFrame(),
            ticker="X",
            expiry="2027-01-15",
            T=0.5,
            spot=100.0,
            r_external=0.04,
        )
    # Non-positive T.
    F_true, T, r_true = 100.0, 0.5, 0.04
    quotes, _ = _build_synthetic_chain(
        F_true,
        T,
        r_true,
        iv_fn=lambda K: np.full_like(np.asarray(K, dtype=float), 0.2),
    )
    with pytest.raises(ValidationError):
        fit_expiry(
            quotes, ticker="X", expiry="2027-01-15", T=-0.1, spot=100.0,
            r_external=0.04,
        )
    # Non-positive spot.
    with pytest.raises(ValidationError):
        fit_expiry(
            quotes, ticker="X", expiry="2027-01-15", T=0.5, spot=0,
            r_external=0.04,
        )


def test_stale_chain_still_fits() -> None:
    """A synthetic chain with every row marked ``is_stale=True`` flows
    through the pipeline and produces a SurfaceFit with the slice-level
    flag set."""
    F_true = 100.0
    T = 0.5
    r_true = 0.04
    ssvi_params = dict(theta_T=0.04, rho=-0.4, eta=0.5, gamma=0.3)

    def iv_fn(K):
        return ssvi_iv(np.log(np.asarray(K) / F_true), **ssvi_params, T=T)

    quotes, spot = _build_synthetic_chain(F_true, T, r_true, iv_fn)
    quotes = quotes.copy()
    quotes["is_stale"] = True

    fit = fit_expiry(
        quotes,
        ticker="SYN",
        expiry="2026-12-31",
        T=T,
        spot=spot,
        r_external=r_true,
        model=VolModel.SSVI,
        asset_class=AssetClass.EQUITY,
        n_grid=120,
        gp_samples=50,
    )
    assert fit.is_stale is True
    assert fit.stale_fraction == 1.0


def test_insufficient_quotes_raises() -> None:
    """Tiny chains raise rather than silently degrade."""
    quotes = pd.DataFrame(
        {
            "strike": [95.0, 100.0],
            "bid": [4.0, 1.0],
            "ask": [4.5, 1.5],
            "mid": [4.25, 1.25],
            "last": [4.25, 1.25],
            "volume": [50, 50],
            "oi": [50, 50],
            "iv_yahoo": [0.2, 0.2],
            "is_call": [True, True],
            "contract_symbol": ["X0C", "X1C"],
            "spread": [0.5, 0.5],
        }
    )
    with pytest.raises(ValueError):
        fit_expiry(
            quotes,
            ticker="SYN",
            expiry="2026-12-31",
            T=0.5,
            spot=100.0,
            r_external=0.045,
        )
