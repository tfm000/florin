"""
Unit tests for :class:`OptionSurfaceService`.

The service is the orchestration layer between
:func:`stats.options.pipeline.fit_expiry` and the FastAPI routes.
We mock the yfinance provider so we can drive any chain shape we
want; the real pipeline runs end-to-end on the resulting data.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock

import numpy as np
import pytest

from dashboard.services.option_surface import (
    _FALLBACK_RATE,
    _FALLBACK_SOURCE,
    OptionSurfaceService,
)
from stats.options.pricing import bs76_call, bs76_put
from stats.options.types import VolModel

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _build_chain(
    F: float = 100.0,
    T_years: float = 0.5,
    r: float = 0.04,
    sigma: float = 0.22,
    n_strikes: int = 21,
    spot: float = 100.0,
) -> dict:
    """Build a synthetic raw-chain payload that obeys parity exactly."""
    D = math.exp(-r * T_years)
    K = np.linspace(0.7 * F, 1.3 * F, n_strikes)
    call_mid = bs76_call(F, K, T_years, sigma, D)
    put_mid = bs76_put(F, K, T_years, sigma, D)
    spread = 0.05
    calls = [
        {
            "strike": float(K[i]),
            "bid": float(call_mid[i] - spread / 2),
            "ask": float(call_mid[i] + spread / 2),
            "mid": float(call_mid[i]),
            "last": float(call_mid[i]),
            "volume": 500,
            "oi": 500,
            "iv_yahoo": sigma,
            "is_call": True,
            "contract_symbol": f"SYN{i}C",
        }
        for i in range(n_strikes)
    ]
    puts = [
        {
            "strike": float(K[i]),
            "bid": float(put_mid[i] - spread / 2),
            "ask": float(put_mid[i] + spread / 2),
            "mid": float(put_mid[i]),
            "last": float(put_mid[i]),
            "volume": 500,
            "oi": 500,
            "iv_yahoo": sigma,
            "is_call": False,
            "contract_symbol": f"SYN{i}P",
        }
        for i in range(n_strikes)
    ]
    import time

    return {
        "ticker": "SYN",
        "spot": spot,
        "expiry": "2027-01-15",
        "expiry_ts": time.time() + T_years * 365.25 * 86400,
        "available_expiries": ["2027-01-15", "2027-04-16"],
        "calls": calls,
        "puts": puts,
        "n_dropped_at_parse": 0,
    }


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Provider that always returns the same well-formed chain."""
    prov = AsyncMock()
    prov.get_option_chain_raw.return_value = _build_chain()
    return prov


# ----------------------------------------------------------------------
# Risk-free rate resolver
# ----------------------------------------------------------------------


async def test_resolve_rfr_uses_fetcher_when_present() -> None:
    """``_resolve_rfr`` converts the fetcher's percent value to a decimal."""
    rf = AsyncMock()
    rf.get_current_rate.return_value = (4.31, "SOFR / Fed")
    svc = OptionSurfaceService(yf_provider=AsyncMock(), rf_fetcher=rf)
    rate, source = await svc._resolve_rfr("USD")
    assert rate == pytest.approx(0.0431)
    assert source == "SOFR / Fed"


async def test_resolve_rfr_falls_back_without_fetcher() -> None:
    """No fetcher → constant fallback, with the fallback label."""
    svc = OptionSurfaceService(yf_provider=AsyncMock(), rf_fetcher=None)
    rate, source = await svc._resolve_rfr("USD")
    assert rate == pytest.approx(_FALLBACK_RATE)
    assert source == _FALLBACK_SOURCE


async def test_resolve_rfr_falls_back_on_error() -> None:
    """Fetcher raises → fall back without raising upward."""
    rf = AsyncMock()
    rf.get_current_rate.side_effect = OSError("BIS API unreachable")
    svc = OptionSurfaceService(yf_provider=AsyncMock(), rf_fetcher=rf)
    rate, source = await svc._resolve_rfr("USD")
    assert rate == pytest.approx(_FALLBACK_RATE)
    assert source == _FALLBACK_SOURCE


# ----------------------------------------------------------------------
# Caching
# ----------------------------------------------------------------------


async def test_single_cache_hit(mock_provider: AsyncMock) -> None:
    """Second call within TTL hits the cache and skips the pipeline."""
    svc = OptionSurfaceService(yf_provider=mock_provider)
    fit_a = await svc.get_single_expiry_fit("SYN")
    fit_b = await svc.get_single_expiry_fit("SYN")
    assert fit_a is fit_b  # identity == cache hit
    assert mock_provider.get_option_chain_raw.call_count == 1


