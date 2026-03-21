"""Tests for Risk API endpoints."""

import numpy as np
import pytest
from unittest.mock import AsyncMock
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database


def _generate_history(days: int, start_price: float = 100.0) -> list[dict]:
    """Generate synthetic OHLCV history with mild random-walk drift."""
    rng = np.random.default_rng(42)
    history = []
    price = start_price
    for i in range(days):
        ret = rng.normal(0.0005, 0.015)
        price *= 1 + ret
        high = price * (1 + abs(rng.normal(0, 0.005)))
        low = price * (1 - abs(rng.normal(0, 0.005)))
        history.append({
            "date": f"2024-{1 + i // 30:02d}-{1 + i % 28:02d}",
            "open": round(price * 0.999, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(price, 2),
            "volume": 50_000_000 + rng.integers(-5_000_000, 5_000_000),
        })
    return history


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

    # Mock yfinance provider
    yf_mock = AsyncMock()
    yf_mock.get_history.return_value = _generate_history(60)
    yf_mock.get_info.return_value = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "currency": "USD",
        "current_price": 195.50,
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


class TestRiskRate:
    @pytest.mark.asyncio
    async def test_risk_rate_no_fetcher(self, client):
        """When rf_fetcher is None, returns rate=0."""
        resp = await client.get("/api/risk/rate?currency=USD")
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "USD"
        assert data["rate"] == 0.0
        assert data["source"] == "unavailable"


class TestRiskMetrics:
    @pytest.mark.asyncio
    async def test_risk_metrics_basic(self, client):
        """With 60 days of history, returns valid risk metrics."""
        resp = await client.get("/api/risk/AAPL?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["trading_days"] > 0
        assert "historical" in data
        assert "var_95" in data["historical"]
        assert "var_99" in data["historical"]
        assert "cvar_95" in data["historical"]
        assert "cvar_99" in data["historical"]

    @pytest.mark.asyncio
    async def test_risk_metrics_empty_history(self, client):
        """Empty history returns zeros."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        yf_mock.get_history.return_value = []

        resp = await client.get("/api/risk/AAPL?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trading_days"] == 0
        assert data["annualized_return"] == 0
        assert data["annualized_vol"] == 0
        assert data["sharpe"] == 0
        assert data["sortino"] == 0

        # Restore the mock for subsequent tests
        yf_mock.get_history.return_value = _generate_history(60)

    @pytest.mark.asyncio
    async def test_risk_metrics_has_sharpe_and_sortino(self, client):
        """With valid data, sharpe and sortino should be nonzero."""
        resp = await client.get("/api/risk/AAPL?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        # With 60 days of data and a random walk, sharpe/sortino should be nonzero
        assert data["sharpe"] != 0 or data["sortino"] != 0
        assert data["annualized_vol"] > 0

    @pytest.mark.asyncio
    async def test_risk_metrics_custom_dates(self, client):
        """With start/end params, period field reflects the date range."""
        resp = await client.get("/api/risk/AAPL?start=2024-01-01&end=2024-06-01")
        assert resp.status_code == 200
        data = resp.json()
        assert "2024-01-01" in data["period"]
        assert "2024-06-01" in data["period"]
        assert data["trading_days"] > 0
