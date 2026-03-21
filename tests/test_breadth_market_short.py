"""Tests for Breadth, Market Hours, and Short Interest API endpoints."""

from datetime import datetime, timedelta

import pytest
from unittest.mock import AsyncMock
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database
from db.models import BreadthSnapshotORM


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
    yf_mock.get_info.return_value = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "short_interest": 0.035,
        "shares_outstanding": 15_000_000_000,
    }

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


# ---- helpers ----------------------------------------------------------------

async def _seed_breadth(app, rows: list[dict]) -> None:
    """Insert BreadthSnapshotORM rows into the in-memory DB."""
    from dashboard.deps import get_db

    db = get_db()
    async with db.session() as session:
        for row in rows:
            session.add(BreadthSnapshotORM(**row))
        await session.commit()


# =============================================================================
# Breadth routes
# =============================================================================

class TestBreadthLatest:
    @pytest.mark.asyncio
    async def test_breadth_latest_from_db(self, client, app):
        """Seeded DB snapshot is returned by GET /api/breadth."""
        await _seed_breadth(app, [
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "hour": 12,
                "advancing": 1800,
                "declining": 1200,
                "unchanged": 100,
                "total": 3100,
                "ad_ratio": 1.5,
                "recorded_at": datetime.now(),
            },
        ])

        resp = await client.get("/api/breadth")
        assert resp.status_code == 200
        data = resp.json()
        assert data["advancing"] == 1800
        assert data["declining"] == 1200
        assert data["unchanged"] == 100
        assert data["total_stocks"] == 3100
        assert data["advance_decline_ratio"] == 1.5
        assert data["pct_advancing"] == pytest.approx(58.1, abs=0.1)


class TestBreadthHistory:
    @pytest.mark.asyncio
    async def test_breadth_history(self, client, app):
        """Multiple snapshots on different dates are returned by history endpoint."""
        today = datetime.now()
        rows = []
        for i in range(5):
            d = today - timedelta(days=i)
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "hour": 10,
                "advancing": 1500 + i * 50,
                "declining": 1400 - i * 30,
                "unchanged": 80,
                "total": 2980 + i * 20,
                "ad_ratio": round((1500 + i * 50) / max(1, 1400 - i * 30), 2),
                "recorded_at": d,
            })
        await _seed_breadth(app, rows)

        resp = await client.get("/api/breadth/history?days=30")
        assert resp.status_code == 200
        data = resp.json()
        snapshots = data["snapshots"]
        assert len(snapshots) == 5
        # Should be ordered by date ascending
        dates = [s["date"] for s in snapshots]
        assert dates == sorted(dates)
        # Verify structure
        for s in snapshots:
            assert "advancing" in s
            assert "declining" in s
            assert "total" in s
            assert "ad_ratio" in s
            assert "hour" in s

    @pytest.mark.asyncio
    async def test_breadth_history_empty(self, client):
        """No snapshots in DB returns an empty list."""
        resp = await client.get("/api/breadth/history?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []


# =============================================================================
# Market hours routes
# =============================================================================

class TestMarketHours:
    @pytest.mark.asyncio
    async def test_market_hours_returns_markets(self, client):
        """GET /api/market/hours returns a markets list with expected fields."""
        resp = await client.get("/api/market/hours")
        assert resp.status_code == 200
        data = resp.json()
        assert "markets" in data
        assert "utc_now" in data
        markets = data["markets"]
        assert len(markets) > 0
        for m in markets:
            assert "name" in m
            assert "is_open" in m
            assert isinstance(m["is_open"], bool)
            assert "timezone" in m


class TestMarketStatus:
    @pytest.mark.asyncio
    async def test_market_status_known_exchange(self, client):
        """GET /api/market/status/NMS returns a valid NYSE/NASDAQ response."""
        resp = await client.get("/api/market/status/NMS")
        assert resp.status_code == 200
        data = resp.json()
        assert data["market_name"] == "NYSE / NASDAQ"
        assert isinstance(data["is_open"], bool)
        assert "local_time" in data
        assert "opens" in data
        assert "closes" in data

    @pytest.mark.asyncio
    async def test_market_status_unknown_exchange(self, client):
        """Unknown exchange falls back to NYSE / NASDAQ."""
        resp = await client.get("/api/market/status/ZZZZZ")
        assert resp.status_code == 200
        data = resp.json()
        # The route defaults unknown exchanges to NYSE / NASDAQ
        assert data["market_name"] == "NYSE / NASDAQ"
        assert isinstance(data["is_open"], bool)


# =============================================================================
# Short interest routes
# =============================================================================

class TestShortInterest:
    @pytest.mark.asyncio
    async def test_short_interest_basic(self, client):
        """GET /api/short-interest/AAPL returns short data from mocked yfinance."""
        resp = await client.get("/api/short-interest/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["short_percent_of_float"] == 0.035
        assert data["shares_outstanding"] == 15_000_000_000

    @pytest.mark.asyncio
    async def test_short_interest_no_data(self, client):
        """When get_info returns empty dict, response handles gracefully."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        original = yf_mock.get_info.return_value
        yf_mock.get_info.return_value = {}

        resp = await client.get("/api/short-interest/XYZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "XYZ"
        assert data["short_percent_of_float"] is None
        assert data["shares_short"] is None
        assert data["shares_outstanding"] is None

        # Restore
        yf_mock.get_info.return_value = original
