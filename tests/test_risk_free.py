"""Tests for stats.risk_free — G10 central bank rate fetcher."""

import pytest

from stats.risk_free import (
    RateObservation,
    RiskFreeRateFetcher,
    _parse_boe_date,
    _parse_rba_date,
    _normalize_date,
    BENCHMARKS,
    _DAY_COUNT_BASIS,
)


class TestNormalizeDate:
    def test_iso_date(self):
        assert _normalize_date("2025-03-21") == "2025-03-21"

    def test_datetime_with_timezone(self):
        """yfinance returns dates like '2025-03-21 00:00:00-04:00'."""
        assert _normalize_date("2025-03-21 00:00:00-04:00") == "2025-03-21"

    def test_datetime_utc(self):
        assert _normalize_date("2025-03-21T14:30:00Z") == "2025-03-21"

    def test_datetime_with_space(self):
        assert _normalize_date("2025-03-21 09:30:00") == "2025-03-21"


class TestDateParsers:
    def test_boe_date_space_format(self):
        assert _parse_boe_date("02 Jan 2024") == "2024-01-02"

    def test_boe_date_slash_format(self):
        assert _parse_boe_date("15/Mar/2025") == "2025-03-15"

    def test_boe_date_dash_format(self):
        assert _parse_boe_date("30-Dec-2023") == "2023-12-30"

    def test_boe_date_invalid(self):
        with pytest.raises(ValueError):
            _parse_boe_date("2024-01-01")

    def test_rba_date_dash_month_format(self):
        assert _parse_rba_date("02-Jan-2024") == "2024-01-02"

    def test_rba_date_slash_format(self):
        assert _parse_rba_date("15/03/2025") == "2025-03-15"

    def test_rba_date_iso_format(self):
        assert _parse_rba_date("2023-12-30") == "2023-12-30"

    def test_rba_date_invalid(self):
        with pytest.raises(ValueError):
            _parse_rba_date("not-a-date")


class TestBenchmarks:
    def test_all_g10_covered(self):
        expected = {"USD", "GBP", "EUR", "JPY", "CAD", "AUD", "CHF", "SEK", "NOK", "NZD"}
        assert set(BENCHMARKS.keys()) == expected

    def test_benchmark_names(self):
        assert BENCHMARKS["USD"] == "SOFR"
        assert BENCHMARKS["GBP"] == "SONIA"
        assert BENCHMARKS["EUR"] == "ESTR"
        assert BENCHMARKS["JPY"] == "TONA"
        assert BENCHMARKS["CAD"] == "CORRA"


class TestDayCountConventions:
    def test_all_benchmarks_have_day_count(self):
        for ccy in BENCHMARKS:
            assert ccy in _DAY_COUNT_BASIS, f"Missing day count for {ccy}"

    def test_act_360_currencies(self):
        for ccy in ("USD", "EUR", "CHF", "SEK", "NOK"):
            assert _DAY_COUNT_BASIS[ccy] == 360, f"{ccy} should be ACT/360"

    def test_act_365_currencies(self):
        for ccy in ("GBP", "JPY", "CAD", "AUD", "NZD"):
            assert _DAY_COUNT_BASIS[ccy] == 365, f"{ccy} should be ACT/365"

    def test_sofr_daily_conversion(self):
        # 5.31% annual SOFR → daily decimal via ACT/360
        annual_pct = 5.31
        expected = 5.31 / 100.0 / 360.0
        actual = annual_pct / 100.0 / _DAY_COUNT_BASIS["USD"]
        assert abs(actual - expected) < 1e-12

    def test_sonia_daily_conversion(self):
        # 4.50% annual SONIA → daily decimal via ACT/365
        annual_pct = 4.50
        expected = 4.50 / 100.0 / 365.0
        actual = annual_pct / 100.0 / _DAY_COUNT_BASIS["GBP"]
        assert abs(actual - expected) < 1e-12

    def test_act360_vs_act365_differ(self):
        # Same annual rate, different conventions → different daily rates
        annual_pct = 5.0
        daily_360 = annual_pct / 100.0 / 360
        daily_365 = annual_pct / 100.0 / 365
        assert daily_360 > daily_365  # fewer days → higher daily rate


class TestRateObservation:
    def test_creation(self):
        obs = RateObservation(
            currency="USD", benchmark="SOFR",
            date="2024-01-15", rate=5.31,
            source="NY Fed Markets API",
        )
        assert obs.currency == "USD"
        assert obs.rate == 5.31


