"""
Live integration smoke test for the options pipeline.

Hits real yfinance, fits SPY end-to-end via :class:`OptionSurfaceService`,
asserts every CLAUDE.md §4 sanity gate. Marked ``integration`` so it's
excluded from the default pytest run; opt-in via::

    pytest tests/test_options_smoke.py -m integration

This is the catch-net for production-shape bugs that synthetic chains
can't surface (yfinance schema drift, NaN columns, expiry-day chains
with zero bids, etc.). Re-run after any change to
``data/yfinance_provider.py`` or ``stats/options/`` before declaring a
release ready.

**Reliability:** yfinance is only useful during US market hours. After
close (and on weekends) the chain returns stale prices with no live
bids; the cleaning filter then drops 100 % of rows. The tests below
detect this and ``pytest.skip()`` with a clear message — that's a
diagnosis of the environment, not a test failure.

Always-on regression coverage for the NaN-bug class lives in
``tests/test_yfinance_chain_raw.py`` (no integration mark) and doesn't
depend on market hours.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from dashboard.services.option_surface import OptionSurfaceService
from data.yfinance_provider import YFinanceProvider
from stats.options.types import VolModel

_MIN_DTE_DAYS = 7  # avoid near-zero-DTE chains where RMSE / mass loss are huge


async def _pick_liquid_expiry(provider: YFinanceProvider) -> str | None:
    """Return the first SPY expiry ≥ _MIN_DTE_DAYS days out, or ``None``
    if none exists (chain too short — caller should skip).

    The pipeline's default auto-select prefers the most-quoted expiry,
    which during market hours is *today* — but ~6-hour-to-expiry
    chains have wild IV in the wings and the trapezoidal RND integral
    loses substantial mass. A 7-DTE floor keeps the smoke test in a
    regime where the math is well-conditioned without sacrificing
    end-to-end coverage.
    """
    raw = await provider.get_option_chain_raw("SPY")
    now = datetime.now(UTC)
    for exp in raw.get("available_expiries", []):
        exp_dt = datetime.fromisoformat(exp).replace(tzinfo=UTC)
        dte_days = (exp_dt - now).days
        if dte_days >= _MIN_DTE_DAYS:
            return exp
    return None


_LIQUIDITY_SKIP_PATTERNS = (
    "filtered out",
    "Need >=",
    "No OTM quotes survived",
    "Insufficient OTM IVs",
)


def _skip_if_offhours(exc: Exception) -> None:
    """Translate the cleaning-filter failures into a clear skip when
    the market is closed (no live bids → empty filtered chain)."""
    msg = str(exc)
    if any(p in msg for p in _LIQUIDITY_SKIP_PATTERNS):
        pytest.skip(
            f"yfinance returned insufficient live liquidity (market "
            f"likely closed). Re-run during US trading hours. Cause: {msg}"
        )
    raise exc


@pytest.mark.integration
async def test_spy_end_to_end_ssvi_live() -> None:
    """Full SSVI pipeline against the live yfinance SPY chain."""
    provider = YFinanceProvider()
    svc = OptionSurfaceService(yf_provider=provider)
    expiry = await _pick_liquid_expiry(provider)
    if expiry is None:
        pytest.skip("No SPY expiry ≥ 7 DTE in the available list.")
    try:
        fit = await svc.get_single_expiry_fit("SPY", expiry=expiry, model=VolModel.SSVI)
    except ValueError as e:
        _skip_if_offhours(e)
        return  # unreachable — _skip_if_offhours raises

    # Shape and trace.
    assert fit.ticker == "SPY"
    assert fit.spot > 0
    assert fit.F > 0
    assert fit.T > 0
    assert len(fit.market_quotes) >= 6
    assert len(fit.rnd_band.K_grid) > 0

    # Loose gates — the smoke test's job is to surface crashes, NaN
    # propagation, and yfinance schema drift; not to enforce tight
    # numerical correctness on live data (yfinance returns wobbly
    # snapshots that can shift between calls within seconds, and the
    # default 0.5F–1.5F K-grid loses substantial mass on short DTEs).
    # The synthetic-chain unit tests in test_options_pipeline.py +
    # test_options_rnd.py check the strict mathematical gates on
    # controlled inputs.
    assert fit.parity.n_strikes >= 3
    assert fit.iv_fit.ssvi is not None
    assert np.isfinite(fit.iv_fit.rmse_iv)
    assert np.isfinite(fit.iv_fit.ssvi.butterfly_margin)
    assert fit.rnd_band.n_samples > 0
    # Density must be non-negative *after* clip+renormalise — this is
    # the only invariant the per-sample clip step guarantees.
    assert np.all(fit.rnd_band.density_median >= -1e-12)
    # Diagnostics must be finite (no NaN-poisoning anywhere in the chain).
    assert np.isfinite(fit.arbitrage.integral_q)
    assert np.isfinite(fit.arbitrage.mean_recovery_pct)
    assert np.isfinite(fit.arbitrage.durrleman_min)


@pytest.mark.integration
async def test_spy_end_to_end_sabr_live() -> None:
    """Same pipeline against SABR, exercising the toggle path."""
    provider = YFinanceProvider()
    svc = OptionSurfaceService(yf_provider=provider)
    expiry = await _pick_liquid_expiry(provider)
    if expiry is None:
        pytest.skip("No SPY expiry ≥ 7 DTE in the available list.")
    try:
        fit = await svc.get_single_expiry_fit("SPY", expiry=expiry, model=VolModel.SABR)
    except ValueError as e:
        _skip_if_offhours(e)
        return

    assert fit.iv_fit.sabr is not None
    assert fit.iv_fit.sabr.beta == 1.0  # equity asset class
    assert np.isfinite(fit.iv_fit.rmse_iv)
    assert np.isfinite(fit.arbitrage.integral_q)
    assert np.isfinite(fit.arbitrage.mean_recovery_pct)
    assert np.all(fit.rnd_band.density_median >= -1e-12)
