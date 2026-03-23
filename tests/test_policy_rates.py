"""Tests for data.policy_rates — PolicyRateFetcher BIS CBPOL integration."""

import time

import httpx
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from data.policy_rates import (
    PolicyRateFetcher,
    G10_COUNTRIES,
    _SEED_RATES,
    _CACHE_TTL,
    _BIS_URL,
)
from db.database import Database
from db.models import PolicyRateORM


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    """In-memory SQLite database for testing."""
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.init()
    await database.create_tables()
    yield database
    await database.close()


@pytest.fixture
async def fetcher(db):
    """PolicyRateFetcher with a real in-memory DB."""
    f = PolicyRateFetcher(db)
    yield f
    await f.close()


# Sample BIS CSV data — realistic format with multiple observations per country
BIS_CSV_FULL = (
    "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "M,US,2024-01,5.50,\n"
    "M,US,2024-06,5.25,\n"
    "M,US,2024-12,4.50,\n"
    "M,XM,2024-01,4.00,\n"
    "M,XM,2024-12,2.65,\n"
    "M,GB,2024-12,4.50,\n"
    "M,JP,2024-12,0.50,\n"
    "M,CA,2024-12,2.75,\n"
    "M,AU,2024-12,4.10,\n"
    "M,NZ,2024-12,3.75,\n"
    "M,CH,2024-12,0.25,\n"
    "M,SE,2024-12,2.25,\n"
    "M,NO,2024-12,4.50,\n"
)

BIS_CSV_PARTIAL = (
    "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "M,US,2024-12,4.50,\n"
    "M,GB,2024-12,4.50,\n"
)

BIS_CSV_EMPTY = "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"


# ---------------------------------------------------------------------------
# CSV Parsing
# ---------------------------------------------------------------------------

class TestBISCSVParsing:
    """Test BIS CBPOL CSV parsing logic."""

    @pytest.mark.asyncio
    async def test_parse_all_g10_countries(self, fetcher):
        """All 10 G10 countries are parsed from a complete CSV."""
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_FULL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        assert len(rates) == 10
        countries = {r["country_code"] for r in rates}
        assert countries == set(G10_COUNTRIES.keys())

    @pytest.mark.asyncio
    async def test_latest_observation_wins(self, fetcher):
        """When multiple observations exist per country, the latest date wins."""
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_FULL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        us_rate = next(r for r in rates if r["country_code"] == "US")
        assert us_rate["rate"] == 4.50  # 2024-12 value, not 5.50 (2024-01)
        assert us_rate["effective_date"] == "2024-12"

    @pytest.mark.asyncio
    async def test_partial_csv_returns_available_countries_only(self, fetcher):
        """If CSV only has data for some countries, only those are returned."""
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_PARTIAL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        assert len(rates) == 2
        codes = {r["country_code"] for r in rates}
        assert codes == {"US", "GB"}

    @pytest.mark.asyncio
    async def test_empty_csv_returns_empty(self, fetcher):
        """CSV with headers only returns empty list."""
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_EMPTY
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()
        assert rates == []

    @pytest.mark.asyncio
    async def test_nan_values_skipped(self, fetcher):
        """NaN observations are filtered out."""
        csv_data = (
            "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
            "M,US,2024-12,NaN,\n"
            "M,GB,2024-12,4.50,\n"
        )
        mock_resp = MagicMock()
        mock_resp.text = csv_data
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        assert len(rates) == 1
        assert rates[0]["country_code"] == "GB"

    @pytest.mark.asyncio
    async def test_non_numeric_values_skipped(self, fetcher):
        """Non-numeric OBS_VALUE entries are silently skipped."""
        csv_data = (
            "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
            "M,US,2024-12,invalid,\n"
            "M,GB,2024-12,,\n"
            "M,JP,2024-12,0.50,\n"
        )
        mock_resp = MagicMock()
        mock_resp.text = csv_data
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        assert len(rates) == 1
        assert rates[0]["country_code"] == "JP"

    @pytest.mark.asyncio
    async def test_unknown_country_codes_ignored(self, fetcher):
        """Country codes not in G10_COUNTRIES are filtered out."""
        csv_data = (
            "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
            "M,US,2024-12,4.50,\n"
            "M,XX,2024-12,5.00,\n"
            "M,BR,2024-12,11.75,\n"
        )
        mock_resp = MagicMock()
        mock_resp.text = csv_data
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        assert len(rates) == 1
        assert rates[0]["country_code"] == "US"

    @pytest.mark.asyncio
    async def test_rate_metadata_is_correct(self, fetcher):
        """Each rate dict includes correct country, central_bank, and currency from G10_COUNTRIES."""
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_FULL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher._fetch_from_bis()

        for r in rates:
            code = r["country_code"]
            expected = G10_COUNTRIES[code]
            assert r["country"] == expected["country"]
            assert r["central_bank"] == expected["central_bank"]
            assert r["currency"] == expected["currency"]
            assert isinstance(r["rate"], float)
            assert r["effective_date"] != ""


