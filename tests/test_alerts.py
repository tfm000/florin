"""Tests for Price Alert CRUD API endpoints."""

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
    await db.create_tables()
    event_bus = EventBus()

    yf_mock = AsyncMock()
    yf_mock.get_info.return_value = {"currency": "USD"}
    yf_mock.get_history.return_value = []

    app = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("event_bus", event_bus)
    set_state("rf_fetcher", None)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAlertsCRUD:
    @pytest.mark.asyncio
    async def test_list_alerts_empty(self, client):
        resp = await client.get("/api/alerts")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_alert(self, client):
        resp = await client.post("/api/alerts", json={
            "ticker": "AAPL",
            "direction": "above",
            "target_price": 200.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["direction"] == "above"
        assert data["target_price"] == 200.0
        assert data["is_active"] is True
        assert data["triggered"] is False
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_alert_uppercase_ticker(self, client):
        resp = await client.post("/api/alerts", json={
            "ticker": "msft",
            "direction": "below",
            "target_price": 350.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "MSFT"

    @pytest.mark.asyncio
    async def test_delete_alert(self, client):
        create_resp = await client.post("/api/alerts", json={
            "ticker": "GOOG",
            "direction": "above",
            "target_price": 150.0,
        })
        alert_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/alerts/{alert_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it's gone
        list_resp = await client.get("/api/alerts?active_only=false")
        ids = [a["id"] for a in list_resp.json()]
        assert alert_id not in ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/alerts/nonexistent_id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_filters_active_only(self, client):
        # Create two alerts
        resp1 = await client.post("/api/alerts", json={
            "ticker": "AAPL",
            "direction": "above",
            "target_price": 200.0,
        })
        resp2 = await client.post("/api/alerts", json={
            "ticker": "TSLA",
            "direction": "below",
            "target_price": 100.0,
        })
        assert resp1.status_code == 201
        assert resp2.status_code == 201

        # Both are active — active_only=true should return both
        active_resp = await client.get("/api/alerts?active_only=true")
        assert active_resp.status_code == 200
        assert len(active_resp.json()) == 2

        # active_only=false should also return both (no inactive ones exist)
        all_resp = await client.get("/api/alerts?active_only=false")
        assert all_resp.status_code == 200
        assert len(all_resp.json()) == 2

        # Default (no param) should filter to active only
        default_resp = await client.get("/api/alerts")
        assert default_resp.status_code == 200
        assert len(default_resp.json()) == 2
