"""Tests for the dashboard FastAPI routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from db.database import Database


@pytest.fixture
async def app():
    """Create a test app with an in-memory database."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    event_bus = EventBus()

    app = create_app(settings, db, event_bus)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    """AsyncClient for testing the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestUniverseRoutes:
    @pytest.mark.asyncio
    async def test_get_universe_empty(self, client):
        resp = await client.get("/api/universe")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_scanner_settings(self, client):
        resp = await client.get("/api/universe/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "price_threshold" in data
        assert "momentum_threshold" in data
        assert "scan_interval_seconds" in data


class TestReportRoutes:
    @pytest.mark.asyncio
    async def test_get_reports_empty(self, client):
        resp = await client.get("/api/reports")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_report_not_found(self, client):
        resp = await client.get("/api/reports/nonexistent")
        assert resp.status_code == 404


class TestTradeRoutes:
    @pytest.mark.asyncio
    async def test_get_trades_empty(self, client):
        resp = await client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json() == []


class TestStatsRoutes:
    @pytest.mark.asyncio
    async def test_get_stats_empty(self, client):
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0


class TestAccountRoutes:
    @pytest.mark.asyncio
    async def test_get_account_no_broker(self, client):
        """Should return 503 when broker is not configured."""
        resp = await client.get("/api/account")
        assert resp.status_code == 503


class TestPositionRoutes:
    @pytest.mark.asyncio
    async def test_get_positions_no_broker(self, client):
        resp = await client.get("/api/positions")
        assert resp.status_code == 503


class TestOrderRoutes:
    @pytest.mark.asyncio
    async def test_buy_no_broker(self, client):
        resp = await client.post("/api/orders/buy", json={"ticker": "AAPL"})
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_pending_no_broker(self, client):
        resp = await client.get("/api/orders/pending")
        assert resp.status_code == 503