# ---------------------------------------------------------------------------
# HTTP Error Handling
# ---------------------------------------------------------------------------

class TestHTTPErrors:
    """Test BIS API error handling."""

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self, fetcher):
        """HTTP 500 from BIS API returns empty list, does not raise."""
        resp = httpx.Response(500, request=httpx.Request("GET", _BIS_URL))
        fetcher._client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("Server error", request=resp.request, response=resp)
        )

        rates = await fetcher._fetch_from_bis()
        assert rates == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self, fetcher):
        """Connection timeout returns empty list, does not raise."""
        fetcher._client.get = AsyncMock(
            side_effect=httpx.TimeoutException("timeout")
        )

        rates = await fetcher._fetch_from_bis()
        assert rates == []

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty(self, fetcher):
        """Network connection error returns empty list."""
        fetcher._client.get = AsyncMock(
            side_effect=httpx.ConnectError("DNS resolution failed")
        )

        rates = await fetcher._fetch_from_bis()
        assert rates == []


# ---------------------------------------------------------------------------
# Database Persistence
# ---------------------------------------------------------------------------

class TestDBPersistence:
    """Test database storage and retrieval of policy rates."""

    @pytest.mark.asyncio
    async def test_persist_inserts_new_rows(self, fetcher, db):
        """First persist creates new rows for each country."""
        rates = [
            {"country_code": "US", "country": "United States",
             "central_bank": "Federal Reserve", "currency": "USD",
             "rate": 4.50, "effective_date": "2024-12"},
            {"country_code": "GB", "country": "United Kingdom",
             "central_bank": "Bank of England", "currency": "GBP",
             "rate": 4.50, "effective_date": "2024-12"},
        ]

        await fetcher._persist(rates)

        from sqlalchemy import select as sa_select
        async with db.session() as session:
            result = await session.execute(sa_select(PolicyRateORM))
            rows = result.scalars().all()

        assert len(rows) == 2
        us = next(r for r in rows if r.country_code == "US")
        assert us.rate == 4.50
        assert us.effective_date == "2024-12"

    @pytest.mark.asyncio
    async def test_persist_upserts_existing_rows(self, fetcher, db):
        """Second persist with same country_code updates rate and date, not duplicate."""
        rates_v1 = [
            {"country_code": "US", "country": "United States",
             "central_bank": "Federal Reserve", "currency": "USD",
             "rate": 5.50, "effective_date": "2024-01"},
        ]
        rates_v2 = [
            {"country_code": "US", "country": "United States",
             "central_bank": "Federal Reserve", "currency": "USD",
             "rate": 4.50, "effective_date": "2024-12"},
        ]

        await fetcher._persist(rates_v1)
        await fetcher._persist(rates_v2)

        from sqlalchemy import select as sa_select
        async with db.session() as session:
            result = await session.execute(sa_select(PolicyRateORM))
            rows = result.scalars().all()

        assert len(rows) == 1  # Upserted, not duplicated
        assert rows[0].rate == 4.50
        assert rows[0].effective_date == "2024-12"

    @pytest.mark.asyncio
    async def test_read_from_db_returns_stored_rates(self, fetcher, db):
        """_read_from_db returns previously persisted rates."""
        rates = [
            {"country_code": "JP", "country": "Japan",
             "central_bank": "Bank of Japan", "currency": "JPY",
             "rate": 0.50, "effective_date": "2024-12"},
        ]
        await fetcher._persist(rates)

        result = await fetcher._read_from_db()

        assert len(result) == 1
        assert result[0]["country_code"] == "JP"
        assert result[0]["rate"] == 0.50
        assert result[0]["country"] == "Japan"

    @pytest.mark.asyncio
    async def test_read_from_empty_db_returns_empty(self, fetcher):
        """_read_from_db on a fresh DB returns empty list."""
        result = await fetcher._read_from_db()
        assert result == []

    @pytest.mark.asyncio
    async def test_persist_handles_db_errors_gracefully(self):
        """DB write failure is caught and logged, not raised."""
        class _BrokenDB:
            def session(self):
                raise RuntimeError("DB connection lost")

        fetcher = PolicyRateFetcher(_BrokenDB())
        # Should not raise
        await fetcher._persist([{"country_code": "US", "country": "US",
                                 "central_bank": "Fed", "currency": "USD",
                                 "rate": 4.50}])
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_read_handles_db_errors_gracefully(self):
        """DB read failure returns empty list, not an exception."""
        class _BrokenDB:
            def session(self):
                raise RuntimeError("DB connection lost")

        fetcher = PolicyRateFetcher(_BrokenDB())
        result = await fetcher._read_from_db()
        assert result == []
        await fetcher.close()


