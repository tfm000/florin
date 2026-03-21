"""Tests for stats.risk_free — G10 central bank rate fetcher."""

import pytest

from stats.risk_free import (
    RateObservation,
    RiskFreeRateFetcher,
    _parse_boe_date,
    _parse_rba_date,
    BENCHMARKS,
    _DAY_COUNT_BASIS,
)


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


# ---------------------------------------------------------------------------
# Integration tests — hit real central bank APIs.
# Marked with @pytest.mark.integration so they can be skipped in CI
# via: pytest -m "not integration"
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFetcherIntegration:
    """Test that each central bank fetcher can retrieve real data.

    These tests hit live APIs so they may be slow or flaky due to
    network issues. Run with: pytest -m integration
    """

    @pytest.fixture
    def fetcher(self):
        """RiskFreeRateFetcher without a database (fetch-only)."""

        class _NullDB:
            """Stub — we only test the HTTP fetch, not DB storage."""

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

    @pytest.mark.asyncio
    async def test_fetch_sofr(self, fetcher):
        obs = await fetcher._fetch_sofr("2025-01-02", "2025-01-10")
        assert len(obs) > 0, "SOFR should return observations"
        assert obs[0].currency == "USD"
        assert obs[0].benchmark == "SOFR"
        assert 0 < obs[0].rate < 20  # sanity: rate between 0% and 20%

    @pytest.mark.asyncio
    async def test_fetch_estr(self, fetcher):
        obs = await fetcher._fetch_estr("2025-01-02", "2025-01-10")
        assert len(obs) > 0, "ESTR should return observations"
        assert obs[0].currency == "EUR"

    @pytest.mark.asyncio
    async def test_fetch_corra(self, fetcher):
        obs = await fetcher._fetch_corra("2025-01-02", "2025-01-10")
        assert len(obs) > 0, "CORRA should return observations"
        assert obs[0].currency == "CAD"

    @pytest.mark.asyncio
    async def test_fetch_sonia(self, fetcher):
        obs = await fetcher._fetch_sonia("2025-01-02", "2025-01-10")
        # BoE may block non-browser requests; if so, should return empty
        # rather than crash
        if obs:
            assert obs[0].currency == "GBP"

    @pytest.mark.asyncio
    async def test_fetch_swestr(self, fetcher):
        obs = await fetcher._fetch_swestr("2025-01-02", "2025-01-10")
        assert len(obs) > 0, "SWESTR should return observations"
        assert obs[0].currency == "SEK"

    @pytest.mark.asyncio
    async def test_unsupported_currency_returns_zeros(self, fetcher):
        import numpy as np
        rates = await fetcher.get_daily_rates("XYZ", ["2025-01-02"])
        assert len(rates) == 1
        assert rates[0] == 0.0