class TestHTTPErrorHandling:
    """Fetchers should handle HTTP errors gracefully, not crash."""

    @pytest.fixture
    def fetcher(self):
        class _NullDB:
            class _Session:
                async def execute(self, *a, **kw):
                    class _R:
                        def all(self):
                            return []
                        def first(self):
                            return None
                    return _R()
                async def commit(self):
                    pass
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *a):
                    pass
            def session(self):
                return self._Session()
        return RiskFreeRateFetcher(_NullDB())

    @pytest.mark.asyncio
    async def test_dispatch_handles_http_400(self, fetcher):
        """A 400/403/500 from a central bank API should return empty, not raise."""
        import httpx
        from unittest.mock import AsyncMock

        # Simulate a 403 Forbidden like RBNZ returns
        original = fetcher._fetch_ocr
        async def _mock_403(start, end):
            resp = httpx.Response(403, request=httpx.Request("GET", "https://example.com"))
            raise httpx.HTTPStatusError("Forbidden", request=resp.request, response=resp)

        fetcher._fetch_ocr = _mock_403
        result = await fetcher._dispatch_fetch("NZD", "2025-01-01", "2025-01-10")
        assert result == []

    @pytest.mark.asyncio
    async def test_dispatch_handles_network_error(self, fetcher):
        """Network failures should return empty, not raise."""
        import httpx

        async def _mock_network_error(start, end):
            raise httpx.ConnectError("Connection refused")

        fetcher._fetch_sofr = _mock_network_error
        result = await fetcher._dispatch_fetch("USD", "2025-01-01", "2025-01-10")
        assert result == []

    @pytest.mark.asyncio
    async def test_dispatch_unsupported_currency(self, fetcher):
        result = await fetcher._dispatch_fetch("XYZ", "2025-01-01", "2025-01-10")
        assert result == []


