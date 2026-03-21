"""Tests for GET /api/stats/returns/{ticker} endpoint."""

import pytest
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database


def _make_history(prices, start_date="2024-01-02"):
    """Build a list of history dicts from a list of close prices."""
    from datetime import datetime, timedelta

    base = datetime.strptime(start_date, "%Y-%m-%d")
    result = []
    for i, close in enumerate(prices):
        d = base + timedelta(days=i)
        result.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": close * 0.998,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 50_000_000,
        })
    return result


def _generate_realistic_history(n=30, start=100.0, drift=0.001, seed=42):
    """Generate n days of realistic random-walk prices."""
    import numpy as np

    rng = np.random.RandomState(seed)
    daily = rng.normal(drift, 0.02, n)
    prices = [start]
    for r in daily:
        prices.append(prices[-1] * (1 + r))
    return _make_history(prices)


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
    yf_mock.get_history.return_value = _generate_realistic_history(30)
    yf_mock.get_info.return_value = {"currency": "USD"}

    application = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("rf_fetcher", None)
    yield application, yf_mock
    await db.close()


@pytest.fixture
async def client(app):
    application, _ = app
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def yf_mock(app):
    _, mock = app
    return mock


EXPECTED_FIELDS = {
    "ticker", "period", "trading_days", "total_return",
    "annualized_return", "annualized_volatility", "sharpe",
    "max_drawdown", "mean_daily_pct", "std_dev_daily_pct",
    "skewness", "excess_kurtosis", "var_95_pct", "cvar_95_pct",
}


class TestReturnsStats:
    @pytest.mark.asyncio
    async def test_returns_stats_basic(self, client):
        resp = await client.get("/api/stats/returns/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == EXPECTED_FIELDS
        assert data["ticker"] == "AAPL"
        assert data["trading_days"] > 0
        assert isinstance(data["total_return"], (int, float))
        assert isinstance(data["sharpe"], (int, float))

    @pytest.mark.asyncio
    async def test_returns_stats_empty_history(self, client, yf_mock):
        yf_mock.get_history.return_value = []
        resp = await client.get("/api/stats/returns/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trading_days"] == 0
        assert data["total_return"] == 0
        assert data["annualized_return"] == 0
        assert data["sharpe"] == 0

    @pytest.mark.asyncio
    async def test_returns_stats_single_point(self, client, yf_mock):
        yf_mock.get_history.return_value = _make_history([100.0])
        resp = await client.get("/api/stats/returns/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trading_days"] == 0
        assert data["total_return"] == 0
        assert data["sharpe"] == 0

    @pytest.mark.asyncio
    async def test_returns_stats_positive_return(self, client, yf_mock):
        # Steadily increasing prices: 100 → 110 over 20 days
        prices = [100.0 + i * 0.5 for i in range(21)]
        yf_mock.get_history.return_value = _make_history(prices)
        resp = await client.get("/api/stats/returns/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_return"] > 0

    @pytest.mark.asyncio
    async def test_returns_stats_negative_return(self, client, yf_mock):
        # Steadily decreasing prices: 100 → 90 over 20 days
        prices = [100.0 - i * 0.5 for i in range(21)]
        yf_mock.get_history.return_value = _make_history(prices)
        resp = await client.get("/api/stats/returns/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_return"] < 0

    @pytest.mark.asyncio
    async def test_returns_stats_sharpe_nonzero(self, client, yf_mock):
        # Use enough data with drift for nonzero Sharpe
        yf_mock.get_history.return_value = _generate_realistic_history(
            n=60, start=100.0, drift=0.002, seed=99,
        )
        resp = await client.get("/api/stats/returns/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sharpe"] != 0

    @pytest.mark.asyncio
    async def test_returns_stats_custom_dates(self, client, yf_mock):
        yf_mock.get_history.return_value = _generate_realistic_history(20)
        resp = await client.get(
            "/api/stats/returns/AAPL?start=2024-01-02&end=2024-02-01"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "2024-01-02" in data["period"]
        assert "2024-02-01" in data["period"]
        # Verify yf mock was called with start/end kwargs
        yf_mock.get_history.assert_called_with(
            "AAPL", start="2024-01-02", end="2024-02-01",
        )
