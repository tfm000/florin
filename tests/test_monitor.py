"""Tests for Live Monitor API endpoints."""

import pytest
from unittest.mock import AsyncMock
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


class TestMonitorCRUD:
    @pytest.mark.asyncio
    async def test_list_empty_monitor(self, client):
        resp = await client.get("/api/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_add_to_monitor(self, client):
        resp = await client.post("/api/monitor", json={"ticker": "AAPL"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["is_active"] is True
        assert data["source"] == "manual"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_add_duplicate_returns_409(self, client):
        await client.post("/api/monitor", json={"ticker": "MSFT"})
        resp = await client.post("/api/monitor", json={"ticker": "MSFT"})
        assert resp.status_code == 409
        assert resp.json()["error"] == "CONFLICT"

    @pytest.mark.asyncio
    async def test_add_case_insensitive(self, client):
        await client.post("/api/monitor", json={"ticker": "goog"})
        resp = await client.post("/api/monitor", json={"ticker": "GOOG"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_list_after_add(self, client):
        await client.post("/api/monitor", json={"ticker": "TSLA"})
        await client.post("/api/monitor", json={"ticker": "NVDA"})
        resp = await client.get("/api/monitor")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_remove_monitored(self, client):
        await client.post("/api/monitor", json={"ticker": "AMZN"})
        resp = await client.delete("/api/monitor/AMZN")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it's deactivated (not deleted)
        list_resp = await client.get("/api/monitor")
        tickers = [item["ticker"] for item in list_resp.json()["items"]]
        assert "AMZN" not in tickers

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/monitor/XXXX")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reactivate_after_removal(self, client):
        # Add, remove, re-add
        await client.post("/api/monitor", json={"ticker": "META"})
        await client.delete("/api/monitor/META")

        resp = await client.post("/api/monitor", json={"ticker": "META"})
        assert resp.status_code == 201
        assert resp.json()["is_active"] is True


class TestMonitorPagination:
    @pytest.mark.asyncio
    async def test_pagination_metadata(self, client):
        for ticker in ["A", "B", "C", "D", "E"]:
            await client.post("/api/monitor", json={"ticker": ticker})

        resp = await client.get("/api/monitor?limit=2&offset=0")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["has_more"] is True

    @pytest.mark.asyncio
    async def test_pagination_last_page(self, client):
        for ticker in ["X", "Y", "Z"]:
            await client.post("/api/monitor", json={"ticker": ticker})

        resp = await client.get("/api/monitor?limit=10&offset=0")
        data = resp.json()
        assert data["total"] == 3
        assert data["has_more"] is False


class TestMonitorLiveData:
    @pytest.mark.asyncio
    async def test_response_includes_live_data_fields(self, client):
        await client.post("/api/monitor", json={"ticker": "SPY"})
        resp = await client.get("/api/monitor")
        item = resp.json()["items"][0]
        # Fields should exist even if null (no data provider)
        assert "current_price" in item
        assert "change_pct" in item
        assert "volume" in item
