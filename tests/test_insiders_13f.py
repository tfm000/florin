"""Tests for Insiders and 13F filing API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
    defaults = dict(
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
    async def test_insiders_basic(
        self, mock_cik, mock_filings, mock_xml, mock_parse, client
    ):
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
            {"cusip": "037833100", "name": "APPLE INC", "title": "COM", "shares": 905560, "value": 150_000_000},
            {"cusip": "594918104", "name": "MICROSOFT CORP", "title": "COM", "shares": 315200, "value": 120_000_000},
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
    async def test_get_holdings_download(self, mock_holdings, mock_cusip_map, client):
        mock_holdings.return_value = [
            {"cusip": "037833100", "name": "APPLE INC", "title": "COM", "shares": 905560, "value": 150_000_000},
        ]
        mock_cusip_map.return_value = {"037833100": "AAPL"}

        resp = await client.get("/api/13f/holdings/download?cik=0001067983&accession=0001234567-25-000001")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        lines = resp.text.strip().split("\n")
        assert lines[0] == "cusip,ticker,name,title,shares,value,weight_pct"
        assert "AAPL" in lines[1]
        assert "037833100" in lines[1]