async def test_surface_r_equals_sofr(mock_provider: AsyncMock) -> None:
    """``SurfaceFit.r`` is always the externally-resolved SOFR rate —
    the pipeline no longer extracts a rate from the chain.

    The diagnostic ``r_implied_raw`` still holds the chain-implied
    value (for a clean synthetic chain it'll be close to the truth,
    but the production guarantee is only that it's preserved, not
    that it's accurate)."""
    rf = AsyncMock()
    rf.get_current_rate.return_value = (4.31, "SOFR / Fed")
    svc = OptionSurfaceService(yf_provider=mock_provider, rf_fetcher=rf)
    fit = await svc.get_single_expiry_fit("SYN")
    assert fit.r == pytest.approx(0.0431)
    # r_implied_raw is populated even on the clean chain — quants can
    # see how far the chain drifts from the true rate.
    assert math.isfinite(fit.r_implied_raw)


async def test_cache_keyed_on_rate_bucket(mock_provider: AsyncMock) -> None:
    """An overnight SOFR refresh invalidates the previous day's fits.

    Two service calls with different SOFR rates must produce two
    *distinct* cached fits — otherwise a stale Greeks panel could
    survive a Fed rate-change announcement."""
    rf_a = AsyncMock()
    rf_a.get_current_rate.return_value = (4.31, "SOFR / Fed")
    svc_a = OptionSurfaceService(yf_provider=mock_provider, rf_fetcher=rf_a)
    fit_a = await svc_a.get_single_expiry_fit("SYN")
    assert fit_a.r == pytest.approx(0.0431)

    rf_b = AsyncMock()
    rf_b.get_current_rate.return_value = (4.56, "SOFR / Fed")
    svc_b = OptionSurfaceService(yf_provider=mock_provider, rf_fetcher=rf_b)
    fit_b = await svc_b.get_single_expiry_fit("SYN")
    assert fit_b.r == pytest.approx(0.0456)
    # Different objects (cache miss on the rate bucket); each fit
    # carries the rate it was priced against.
    assert fit_a is not fit_b


async def test_auto_and_explicit_same_expiry_share_fit(
    mock_provider: AsyncMock,
) -> None:
    """Regression: ``get_single_expiry_fit(ticker)`` (auto) and
    ``get_single_expiry_fit(ticker, expiry=X)`` where ``X`` is the
    resolved expiry **must return the same SurfaceFit object** —
    otherwise the chart visibly jumps when the user clicks their own
    auto-selected date in the expiry dropdown.

    The bug we're guarding against: each path was caching under a
    different key (``auto`` vs ``X``) and re-fetching yfinance
    separately, producing fits against different live-bid snapshots.
    """
    svc = OptionSurfaceService(yf_provider=mock_provider)
    fit_auto = await svc.get_single_expiry_fit("SYN")
    fit_explicit = await svc.get_single_expiry_fit(
        "SYN", expiry=fit_auto.expiry
    )
    # Same Python object: cross-cache hit, not a recomputed fit.
    assert fit_auto is fit_explicit
    # And the chain provider was hit exactly once across both calls
    # (the auto call). The explicit call resolved through the
    # service-level cross-cache.
    assert mock_provider.get_option_chain_raw.call_count == 1

    # Reverse order: explicit first, then auto. The auto call must
    # also reuse the explicit fit rather than recompute.
    svc2 = OptionSurfaceService(yf_provider=mock_provider)
    mock_provider.reset_mock()
    fit_explicit_first = await svc2.get_single_expiry_fit(
        "SYN", expiry="2027-01-15"
    )
    fit_auto_second = await svc2.get_single_expiry_fit("SYN")
    assert fit_auto_second is fit_explicit_first


async def test_single_cache_key_per_model(mock_provider: AsyncMock) -> None:
    """Different model → different cache entry → two pipeline runs."""
    svc = OptionSurfaceService(yf_provider=mock_provider)
    fit_ssvi = await svc.get_single_expiry_fit("SYN", model=VolModel.SSVI)
    fit_sabr = await svc.get_single_expiry_fit("SYN", model=VolModel.SABR)
    assert fit_ssvi is not fit_sabr
    assert fit_ssvi.model == VolModel.SSVI
    assert fit_sabr.model == VolModel.SABR


