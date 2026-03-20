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


class TestSettingsRoutes:
    @pytest.mark.asyncio
    async def test_get_settings(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        section_ids = [s["id"] for s in data["sections"]]
        assert "scanner" in section_ids
        assert "llm" in section_ids
        assert "broker" in section_ids

    @pytest.mark.asyncio
    async def test_settings_masks_secrets(self, client):
        resp = await client.get("/api/settings")
        data = resp.json()
        # Find broker section
        broker = next(s for s in data["sections"] if s["id"] == "broker")
        api_key_field = next(f for f in broker["fields"] if f["key"] == "t212_api_key")
        assert api_key_field["is_secret"] is True

    @pytest.mark.asyncio
    async def test_update_settings(self, client):
        resp = await client.put("/api/settings", json={
            "settings": [{"key": "scan_interval_seconds", "value": "60"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "scan_interval_seconds" in data["updated"]

    @pytest.mark.asyncio
    async def test_update_persists(self, client):
        await client.put("/api/settings", json={
            "settings": [{"key": "scan_min_volume", "value": "5000"}]
        })
        resp = await client.get("/api/settings")
        data = resp.json()
        scanner = next(s for s in data["sections"] if s["id"] == "scanner")
        vol_field = next(f for f in scanner["fields"] if f["key"] == "scan_min_volume")
        assert vol_field["value"] == "5000"
        assert vol_field["has_db_override"] is True

    @pytest.mark.asyncio
    async def test_delete_setting(self, client):
        # Set then delete
        await client.put("/api/settings", json={
            "settings": [{"key": "log_level", "value": "DEBUG"}]
        })
        resp = await client.delete("/api/settings/log_level")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "log_level"
