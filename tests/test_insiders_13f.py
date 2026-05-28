"""Tests for Insiders and 13F filing API endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from data.sec_edgar_utils import FilingRef, Form4Transaction
from db.database import Database


@pytest.fixture
async def app():
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()

    yf_mock = AsyncMock()
    yf_mock.get_history.return_value = []
    yf_mock.get_info.return_value = {"ticker": "AAPL", "name": "Apple Inc."}

    app = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("rf_fetcher", None)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Insider routes
# ---------------------------------------------------------------------------

_INSIDERS_MODULE = "dashboard.routes.insiders"


def _make_filing_ref(**overrides) -> FilingRef:
    defaults = dict(
        form_type="4",
        filing_date="2025-06-15",
        accession="000123456789",
        accession_dashed="0001234567-89",
        primary_document="doc.xml",
        cik="0001234567",
    )
    defaults.update(overrides)
    return FilingRef(**defaults)


def _make_form4_txn(**overrides) -> Form4Transaction:
    defaults: dict[str, Any] = dict(
        insider_name="Jane Doe",
        insider_title="CEO",
        transaction_type="Purchase",
        transaction_date="2025-06-14",
        shares=1000.0,
        price_per_share=12.50,
        post_transaction_shares=5000.0,
        filing_url="",
    )
    defaults.update(overrides)
    return Form4Transaction(**defaults)


class TestInsiders:
    @pytest.mark.asyncio
    @patch(f"{_INSIDERS_MODULE}.parse_form4_transactions")
    @patch(f"{_INSIDERS_MODULE}.fetch_form4_xml", new_callable=AsyncMock)
    @patch(f"{_INSIDERS_MODULE}.get_company_filings", new_callable=AsyncMock)
    @patch(f"{_INSIDERS_MODULE}.resolve_ticker_to_cik", new_callable=AsyncMock)
    async def test_insiders_basic(self, mock_cik, mock_filings, mock_xml, mock_parse, client):
        filing = _make_filing_ref()
        mock_cik.return_value = "0001234567"
        mock_filings.return_value = [filing]
        mock_xml.return_value = "<xml>fake</xml>"
        mock_parse.return_value = [_make_form4_txn()]

        resp = await client.get("/api/insiders/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert len(data["transactions"]) == 1
        txn = data["transactions"][0]
        assert txn["insider_name"] == "Jane Doe"
        assert txn["transaction_type"] == "Buy"  # "Purchase" mapped to "Buy"
        assert txn["shares"] == 1000
        assert txn["price_per_share"] == 12.50
        assert txn["value"] == 12500.0

    @pytest.mark.asyncio
    @patch(f"{_INSIDERS_MODULE}.resolve_ticker_to_cik", new_callable=AsyncMock)
    async def test_insiders_no_cik(self, mock_cik, client):
        mock_cik.return_value = None

        resp = await client.get("/api/insiders/FAKE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "FAKE"
        assert data["transactions"] == []
        assert data["cluster_buys"] == []

    @pytest.mark.asyncio
    @patch(f"{_INSIDERS_MODULE}.get_company_filings", new_callable=AsyncMock)
    @patch(f"{_INSIDERS_MODULE}.resolve_ticker_to_cik", new_callable=AsyncMock)
    async def test_insiders_no_filings(self, mock_cik, mock_filings, client):
        mock_cik.return_value = "0001234567"
        mock_filings.return_value = []

        resp = await client.get("/api/insiders/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["transactions"] == []


# ---------------------------------------------------------------------------
# 13F routes
# ---------------------------------------------------------------------------

_13F_MODULE = "data.sec_13f_provider"


class TestCusipCachePersistence:
    @pytest.fixture(autouse=True)
    def _stub_sec_name_map(self):
        """load_cusip_cache() unconditionally fetches SEC company_tickers.json via
        _load_sec_name_map(). These tests exercise the DB-backed CUSIP cache, not the
        name map, so stub the network fetch to keep them hermetic (and CI-safe)."""
        with patch(f"{_13F_MODULE}._load_sec_name_map", new_callable=AsyncMock):
            yield

    @pytest.mark.asyncio
    async def test_load_and_persist_cusip_cache(self, app):
        """CUSIP mappings can be persisted to DB and reloaded."""
        from dashboard.deps import get_db
        from data.sec_13f_provider import (
            _cusip_cache,
            _persist_cusip_mappings,
            load_cusip_cache,
        )

        db = get_db()

        # Clear in-memory cache
        _cusip_cache.clear()

        # Persist some mappings
        import data.sec_13f_provider as provider

        provider._db_ref = db
        await _persist_cusip_mappings({"037833100": "AAPL", "594918104": "MSFT"})

        # Clear cache again
        _cusip_cache.clear()
        assert "037833100" not in _cusip_cache

        # Reload from DB
        await load_cusip_cache(db)
        assert _cusip_cache["037833100"] == "AAPL"
        assert _cusip_cache["594918104"] == "MSFT"

    @pytest.mark.asyncio
    async def test_persist_updates_existing_mapping(self, app):
        """Persisting a CUSIP that already exists updates the ticker."""
        from dashboard.deps import get_db
        from data.sec_13f_provider import (
            _cusip_cache,
            _persist_cusip_mappings,
            load_cusip_cache,
        )

        db = get_db()

        import data.sec_13f_provider as provider

        provider._db_ref = db

        # First mapping
        await _persist_cusip_mappings({"TESTCUSIP": "OLD"})
        _cusip_cache.clear()
        await load_cusip_cache(db)
        assert _cusip_cache["TESTCUSIP"] == "OLD"

        # Update mapping (ticker changed)
        await _persist_cusip_mappings({"TESTCUSIP": "NEW"})
        _cusip_cache.clear()
        await load_cusip_cache(db)
        assert _cusip_cache["TESTCUSIP"] == "NEW"


class TestParseXmlFigi:
    """Test that FIGI tags are extracted from 13F XML when present."""

    def test_parse_xml_with_figi(self):
        from data.sec_13f_provider import _parse_13f_xml

        xml = """<?xml version="1.0"?>
        <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
          <infoTable>
            <nameOfIssuer>APPLE INC</nameOfIssuer>
            <titleOfClass>COM</titleOfClass>
            <cusip>037833100</cusip>
            <figi>BBG000B9XRY4</figi>
            <value>150000000</value>
            <shrsOrPrnAmt><sshPrnamt>905560</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
          </infoTable>
        </informationTable>"""
        holdings = _parse_13f_xml(xml)
        assert len(holdings) == 1
        assert holdings[0]["cusip"] == "037833100"
        assert holdings[0]["figi"] == "BBG000B9XRY4"
        assert holdings[0]["name"] == "APPLE INC"
        assert holdings[0]["shares"] == 905560
        assert holdings[0]["value"] == 150000000

    def test_parse_xml_without_figi(self):
        from data.sec_13f_provider import _parse_13f_xml

        xml = """<?xml version="1.0"?>
        <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
          <infoTable>
            <nameOfIssuer>TESLA INC</nameOfIssuer>
            <titleOfClass>COM</titleOfClass>
            <cusip>88160R101</cusip>
            <value>50000000</value>
            <shrsOrPrnAmt><sshPrnamt>200000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
          </infoTable>
        </informationTable>"""
        holdings = _parse_13f_xml(xml)
        assert len(holdings) == 1
        assert "figi" not in holdings[0]  # no figi tag in XML


class TestSecNameMapping:
    """Test SEC company_tickers.json name-based CUSIP mapping."""

    @pytest.mark.asyncio
    async def test_name_matching_resolves_cusips(self):
        from data.sec_13f_provider import (
            _cusip_cache,
            _name_to_ticker,
            map_cusips_to_tickers,
        )

        _cusip_cache.clear()
        # Simulate loaded SEC name map
        _name_to_ticker.clear()
        _name_to_ticker["APPLE INC"] = "AAPL"
        _name_to_ticker["MICROSOFT CORP"] = "MSFT"

        holdings = [
            {"cusip": "037833100", "name": "APPLE INC"},
            {"cusip": "594918104", "name": "MICROSOFT CORP"},
            {"cusip": "G1890L107", "name": "UNKNOWN FOREIGN CO"},
        ]
        cusips = [h["cusip"] for h in holdings]
        result = await map_cusips_to_tickers(cusips, holdings=holdings)

        assert result["037833100"] == "AAPL"
        assert result["594918104"] == "MSFT"
        # Foreign CUSIP not in name map, and OpenFIGI not called in unit test
        assert result["G1890L107"] == ""

        # Verify they got cached
        assert _cusip_cache["037833100"] == "AAPL"
        assert _cusip_cache["594918104"] == "MSFT"

        _name_to_ticker.clear()
        _cusip_cache.clear()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_name_matching(self):
        from data.sec_13f_provider import _cusip_cache, map_cusips_to_tickers

        _cusip_cache.clear()
        _cusip_cache["CACHED123"] = "CACHED"

        result = await map_cusips_to_tickers(["CACHED123"])
        assert result["CACHED123"] == "CACHED"
        _cusip_cache.clear()


class TestOpenFIGICachePreFilter:
    """Test that _openfigi_lookup skips CUSIPs already in cache."""

    @pytest.mark.asyncio
    async def test_cached_cusips_skip_api_call(self):
        from data.sec_13f_provider import _cusip_cache, _openfigi_lookup

        _cusip_cache.clear()
        _cusip_cache["CACHED01"] = "AAPL"
        _cusip_cache["CACHED02"] = "MSFT"

        # All CUSIPs are cached — should return immediately without API call
        jobs = [
            {"idType": "ID_CUSIP", "idValue": "CACHED01"},
            {"idType": "ID_CUSIP", "idValue": "CACHED02"},
        ]
        result = await _openfigi_lookup(jobs, ["CACHED01", "CACHED02"])
        assert result["CACHED01"] == "AAPL"
        assert result["CACHED02"] == "MSFT"

        _cusip_cache.clear()


class TestBulkCusipPersistence:
    """Test that bulk upsert persists multiple CUSIP mappings in one operation."""

    @pytest.fixture(autouse=True)
    def _stub_sec_name_map(self):
        """Stub the SEC company_tickers.json fetch that load_cusip_cache() triggers —
        these tests cover DB-backed bulk upsert, not the name map. Keeps them hermetic."""
        with patch(f"{_13F_MODULE}._load_sec_name_map", new_callable=AsyncMock):
            yield

    @pytest.mark.asyncio
    async def test_bulk_persist_multiple_mappings(self, app):
        from dashboard.deps import get_db
        from data.sec_13f_provider import (
            _cusip_cache,
            _persist_cusip_mappings,
            load_cusip_cache,
        )

        db = get_db()

        import data.sec_13f_provider as provider

        provider._db_ref = db
        _cusip_cache.clear()

        # Persist batch of mappings
        mappings = {
            "BULK001": "AAPL",
            "BULK002": "MSFT",
            "BULK003": "GOOG",
        }
        await _persist_cusip_mappings(mappings)

        # Verify all were saved to DB
        _cusip_cache.clear()
        await load_cusip_cache(db)
        assert _cusip_cache["BULK001"] == "AAPL"
        assert _cusip_cache["BULK002"] == "MSFT"
        assert _cusip_cache["BULK003"] == "GOOG"

        _cusip_cache.clear()

    @pytest.mark.asyncio
    async def test_bulk_upsert_updates_existing(self, app):
        from dashboard.deps import get_db
        from data.sec_13f_provider import (
            _cusip_cache,
            _persist_cusip_mappings,
            load_cusip_cache,
        )

        db = get_db()

        import data.sec_13f_provider as provider

        provider._db_ref = db

        # Initial persist
        await _persist_cusip_mappings({"UPSERT01": "OLD_TICKER"})
        _cusip_cache.clear()
        await load_cusip_cache(db)
        assert _cusip_cache["UPSERT01"] == "OLD_TICKER"

        # Upsert with new ticker
        await _persist_cusip_mappings({"UPSERT01": "NEW_TICKER", "UPSERT02": "MSFT"})
        _cusip_cache.clear()
        await load_cusip_cache(db)
        assert _cusip_cache["UPSERT01"] == "NEW_TICKER"
        assert _cusip_cache["UPSERT02"] == "MSFT"

        _cusip_cache.clear()


class TestSearch13FFilers:
    @pytest.mark.asyncio
    @patch(f"{_13F_MODULE}.search_filers", new_callable=AsyncMock)
    async def test_search_filers(self, mock_search, client):
        mock_search.return_value = [
            {"cik": "0001067983", "name": "BERKSHIRE HATHAWAY INC", "filing_date": "2025-05-15"},
        ]
        resp = await client.get("/api/13f/search?q=Berkshire")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["cik"] == "0001067983"
        assert data[0]["name"] == "BERKSHIRE HATHAWAY INC"

    @pytest.mark.asyncio
    async def test_search_filers_min_length(self, client):
        resp = await client.get("/api/13f/search?q=B")
        assert resp.status_code == 422  # FastAPI validation error


class TestGet13FFilings:
    @pytest.mark.asyncio
    @patch(f"{_13F_MODULE}.get_filings", new_callable=AsyncMock)
    async def test_get_filings(self, mock_filings, client):
        mock_filings.return_value = [
            {"accession": "0001234567-25-000001", "date": "2025-05-15", "document": "form13f.xml"},
            {"accession": "0001234567-24-000010", "date": "2024-11-14", "document": "form13f.xml"},
        ]
        resp = await client.get("/api/13f/filings?cik=0001067983")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["accession"] == "0001234567-25-000001"
        assert data[1]["date"] == "2024-11-14"


class TestGet13FHoldings:
    @pytest.mark.asyncio
    @patch(f"{_13F_MODULE}.map_cusips_to_tickers", new_callable=AsyncMock)
    @patch(f"{_13F_MODULE}.get_holdings", new_callable=AsyncMock)
    async def test_get_holdings(self, mock_holdings, mock_cusip_map, client):
        mock_holdings.return_value = [
            {
                "cusip": "037833100",
                "name": "APPLE INC",
                "title": "COM",
                "shares": 905560,
                "value": 150_000_000,
            },
            {
                "cusip": "594918104",
                "name": "MICROSOFT CORP",
                "title": "COM",
                "shares": 315200,
                "value": 120_000_000,
            },
        ]
        mock_cusip_map.return_value = {
            "037833100": "AAPL",
            "594918104": "MSFT",
        }

        resp = await client.get("/api/13f/holdings?cik=0001067983&accession=0001234567-25-000001")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Sorted by value descending
        assert data[0]["ticker"] == "AAPL"
        assert data[0]["value"] == 150_000_000
        assert data[0]["weight"] > 0
        assert data[1]["ticker"] == "MSFT"
        # Weights should sum to 100
        total_weight = sum(h["weight"] for h in data)
        assert abs(total_weight - 100.0) < 0.1

    @pytest.mark.asyncio
    @patch(f"{_13F_MODULE}.map_cusips_to_tickers", new_callable=AsyncMock)
    @patch(f"{_13F_MODULE}.get_holdings", new_callable=AsyncMock)
    async def test_holdings_cache_prevents_refetch(self, mock_holdings, mock_cusip_map, client):
        """Second request for same filing should use cache, not re-call provider."""
        from dashboard.routes.filings_13f import _resolved_cache

        # Clear cache for clean test
        _resolved_cache.clear()

        mock_holdings.return_value = [
            {
                "cusip": "037833100",
                "name": "APPLE INC",
                "title": "COM",
                "shares": 100,
                "value": 1000,
            },
        ]
        mock_cusip_map.return_value = {"037833100": "AAPL"}

        # First call — hits provider
        resp1 = await client.get("/api/13f/holdings?cik=999&accession=cached_test")
        assert resp1.status_code == 200
        assert mock_holdings.call_count == 1

        # Second call — should use cache
        resp2 = await client.get("/api/13f/holdings?cik=999&accession=cached_test")
        assert resp2.status_code == 200
        assert mock_holdings.call_count == 1  # NOT called again
        assert resp2.json() == resp1.json()

        _resolved_cache.clear()

    @pytest.mark.asyncio
    @patch(f"{_13F_MODULE}.map_cusips_to_tickers", new_callable=AsyncMock)
    @patch(f"{_13F_MODULE}.get_holdings", new_callable=AsyncMock)
    async def test_holdings_empty_returns_empty(self, mock_holdings, mock_cusip_map, client):
        """Empty holdings from provider returns empty list without calling CUSIP mapper."""
        mock_holdings.return_value = []

        resp = await client.get("/api/13f/holdings?cik=999&accession=empty_test")
        assert resp.status_code == 200
        assert resp.json() == []
        mock_cusip_map.assert_not_called()

    @pytest.mark.asyncio
    @patch(f"{_13F_MODULE}.map_cusips_to_tickers", new_callable=AsyncMock)
    @patch(f"{_13F_MODULE}.get_holdings", new_callable=AsyncMock)
    async def test_get_holdings_download(self, mock_holdings, mock_cusip_map, client):
        mock_holdings.return_value = [
            {
                "cusip": "037833100",
                "name": "APPLE INC",
                "title": "COM",
                "shares": 905560,
                "value": 150_000_000,
            },
        ]
        mock_cusip_map.return_value = {"037833100": "AAPL"}

        resp = await client.get(
            "/api/13f/holdings/download?cik=0001067983&accession=0001234567-25-000001"
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        lines = resp.text.strip().split("\n")
        assert lines[0] == "cusip,ticker,name,title,shares,value,weight_pct"
        assert "AAPL" in lines[1]
        assert "037833100" in lines[1]
