"""Unit tests for YFinanceProvider.get_option_chain_raw — schema + edge cases."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.yfinance_provider import YFinanceProvider


def _make_calls_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "strike": 95.0,
                "bid": 6.0,
                "ask": 6.4,
                "lastPrice": 6.2,
                "volume": 100,
                "openInterest": 500,
                "impliedVolatility": 0.25,
                "contractSymbol": "SPY250620C00095000",
            },
            {
                "strike": 100.0,
                "bid": 2.0,
                "ask": 2.4,
                "lastPrice": 2.2,
                "volume": 200,
                "openInterest": 800,
                "impliedVolatility": 0.20,
                "contractSymbol": "SPY250620C00100000",
            },
            {
                "strike": 105.0,
                "bid": 0.5,
                "ask": 0.7,
                "lastPrice": 0.6,
                "volume": 50,
                "openInterest": 300,
                "impliedVolatility": 0.22,
                "contractSymbol": "SPY250620C00105000",
            },
        ]
    )


def _make_puts_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "strike": 95.0,
                "bid": 0.4,
                "ask": 0.6,
                "lastPrice": 0.5,
                "volume": 80,
                "openInterest": 250,
                "impliedVolatility": 0.27,
                "contractSymbol": "SPY250620P00095000",
            },
            {
                "strike": 100.0,
                "bid": 1.8,
                "ask": 2.2,
                "lastPrice": 2.0,
                "volume": 150,
                "openInterest": 600,
                "impliedVolatility": 0.20,
                "contractSymbol": "SPY250620P00100000",
            },
            {
                "strike": 105.0,
                "bid": 5.5,
                "ask": 5.9,
                "lastPrice": 5.7,
                "volume": 60,
                "openInterest": 400,
                "impliedVolatility": 0.23,
                "contractSymbol": "SPY250620P00105000",
            },
        ]
    )


@pytest.fixture
def patched_yf():
    """Patch ``yfinance.Ticker`` inside ``data.yfinance_provider``."""
    chain = SimpleNamespace(calls=_make_calls_df(), puts=_make_puts_df())
    mock_ticker = MagicMock()
    mock_ticker.info = {"regularMarketPrice": 100.0}
    mock_ticker.options = ("2026-06-20", "2026-09-18", "2026-12-19")
    mock_ticker.option_chain.return_value = chain
    with patch("data.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        yield mock_ticker


async def test_shape(patched_yf):
    """Returned payload has the expected schema and non-empty calls/puts."""
    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("SPY", expiry="2026-06-20")
    assert res["ticker"] == "SPY"
    assert res["spot"] == 100.0
    assert res["expiry"] == "2026-06-20"
    assert res["expiry_ts"] > 0
    assert len(res["available_expiries"]) == 3
    assert len(res["calls"]) == 3
    assert len(res["puts"]) == 3

    one_call = res["calls"][1]  # K=100 row
    assert set(one_call.keys()) == {
        "strike",
        "bid",
        "ask",
        "mid",
        "last",
        "volume",
        "oi",
        "iv_yahoo",
        "is_call",
        "contract_symbol",
        "is_stale",
    }
    assert one_call["strike"] == 100.0
    assert one_call["bid"] == 2.0
    assert one_call["ask"] == 2.4
    assert one_call["mid"] == pytest.approx(2.2)
    assert one_call["volume"] == 200
    assert one_call["oi"] == 800
    assert one_call["iv_yahoo"] == pytest.approx(0.20)
    assert one_call["is_call"] is True
    assert one_call["contract_symbol"].startswith("SPY")
    assert one_call["is_stale"] is False
    assert res["stale_fraction"] == 0.0


async def test_auto_expiry_selection(patched_yf):
    """Without an expiry arg, the method picks one from the available
    list and populates the chain."""
    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("SPY")
    assert res["expiry"] in res["available_expiries"]
    assert len(res["calls"]) > 0


async def test_bad_ticker_returns_empty():
    """Tickers with no options return a well-formed empty payload, not
    an exception."""
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    mock_ticker.options = ()  # no options listed
    with patch("data.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        prov = YFinanceProvider()
        res = await prov.get_option_chain_raw("NOTREAL")
        assert res["calls"] == []
        assert res["puts"] == []
        assert res["available_expiries"] == []
        assert res["spot"] == 0.0


async def test_sentinel_iv_dropped(patched_yf):
    """Quotes with the SENTINEL IV value drop their iv_yahoo to None
    rather than serving a phantom 2e-5 value."""
    # Inject a sentinel-IV row.
    sentinel_calls = _make_calls_df().copy()
    sentinel_calls.loc[0, "impliedVolatility"] = 1e-6  # below SENTINEL_IV
    chain = SimpleNamespace(calls=sentinel_calls, puts=_make_puts_df())
    patched_yf.option_chain.return_value = chain
    prov = YFinanceProvider()
    # Bust the cache key by using a different expiry param.
    res = await prov.get_option_chain_raw("SPY", expiry="2026-09-18")
    assert res["calls"][0]["iv_yahoo"] is None


async def test_nan_volume_does_not_crash(patched_yf):
    """Regression — the original ``int(row.volume or 0)`` blew up on
    NaN because NaN is truthy. The safe-int helper must coerce
    NaN→0 without raising.

    Uses a distinct ticker per test to dodge the module-level cache.
    """
    import numpy as np

    nan_calls = _make_calls_df().copy()
    nan_calls.loc[1, "volume"] = np.nan
    nan_calls.loc[1, "openInterest"] = np.nan
    chain = SimpleNamespace(calls=nan_calls, puts=_make_puts_df())
    patched_yf.option_chain.return_value = chain
    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("NANVOL", expiry="2026-06-20")
    assert len(res["calls"]) == 3
    assert res["calls"][1]["volume"] == 0
    assert res["calls"][1]["oi"] == 0


async def test_nan_strike_drops_row(patched_yf):
    """Rows with NaN strike are dropped (can't price them) and
    n_dropped_at_parse counts the rejection."""
    import numpy as np

    bad_calls = _make_calls_df().copy()
    bad_calls.loc[0, "strike"] = np.nan
    chain = SimpleNamespace(calls=bad_calls, puts=_make_puts_df())
    patched_yf.option_chain.return_value = chain
    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("NANSTK", expiry="2026-06-20")
    assert len(res["calls"]) == 2
    assert res["n_dropped_at_parse"] >= 1


async def test_crossed_quote_drops_row(patched_yf):
    """A bid > ask quote is malformed; drop and count."""
    bad_calls = _make_calls_df().copy()
    bad_calls.loc[0, "bid"] = 50.0  # ask is 6.4
    chain = SimpleNamespace(calls=bad_calls, puts=_make_puts_df())
    patched_yf.option_chain.return_value = chain
    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("CROSS", expiry="2026-06-20")
    assert all(c["strike"] != 95.0 for c in res["calls"])
    assert res["n_dropped_at_parse"] >= 1


async def test_nan_iv_handled(patched_yf):
    """NaN impliedVolatility shouldn't sneak through the truthy check;
    it must come out as None."""
    import numpy as np

    nan_iv_calls = _make_calls_df().copy()
    nan_iv_calls.loc[0, "impliedVolatility"] = np.nan
    chain = SimpleNamespace(calls=nan_iv_calls, puts=_make_puts_df())
    patched_yf.option_chain.return_value = chain
    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("NANIV", expiry="2026-06-20")
    assert res["calls"][0]["iv_yahoo"] is None


async def test_stale_fallback_uses_lastprice(patched_yf):
    """When bid=ask=0 but lastPrice>0, we substitute the last-traded
    price for the mid and synthesise a small half-spread.

    Off-hours behaviour — every strike falls back to lastPrice → the
    chain is fully stale.
    """
    stale_calls = _make_calls_df().copy()
    stale_calls["bid"] = 0.0
    stale_calls["ask"] = 0.0
    stale_puts = _make_puts_df().copy()
    stale_puts["bid"] = 0.0
    stale_puts["ask"] = 0.0
    chain = SimpleNamespace(calls=stale_calls, puts=stale_puts)
    patched_yf.option_chain.return_value = chain

    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("STALE", expiry="2026-06-20")
    # Every surviving row is stale.
    assert all(c["is_stale"] for c in res["calls"])
    assert all(p["is_stale"] for p in res["puts"])
    assert res["stale_fraction"] == pytest.approx(1.0)

    # mid == lastPrice for every row.
    for c, src in zip(res["calls"], stale_calls.itertuples(index=False), strict=True):
        assert c["mid"] == pytest.approx(float(src.lastPrice))
        # half-spread floor + scaling.
        expected_half = max(0.01, 0.02 * float(src.lastPrice))
        assert c["ask"] - c["bid"] == pytest.approx(2 * expected_half)


async def test_stale_fallback_drops_no_last(patched_yf):
    """If bid=ask=0 AND lastPrice is also missing, the row is dropped
    rather than serving a phantom record."""
    import numpy as np

    junk_calls = _make_calls_df().copy()
    junk_calls.loc[0, "bid"] = 0.0
    junk_calls.loc[0, "ask"] = 0.0
    junk_calls.loc[0, "lastPrice"] = np.nan
    chain = SimpleNamespace(calls=junk_calls, puts=_make_puts_df())
    patched_yf.option_chain.return_value = chain

    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("NOLAST", expiry="2026-06-20")
    # First call (the corrupt row) is gone; the other two survive.
    assert len(res["calls"]) == 2
    assert all(c["strike"] != 95.0 for c in res["calls"])
    assert res["n_dropped_at_parse"] >= 1


async def test_stale_fraction_reported(patched_yf):
    """Mixed live + stale chain → stale_fraction ≈ 0.5."""
    mixed_calls = _make_calls_df().copy()
    # Half of calls go stale (bid=ask=0, keep lastPrice).
    mixed_calls.loc[0, "bid"] = 0.0
    mixed_calls.loc[0, "ask"] = 0.0
    mixed_calls.loc[1, "bid"] = 0.0
    mixed_calls.loc[1, "ask"] = 0.0
    # 2 of 3 puts are stale.
    mixed_puts = _make_puts_df().copy()
    mixed_puts.loc[0, "bid"] = 0.0
    mixed_puts.loc[0, "ask"] = 0.0
    mixed_puts.loc[1, "bid"] = 0.0
    mixed_puts.loc[1, "ask"] = 0.0

    chain = SimpleNamespace(calls=mixed_calls, puts=mixed_puts)
    patched_yf.option_chain.return_value = chain

    prov = YFinanceProvider()
    res = await prov.get_option_chain_raw("MIXED", expiry="2026-06-20")
    # 4 of 6 rows are stale.
    assert res["stale_fraction"] == pytest.approx(4 / 6)
