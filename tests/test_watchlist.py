"""Tests for Watchlist CRUD API endpoints."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
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
    yf_mock.get_info.return_value = {"name": "Apple Inc."}

    app = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("event_bus", event_bus)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestWatchlistCRUD:
    @pytest.mark.asyncio
    async def test_list_empty_watchlist(self, client):
        resp = await client.get("/api/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_add_to_watchlist(self, client):
        resp = await client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["asset_type"] == "equity"
        assert "id" in data
        assert "added_at" in data

    @pytest.mark.asyncio
    async def test_add_duplicate_returns_409(self, client):
        await client.post("/api/watchlist", json={"ticker": "MSFT"})
        resp = await client.post("/api/watchlist", json={"ticker": "MSFT"})
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"] == "CONFLICT"
        assert "MSFT" in body["message"]

    @pytest.mark.asyncio
    async def test_add_case_insensitive(self, client):
        await client.post("/api/watchlist", json={"ticker": "goog"})
        resp = await client.post("/api/watchlist", json={"ticker": "GOOG"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_list_after_add(self, client):
        await client.post("/api/watchlist", json={"ticker": "TSLA"})
        await client.post("/api/watchlist", json={"ticker": "NVDA"})
        resp = await client.get("/api/watchlist")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_update_notes(self, client):
        await client.post("/api/watchlist", json={"ticker": "META"})
        resp = await client.put("/api/watchlist/META", json={"notes": "Watching for earnings"})
        assert resp.status_code == 200
        assert resp.json()["notes"] == "Watching for earnings"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_404(self, client):
        resp = await client.put("/api/watchlist/XXXX", json={"notes": "test"})
        assert resp.status_code == 404
        assert resp.json()["error"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_from_watchlist(self, client):
        await client.post("/api/watchlist", json={"ticker": "AMZN"})
        resp = await client.delete("/api/watchlist/AMZN")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it's gone
        list_resp = await client.get("/api/watchlist")
        tickers = [item["ticker"] for item in list_resp.json()["items"]]
        assert "AMZN" not in tickers

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/watchlist/XXXX")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_with_custom_asset_type(self, client):
        resp = await client.post(
            "/api/watchlist",
            json={
                "ticker": "BTC-USD",
                "asset_type": "crypto",
                "notes": "Bitcoin tracking",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["asset_type"] == "crypto"
        assert resp.json()["notes"] == "Bitcoin tracking"


class TestWatchlistPagination:
    @pytest.mark.asyncio
    async def test_pagination_metadata(self, client):
        for ticker in ["A", "B", "C", "D", "E"]:
            await client.post("/api/watchlist", json={"ticker": ticker})

        resp = await client.get("/api/watchlist?limit=2&offset=0")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["limit"] == 2
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_pagination_last_page(self, client):
        for ticker in ["X", "Y", "Z"]:
            await client.post("/api/watchlist", json={"ticker": ticker})

        resp = await client.get("/api/watchlist?limit=10&offset=0")
        data = resp.json()
        assert data["total"] == 3
        assert data["has_more"] is False