# ---------------------------------------------------------------------------
# Integration tests — hit real central bank APIs.
# Marked with @pytest.mark.integration so they can be skipped in CI
# via: pytest -m "not integration"
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFetcherIntegration:
    """Test each central bank fetcher against the REAL API.

    These tests hit live APIs. Run with: pytest -m integration
    They validate that:
    - The API endpoint is reachable and returns data
    - The response is parsed correctly (dates, rates, currency codes)
    - Date formats match YYYY-MM-DD
    - Rates are in a sane range (0-20% annual)
    - Multiple business days are returned for a week-long range
    - Known API quirks (BoE HTML, RBNZ 403) are handled gracefully
    """

    # Use a historical range that definitely has data for all G10 central banks.
    # Avoid recent dates (may not be published yet) and weekends.
    START = "2025-01-06"  # Monday
    END = "2025-01-10"    # Friday — 5 business days

    @pytest.fixture
    def fetcher(self):
        """RiskFreeRateFetcher without a database (fetch-only)."""

        class _NullDB:
            class _Session:
                async def execute(self, *a, **kw):
                    class _R:
                        def all(self):
                            return []
                        def first(self):
                            return None
                        def scalars(self):
                            return self
                    return _R()

                async def commit(self):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    pass

            def session(self):
                return self._Session()

        return RiskFreeRateFetcher(_NullDB())

    def _validate_observations(self, obs, currency, benchmark, min_count=1):
        """Common validation for all central bank responses."""
        assert len(obs) >= min_count, (
            f"{currency} ({benchmark}): expected >= {min_count} observations, got {len(obs)}"
        )
        for o in obs:
            assert o.currency == currency
            assert o.benchmark == benchmark
            # Date must be YYYY-MM-DD (10 chars, parseable)
            assert len(o.date) == 10, f"Bad date format: {o.date!r}"
            from datetime import date as d
            d.fromisoformat(o.date)  # will raise if invalid
            # Rate must be a sane annual percentage
            assert -1 < o.rate < 20, f"Rate {o.rate}% out of range for {currency}"
            assert o.source, "source must not be empty"

    # -- ACT/360 currencies ------------------------------------------------

    @pytest.mark.asyncio
    async def test_sofr_usd(self, fetcher):
        """NY Fed SOFR — JSON API, ACT/360."""
        obs = await fetcher._fetch_sofr(self.START, self.END)
        self._validate_observations(obs, "USD", "SOFR", min_count=3)

    @pytest.mark.asyncio
    async def test_estr_eur(self, fetcher):
        """ECB ESTR — SDMX CSV API, ACT/360."""
        obs = await fetcher._fetch_estr(self.START, self.END)
        self._validate_observations(obs, "EUR", "ESTR", min_count=3)

    @pytest.mark.asyncio
    async def test_saron_chf(self, fetcher):
        """SNB SARON — semicolon-delimited CSV, ACT/360."""
        obs = await fetcher._fetch_saron(self.START, self.END)
        self._validate_observations(obs, "CHF", "SARON", min_count=3)

    @pytest.mark.asyncio
    async def test_swestr_sek(self, fetcher):
        """Riksbank SWESTR — JSON API, ACT/360."""
        obs = await fetcher._fetch_swestr(self.START, self.END)
        self._validate_observations(obs, "SEK", "SWESTR", min_count=3)

    @pytest.mark.asyncio
    async def test_nowa_nok(self, fetcher):
        """Norges Bank NOWA — SDMX CSV, ACT/360."""
        obs = await fetcher._fetch_nowa(self.START, self.END)
        self._validate_observations(obs, "NOK", "NOWA", min_count=3)

    # -- ACT/365 currencies ------------------------------------------------

    @pytest.mark.asyncio
    async def test_corra_cad(self, fetcher):
        """Bank of Canada CORRA — JSON Valet API, ACT/365."""
        obs = await fetcher._fetch_corra(self.START, self.END)
        self._validate_observations(obs, "CAD", "CORRA", min_count=3)

    @pytest.mark.asyncio
    async def test_tona_jpy(self, fetcher):
        """Bank of Japan TONA — REST API, ACT/365.
        May fail if BoJ API is unavailable; should return empty, not crash."""
        obs = await fetcher._fetch_tona(self.START, self.END)
        if obs:
            self._validate_observations(obs, "JPY", "TONA")

    # -- Quirky APIs -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sonia_gbp_handles_html_response(self, fetcher):
        """BoE SONIA — may return HTML instead of CSV.
        Must return empty list, not crash on HTML parsing."""
        obs = await fetcher._fetch_sonia(self.START, self.END)
        # If BoE returns CSV, validate it. If it returns HTML, should be empty.
        if obs:
            self._validate_observations(obs, "GBP", "SONIA", min_count=1)
        # Either way, no crash.

    @pytest.mark.asyncio
    async def test_rba_aud_static_csv(self, fetcher):
        """RBA Cash Rate — static CSV file download, ACT/365.
        The RBA serves a large CSV with all historical data; we filter by date."""
        obs = await fetcher._fetch_rba(self.START, self.END)
        if obs:
            self._validate_observations(obs, "AUD", "CASH_RATE")

    @pytest.mark.asyncio
    async def test_ocr_nzd_excel_download(self, fetcher):
        """RBNZ OCR — Excel file download, ACT/365.
        RBNZ may block with 403; should return empty via _dispatch_fetch."""
        result = await fetcher._dispatch_fetch("NZD", self.START, self.END)
        # Either parsed successfully or returned empty (403 handled gracefully)
        if result:
            self._validate_observations(result, "NZD", "OCR")

    # -- Dispatch-level tests ----------------------------------------------

    @pytest.mark.asyncio
    async def test_dispatch_all_g10_no_crash(self, fetcher):
        """Every G10 currency should be fetchable without crashing.
        Some may return empty (API down, 403, etc.) but none should raise."""
        for currency in BENCHMARKS:
            result = await fetcher._dispatch_fetch(currency, self.START, self.END)
            assert isinstance(result, list), f"{currency} dispatch returned non-list"

    @pytest.mark.asyncio
    async def test_unsupported_currency_returns_empty(self, fetcher):
        result = await fetcher._dispatch_fetch("XYZ", self.START, self.END)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_daily_rates_returns_correct_length(self, fetcher):
        """get_daily_rates should return an array matching the input dates length."""
        import numpy as np
        dates = ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"]
        rates = await fetcher.get_daily_rates("USD", dates)
        assert len(rates) == len(dates)
        assert rates.dtype == np.float64

    @pytest.mark.asyncio
    async def test_get_daily_rates_with_yfinance_datetime_format(self, fetcher):
        """Dates from yfinance include timezone info — must be handled."""
        import numpy as np
        dates = [
            "2025-01-06 00:00:00-05:00",
            "2025-01-07 00:00:00-05:00",
            "2025-01-08 00:00:00-05:00",
        ]
        rates = await fetcher.get_daily_rates("USD", dates)
        assert len(rates) == 3
        # Should not crash on the datetime format