# ---------------------------------------------------------------------------
# Fallback Chain
# ---------------------------------------------------------------------------

class TestFallbackChain:
    """Test the cache → API → DB → seeds fallback logic."""

    @pytest.mark.asyncio
    async def test_api_success_caches_and_persists(self, fetcher):
        """Successful API call populates cache and writes to DB."""
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_PARTIAL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher.get_rates()

        assert len(rates) == 2
        assert fetcher._cache is not None
        assert fetcher._cache_time > 0

        # Verify DB was written
        db_rates = await fetcher._read_from_db()
        assert len(db_rates) == 2

    @pytest.mark.asyncio
    async def test_api_failure_falls_back_to_db(self, fetcher, db):
        """When BIS API fails, previously stored DB rates are returned."""
        # Pre-populate DB
        stored = [
            {"country_code": "US", "country": "United States",
             "central_bank": "Federal Reserve", "currency": "USD",
             "rate": 5.00, "effective_date": "2024-06"},
        ]
        await fetcher._persist(stored)

        # Mock API failure
        fetcher._client.get = AsyncMock(
            side_effect=httpx.ConnectError("BIS down")
        )

        rates = await fetcher.get_rates()

        assert len(rates) == 1
        assert rates[0]["rate"] == 5.00

    @pytest.mark.asyncio
    async def test_api_and_db_failure_falls_back_to_seeds(self):
        """When both API and DB fail, seed values are returned."""
        class _BrokenDB:
            def session(self):
                raise RuntimeError("DB gone")

        fetcher = PolicyRateFetcher(_BrokenDB())
        fetcher._client.get = AsyncMock(
            side_effect=httpx.ConnectError("BIS down")
        )

        rates = await fetcher.get_rates()

        assert len(rates) == 10
        us = next(r for r in rates if r["country_code"] == "US")
        assert us["rate"] == _SEED_RATES["US"]
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_cache_skips_api_within_ttl(self, fetcher):
        """Cached rates are returned without hitting the API when within TTL."""
        cached_rates = [{"country": "Test", "rate": 99.0}]
        fetcher._cache = cached_rates
        fetcher._cache_time = time.time()  # Fresh

        fetcher._client.get = AsyncMock(side_effect=AssertionError("Should not be called"))

        rates = await fetcher.get_rates()
        assert rates == cached_rates

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, fetcher):
        """Expired cache triggers a fresh API call."""
        fetcher._cache = [{"country": "Stale", "rate": 0.0}]
        fetcher._cache_time = time.time() - _CACHE_TTL - 1  # Expired

        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_PARTIAL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher.get_rates()

        assert len(rates) == 2  # Fresh data, not the stale [{"country": "Stale"}]
        assert rates[0]["country_code"] == "US"

    @pytest.mark.asyncio
    async def test_empty_cache_triggers_fetch(self, fetcher):
        """None cache (initial state) triggers API call."""
        assert fetcher._cache is None

        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_PARTIAL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        rates = await fetcher.get_rates()
        assert len(rates) == 2


