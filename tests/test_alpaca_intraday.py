"""Regression tests for AlpacaProvider.get_intraday_bars.

Covers the bad-ticker-in-batch bug where a single invalid symbol (e.g. MLB1)
caused Alpaca to return HTTP 400 for the entire batch.  The previous code
called raise_for_status() before reading the response body and then swallowed
the exception, returning {} silently.

Root cause confirmed live: Alpaca responds with
    {"message": "invalid symbol: MLB1"}
when any symbol in a batch contains digits, slashes, or other characters not
matching the pattern ``^[A-Z]+(\\.[A-Z]+)?$``.

Fix:
  1. Pre-filter symbols via _is_valid_alpaca_ticker() before issuing any request.
  2. Emit a WARNING for each dropped symbol (no silent failure).
  3. Split valid symbols into chunks of at most INTRADAY_BATCH_SIZE so a
     per-chunk HTTP error does not silently discard other chunks.
  4. Per-chunk HTTP errors are logged at ERROR level (not swallowed).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from config.settings import AlpacaFeed, Settings
from data.alpaca_provider import (
    INTRADAY_BATCH_SIZE,
    AlpacaProvider,
    _is_valid_alpaca_ticker,
)

# Canonical URL used in mock requests
_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_settings() -> Settings:
    return Settings(
        alpaca_api_key="test-key",
        alpaca_api_secret="test-secret",
        alpaca_feed=AlpacaFeed.IEX,
    )


def _alpaca_response(bars_by_ticker: dict[str, list[dict]], status: int = 200) -> httpx.Response:
    """Build a fake httpx.Response as Alpaca would return for a bars request.

    A real httpx.Request is attached so that raise_for_status() works correctly.
    """
    req = httpx.Request("GET", _BARS_URL)
    payload: dict[str, Any] = {"bars": bars_by_ticker, "next_page_token": None}
    return httpx.Response(
        status,
        json=payload,
        headers={"content-type": "application/json"},
        request=req,
    )


def _alpaca_error_response(message: str, status: int = 400) -> httpx.Response:
    req = httpx.Request("GET", _BARS_URL)
    return httpx.Response(
        status,
        json={"message": message},
        headers={"content-type": "application/json"},
        request=req,
    )


def _raw_bar(
    ts: str = "2026-05-27T13:30:00Z",
    o: float = 100.0,
    h: float = 101.0,
    low: float = 99.0,
    c: float = 100.5,
    v: int = 1000,
) -> dict:
    """Minimal Alpaca bar dict as returned by /v2/stocks/bars."""
    return {"t": ts, "o": o, "h": h, "l": low, "c": c, "v": v, "n": 10, "vw": 100.3}


def _make_provider() -> AlpacaProvider:
    """Create an AlpacaProvider with a mock HTTP client attached.

    The _http attribute is set to an AsyncMock so tests can configure
    provider._http.get without making real network calls.
    """
    settings = _make_settings()
    provider = AlpacaProvider(settings)
    provider._http = AsyncMock()  # type: ignore[assignment]
    return provider


# ---------------------------------------------------------------------------
# _is_valid_alpaca_ticker unit tests
# ---------------------------------------------------------------------------


class TestIsValidAlpacaTicker:
    """Unit tests for the symbol pre-filter function."""

    def test_plain_alpha_accepted(self):
        assert _is_valid_alpaca_ticker("AAPL") is True

    def test_single_letter_accepted(self):
        assert _is_valid_alpaca_ticker("A") is True

    def test_dot_class_notation_accepted(self):
        # BRK.A / BRK.B style symbols are valid Alpaca equity tickers
        assert _is_valid_alpaca_ticker("BRK.A") is True
        assert _is_valid_alpaca_ticker("BRK.B") is True

    def test_digit_suffix_rejected(self):
        # This is the exact pattern that triggered the production bug.
        # MLB1 appeared in the TIGER GLOBAL MANAGEMENT LLC 13F portfolio.
        assert _is_valid_alpaca_ticker("MLB1") is False
        assert _is_valid_alpaca_ticker("AAPL1") is False
        assert _is_valid_alpaca_ticker("A1") is False

    def test_digit_prefix_rejected(self):
        assert _is_valid_alpaca_ticker("1AAPL") is False

    def test_all_digits_rejected(self):
        assert _is_valid_alpaca_ticker("123") is False

    def test_slash_rejected(self):
        assert _is_valid_alpaca_ticker("BRK/B") is False

    def test_dash_rejected(self):
        assert _is_valid_alpaca_ticker("MSFT-") is False
        assert _is_valid_alpaca_ticker("CIG-C") is False

    def test_empty_string_rejected(self):
        assert _is_valid_alpaca_ticker("") is False

    def test_lowercase_rejected(self):
        # Alpaca symbols must be uppercase-only
        assert _is_valid_alpaca_ticker("aapl") is False
        assert _is_valid_alpaca_ticker("Aapl") is False

    def test_multiple_dots_rejected(self):
        assert _is_valid_alpaca_ticker("A.B.C") is False

    def test_dot_only_rejected(self):
        assert _is_valid_alpaca_ticker(".") is False

    def test_leading_dot_rejected(self):
        assert _is_valid_alpaca_ticker(".AAPL") is False

    def test_trailing_dot_rejected(self):
        assert _is_valid_alpaca_ticker("AAPL.") is False


# ---------------------------------------------------------------------------
# get_intraday_bars integration tests (mocked httpx client)
# ---------------------------------------------------------------------------


class TestGetIntradayBarsFiltering:
    """Tests that invalid tickers are dropped before the HTTP request is made."""

    @pytest.mark.asyncio
    async def test_bad_ticker_dropped_good_bars_returned(self, caplog: pytest.LogCaptureFixture):
        """MLB1 must be dropped with a WARNING; AAPL bars must still be returned.

        This is the direct regression test for the production bug: the 13F
        portfolio contained MLB1 which caused Alpaca to 400 the whole batch.
        """
        provider = _make_provider()
        provider._http.get = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_alpaca_response({"AAPL": [_raw_bar()]})
        )

        with caplog.at_level(logging.WARNING, logger="data.alpaca_provider"):
            result = await provider.get_intraday_bars(
                ["AAPL", "MLB1"],
                timeframe="5Min",
                start="2026-05-27T09:30:00-04:00",
            )

        # Good ticker's bars must be returned
        assert "AAPL" in result
        assert len(result["AAPL"]) == 1
        assert result["AAPL"][0]["close"] == 100.5

        # Invalid ticker must be absent from result
        assert "MLB1" not in result

        # Warning must be surfaced (rule-1: no silent failure)
        warning_text = " ".join(caplog.messages)
        assert "MLB1" in warning_text

    @pytest.mark.asyncio
    async def test_mlb1_not_included_in_request(self, caplog: pytest.LogCaptureFixture):
        """Verify MLB1 is filtered out BEFORE the HTTP request is issued.

        Captures the actual 'symbols' parameter sent to Alpaca and asserts
        that MLB1 is absent from it.
        """
        provider = _make_provider()
        captured_params: dict[str, Any] = {}

        async def fake_get(url: str, params: dict | None = None, **kwargs: Any) -> httpx.Response:
            captured_params["params"] = params or {}
            return _alpaca_response(
                {
                    "MSFT": [_raw_bar()],
                    "NVDA": [_raw_bar()],
                }
            )

        provider._http.get = fake_get  # type: ignore[union-attr, method-assign]

        with caplog.at_level(logging.WARNING, logger="data.alpaca_provider"):
            result = await provider.get_intraday_bars(
                ["MSFT", "MLB1", "NVDA"],
                timeframe="5Min",
                start="2026-05-27T09:30:00-04:00",
            )

        # MLB1 must NOT appear in the symbols= parameter sent to Alpaca
        sent_symbols = captured_params["params"].get("symbols", "")
        assert "MLB1" not in sent_symbols, (
            f"MLB1 should have been filtered before the HTTP request; got symbols={sent_symbols!r}"
        )
        assert "MSFT" in sent_symbols
        assert "NVDA" in sent_symbols

        # Good tickers still in result
        assert "MSFT" in result
        assert "NVDA" in result
        assert "MLB1" not in result

        # Warning surfaced
        assert "MLB1" in " ".join(caplog.messages)

    @pytest.mark.asyncio
    async def test_all_invalid_tickers_returns_empty_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When every symbol is invalid the function must return {} and warn.

        No HTTP call must be made.
        """
        provider = _make_provider()
        provider._http.get = AsyncMock()  # type: ignore[union-attr, method-assign] # should not be called

        with caplog.at_level(logging.WARNING, logger="data.alpaca_provider"):
            result = await provider.get_intraday_bars(
                ["MLB1", "ABC1", "XYZ/2"],
                timeframe="5Min",
                start="2026-05-27T09:30:00-04:00",
            )

        assert result == {}

        # No HTTP call must be made when all tickers are invalid
        provider._http.get.assert_not_called()  # type: ignore[union-attr]

        # At least one warning must mention the invalid symbols
        warning_text = " ".join(caplog.messages)
        assert "MLB1" in warning_text or "ABC1" in warning_text

    @pytest.mark.asyncio
    async def test_empty_ticker_list_returns_empty_no_request(self):
        """Empty input must return {} without making any HTTP call."""
        provider = _make_provider()
        provider._http.get = AsyncMock()  # type: ignore[union-attr, method-assign]

        result = await provider.get_intraday_bars(
            [],
            timeframe="5Min",
            start="2026-05-27T09:30:00-04:00",
        )

        assert result == {}
        provider._http.get.assert_not_called()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_dot_notation_tickers_not_dropped(self):
        """BRK.B is a valid Alpaca equity symbol and must not be filtered out."""
        provider = _make_provider()
        provider._http.get = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_alpaca_response({"BRK.B": [_raw_bar()]})
        )

        result = await provider.get_intraday_bars(
            ["BRK.B"],
            timeframe="5Min",
            start="2026-05-27T09:30:00-04:00",
        )

        assert "BRK.B" in result
        assert len(result["BRK.B"]) == 1
        provider._http.get.assert_called_once()  # type: ignore[union-attr]