async def test_single_cache_ttl_expiry(
    mock_provider: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After cache_ttl elapses, the next call re-fetches."""
    fake_now = [1_000.0]
    monkeypatch.setattr(
        "dashboard.services.option_surface.time.time", lambda: fake_now[0]
    )
    svc = OptionSurfaceService(yf_provider=mock_provider, cache_ttl=60)
    await svc.get_single_expiry_fit("SYN")
    assert mock_provider.get_option_chain_raw.call_count == 1
    fake_now[0] += 30
    await svc.get_single_expiry_fit("SYN")
    assert mock_provider.get_option_chain_raw.call_count == 1  # still cached
    fake_now[0] += 60
    await svc.get_single_expiry_fit("SYN")
    assert mock_provider.get_option_chain_raw.call_count == 2  # refetched


async def test_cache_eviction_above_capacity(mock_provider: AsyncMock) -> None:
    """Cache evicts the oldest entry once capacity (100) is exceeded.

    Insert 105 entries directly so we don't have to fan out 105 real
    pipeline runs; eviction is implemented on _cache_set.
    """
    svc = OptionSurfaceService(yf_provider=mock_provider)
    for i in range(105):
        svc._cache_set(("key", i), {"payload": i})
    assert len(svc._cache) <= 100


# ----------------------------------------------------------------------
# Multi-expiry fan-out
# ----------------------------------------------------------------------


async def test_multi_fanout_partial_failures() -> None:
    """Some expiries succeed, some raise — assemble only the successes
    and emit a warning for each failure (the warning shape is a logging
    side-effect; here we just assert the response shape)."""
    good_chain = _build_chain()
    # Provider returns the good chain only for the first expiry; raises
    # on the second.

    async def fake_get(ticker: str, expiry: str | None = None) -> dict:
        if expiry is None or expiry == "2027-01-15":
            return good_chain
        # Simulate yfinance returning an empty payload for the second.
        return {
            "ticker": ticker,
            "spot": 0.0,
            "expiry": "",
            "expiry_ts": 0.0,
            "available_expiries": [],
            "calls": [],
            "puts": [],
            "n_dropped_at_parse": 0,
        }

    prov = AsyncMock()
    prov.get_option_chain_raw.side_effect = fake_get
    svc = OptionSurfaceService(yf_provider=prov)
    payload = await svc.get_multi_expiry_fit("SYN", n_expiries=2, n_grid=50)
    # Only the first expiry made it.
    assert len(payload["expiries"]) == 1
    assert payload["expiries"][0] == "2027-01-15"
    assert len(payload["iv_surface"]) == 1


async def test_multi_all_failures_raises() -> None:
    """If every expiry fails, the service raises so the caller sees a
    typed 404 (rather than an empty payload)."""
    prov = AsyncMock()
    prov.get_option_chain_raw.return_value = {
        "ticker": "EMPTY",
        "spot": 0.0,
        "expiry": "",
        "expiry_ts": 0.0,
        "available_expiries": ["2099-01-01"],
        "calls": [],
        "puts": [],
        "n_dropped_at_parse": 0,
    }
    svc = OptionSurfaceService(yf_provider=prov)
    with pytest.raises(ValueError, match="All per-expiry fits failed"):
        await svc.get_multi_expiry_fit("EMPTY", n_expiries=1, n_grid=50)


# ----------------------------------------------------------------------
# Spread curve
# ----------------------------------------------------------------------


async def test_spread_curve_drops_nan_iv() -> None:
    """A chain with iv_yahoo=None on every row yields an empty spread
    curve, not a crash."""
    chain = _build_chain()
    for c in chain["calls"]:
        c["iv_yahoo"] = None
    for p in chain["puts"]:
        p["iv_yahoo"] = None
    prov = AsyncMock()
    prov.get_option_chain_raw.return_value = chain
    svc = OptionSurfaceService(yf_provider=prov)
    res = await svc.get_spread_curve("SYN", n_expiries=2)
    assert res["spread_curve"] == []


async def test_spread_curve_populated(mock_provider: AsyncMock) -> None:
    """Normal chain → spread_curve has at least one row with put_iv,
    call_iv, spread = put − call."""
    svc = OptionSurfaceService(yf_provider=mock_provider)
    res = await svc.get_spread_curve("SYN", n_expiries=2)
    assert len(res["spread_curve"]) >= 1
    row = res["spread_curve"][0]
    assert math.isclose(row["spread"], row["put_iv"] - row["call_iv"], abs_tol=1e-12)