# ---------------------------------------------------------------------------
# Seed Values
# ---------------------------------------------------------------------------

class TestSeedValues:
    """Test hardcoded seed rate fallback values."""

    def test_seed_rates_cover_all_g10_countries(self):
        """Seed rates exist for every G10 country code."""
        assert set(_SEED_RATES.keys()) == set(G10_COUNTRIES.keys())

    def test_seed_rates_method_returns_all_countries(self):
        """_seed_rates() returns a list with all 10 G10 countries."""
        rates = PolicyRateFetcher._seed_rates()
        assert len(rates) == 10

        codes = {r["country_code"] for r in rates}
        assert codes == set(G10_COUNTRIES.keys())

    def test_seed_rates_have_required_fields(self):
        """Each seed rate dict has all required keys."""
        required_keys = {"country", "central_bank", "rate", "currency",
                         "effective_date", "country_code"}
        for r in PolicyRateFetcher._seed_rates():
            assert required_keys.issubset(r.keys()), f"Missing keys in {r}"

    def test_seed_rates_are_positive(self):
        """All seed rates are non-negative (some central banks have 0% or near-zero)."""
        for code, rate in _SEED_RATES.items():
            assert rate >= 0, f"Negative seed rate for {code}: {rate}"


# ---------------------------------------------------------------------------
# G10 Countries Metadata
# ---------------------------------------------------------------------------

class TestG10Metadata:
    """Test G10_COUNTRIES mapping completeness and consistency."""

    def test_ten_countries_defined(self):
        assert len(G10_COUNTRIES) == 10

    def test_all_countries_have_required_keys(self):
        for code, meta in G10_COUNTRIES.items():
            assert "country" in meta
            assert "central_bank" in meta
            assert "currency" in meta
            assert len(meta["currency"]) == 3  # ISO currency code

    def test_country_codes_are_two_chars(self):
        """BIS REF_AREA codes are 2 characters (XM for Eurozone)."""
        for code in G10_COUNTRIES:
            assert len(code) == 2, f"Unexpected code length: {code}"


# ---------------------------------------------------------------------------
# API Route Integration
# ---------------------------------------------------------------------------

class TestPolicyRatesRoute:
    """Test the /api/research/policy-rates endpoint with a real fetcher."""

    @pytest.fixture
    async def client(self, db):
        from config.settings import Settings
        from core.events import EventBus
        from dashboard.app import create_app
        from dashboard.deps import set_state

        settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            t212_api_key="",
            t212_api_secret="",
        )
        event_bus = EventBus()

        fetcher = PolicyRateFetcher(db)
        # Mock BIS API to return known data
        mock_resp = MagicMock()
        mock_resp.text = BIS_CSV_FULL
        mock_resp.raise_for_status = MagicMock()
        fetcher._client.get = AsyncMock(return_value=mock_resp)

        from data.yfinance_provider import YFinanceProvider
        yf = YFinanceProvider(policy_rate_fetcher=fetcher)

        app = create_app(settings, db, event_bus)
        set_state("yfinance_provider", yf)

        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_endpoint_returns_all_g10_rates(self, client):
        """GET /api/research/policy-rates returns all 10 G10 rates from BIS."""
        resp = await client.get("/api/research/policy-rates")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10

        countries = {r["country"] for r in data}
        assert "United States" in countries
        assert "Eurozone" in countries
        assert "Japan" in countries

    @pytest.mark.asyncio
    async def test_endpoint_rate_values_are_correct(self, client):
        """Rates returned by the endpoint match the BIS CSV data."""
        resp = await client.get("/api/research/policy-rates")
        data = resp.json()

        us = next(r for r in data if r["country"] == "United States")
        assert us["rate"] == 4.50
        assert us["central_bank"] == "Federal Reserve"
        assert us["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_endpoint_includes_effective_date(self, client):
        """Response includes effective_date field."""
        resp = await client.get("/api/research/policy-rates")
        data = resp.json()

        for r in data:
            assert "effective_date" in r