class TestGetIntradayBarsChunking:
    """Tests that the validated ticker list is split into INTRADAY_BATCH_SIZE chunks."""

    @pytest.mark.asyncio
    async def test_large_batch_issues_multiple_requests(self):
        """A batch larger than INTRADAY_BATCH_SIZE must produce multiple HTTP requests."""
        extra = 5
        # Build INTRADAY_BATCH_SIZE + extra valid uppercase-only tickers
        tickers: list[str] = []
        for i in range(INTRADAY_BATCH_SIZE + extra):
            a = chr(65 + (i % 26))
            b = chr(65 + ((i // 26) % 26))
            c = chr(65 + ((i // 676) % 26))
            tickers.append(f"{c}{b}{a}")
        tickers = list(dict.fromkeys(tickers))[: INTRADAY_BATCH_SIZE + extra]

        call_count = 0

        async def fake_get(url: str, params: dict | None = None, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            syms = (params or {}).get("symbols", "").split(",")
            bars = {s: [_raw_bar()] for s in syms if s}
            return _alpaca_response(bars)

        provider = _make_provider()
        provider._http.get = fake_get  # type: ignore[union-attr, method-assign]

        result = await provider.get_intraday_bars(
            tickers,
            timeframe="5Min",
            start="2026-05-27T09:30:00-04:00",
        )

        assert call_count == 2, (
            f"Expected 2 HTTP requests for {len(tickers)} tickers "
            f"(chunk size {INTRADAY_BATCH_SIZE}), got {call_count}"
        )
        assert len(result) == len(tickers)

    @pytest.mark.asyncio
    async def test_chunk_http_error_logged_not_swallowed(self, caplog: pytest.LogCaptureFixture):
        """An HTTP 500 error on one chunk must be logged at ERROR level.

        The successful chunk's bars must still be returned — the error must NOT
        be swallowed and returned as {} for the whole result.
        """
        extra = 3
        tickers: list[str] = []
        for i in range(INTRADAY_BATCH_SIZE + extra):
            a = chr(65 + (i % 26))
            b = chr(65 + ((i // 26) % 26))
            c = chr(65 + ((i // 676) % 26))
            tickers.append(f"{c}{b}{a}")
        tickers = list(dict.fromkeys(tickers))[: INTRADAY_BATCH_SIZE + extra]

        chunk1 = tickers[:INTRADAY_BATCH_SIZE]
        chunk2 = tickers[INTRADAY_BATCH_SIZE:]

        call_count = 0

        async def fake_get(url: str, params: dict | None = None, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            syms = (params or {}).get("symbols", "").split(",")

            if call_count == 1:
                # First chunk succeeds
                bars = {s: [_raw_bar()] for s in syms if s}
                return _alpaca_response(bars)
            else:
                # Second chunk fails with HTTP 500
                error_resp = _alpaca_error_response("internal error", status=500)
                raise httpx.HTTPStatusError(
                    "500 Internal Server Error",
                    request=httpx.Request("GET", _BARS_URL),
                    response=error_resp,
                )

        provider = _make_provider()
        provider._http.get = fake_get  # type: ignore[union-attr, method-assign]

        with caplog.at_level(logging.ERROR, logger="data.alpaca_provider"):
            result = await provider.get_intraday_bars(
                tickers,
                timeframe="5Min",
                start="2026-05-27T09:30:00-04:00",
            )

        # Chunk 1 results must be present despite chunk 2 failure
        for t in chunk1:
            assert t in result, f"{t} from successful chunk 1 should be in result"

        # Chunk 2 bars absent (request failed)
        for t in chunk2:
            assert t not in result

        # Error must be surfaced in logs (not silently swallowed)
        log_text = " ".join(caplog.messages)
        assert log_text.strip(), "Expected at least one ERROR log entry for the failed chunk"


class TestGetIntradayBarsBarMapping:
    """Tests that Alpaca bar fields are mapped to the expected output dict keys."""

    @pytest.mark.asyncio
    async def test_bar_fields_mapped_correctly(self):
        """Each bar dict must have timestamp, open, high, low, close, volume."""
        provider = _make_provider()
        provider._http.get = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_alpaca_response(
                {
                    "TSLA": [
                        {
                            "t": "2026-05-27T13:30:00Z",
                            "o": 200.0,
                            "h": 205.0,
                            "l": 198.0,
                            "c": 203.0,
                            "v": 5000,
                            "n": 50,
                            "vw": 201.5,
                        }
                    ]
                }
            )
        )

        result = await provider.get_intraday_bars(
            ["TSLA"],
            timeframe="5Min",
            start="2026-05-27T09:30:00-04:00",
        )

        assert "TSLA" in result
        bar = result["TSLA"][0]
        assert bar["timestamp"] == "2026-05-27T13:30:00Z"
        assert bar["open"] == 200.0
        assert bar["high"] == 205.0
        assert bar["low"] == 198.0
        assert bar["close"] == 203.0
        assert bar["volume"] == 5000

    @pytest.mark.asyncio
    async def test_multiple_bars_per_ticker(self):
        """All bars for a ticker must be returned, not just the first."""
        provider = _make_provider()
        bars = [
            _raw_bar(ts="2026-05-27T13:30:00Z", c=100.0),
            _raw_bar(ts="2026-05-27T13:35:00Z", c=101.0),
            _raw_bar(ts="2026-05-27T13:40:00Z", c=102.0),
        ]
        provider._http.get = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_alpaca_response({"AAPL": bars})
        )

        result = await provider.get_intraday_bars(
            ["AAPL"],
            timeframe="5Min",
            start="2026-05-27T09:30:00-04:00",
        )

        assert len(result["AAPL"]) == 3
        assert result["AAPL"][0]["close"] == 100.0
        assert result["AAPL"][1]["close"] == 101.0
        assert result["AAPL"][2]["close"] == 102.0
