"""Tests for Portfolio management API endpoints."""

import pytest
from unittest.mock import AsyncMock
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database


def _make_history(num_days: int, base_price: float = 100.0):
    """Generate a list of price history dicts with ascending dates."""
    from datetime import date, timedelta

    start = date(2024, 1, 2)
    history = []
    for i in range(num_days):
        d = start + timedelta(days=i)
        price = base_price + i * 0.5
        history.append({
            "date": d.isoformat(),
            "open": price - 0.2,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1_000_000 + i * 1000,
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

    yf_mock = AsyncMock()
    yf_mock.get_info.return_value = {"currency": "USD"}
    yf_mock.get_history.return_value = _make_history(40)

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


class TestPortfolioCRUD:
    @pytest.mark.asyncio
    async def test_list_portfolios_empty(self, client):
        resp = await client.get("/api/portfolios")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_portfolio(self, client):
        resp = await client.post("/api/portfolios", json={"name": "My Portfolio"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Portfolio"
        assert "id" in data
        assert "created_at" in data
        assert data["holdings"] == []

    @pytest.mark.asyncio
    async def test_create_duplicate_name_returns_409(self, client):
        await client.post("/api/portfolios", json={"name": "Duplicate"})
        resp = await client.post("/api/portfolios", json={"name": "Duplicate"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_portfolio(self, client):
        create_resp = await client.post("/api/portfolios", json={"name": "To Delete"})
        pid = create_resp.json()["id"]

        resp = await client.delete(f"/api/portfolios/{pid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it's gone
        list_resp = await client.get("/api/portfolios")
        assert all(p["id"] != pid for p in list_resp.json())

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/portfolios/nonexistent_id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_holdings(self, client):
        create_resp = await client.post("/api/portfolios", json={"name": "Holdings Test"})
        pid = create_resp.json()["id"]

        holdings = [
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ]
        resp = await client.put(f"/api/portfolios/{pid}/holdings", json=holdings)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["count"] == 2

        # Verify holdings appear in list
        list_resp = await client.get("/api/portfolios")
        portfolio = [p for p in list_resp.json() if p["id"] == pid][0]
        tickers = {h["ticker"] for h in portfolio["holdings"]}
        assert tickers == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_get_analytics(self, client, app):
        import numpy as np
        import dashboard.routes.portfolio as portfolio_mod

        # Patch numpy into the portfolio module so np.float64 resolves at line 195
        original_np = getattr(portfolio_mod, "np", None)
        portfolio_mod.np = np

        try:
            # Create portfolio with holdings
            create_resp = await client.post(
                "/api/portfolios", json={"name": "Analytics Test"}
            )
            pid = create_resp.json()["id"]

            holdings = [
                {"ticker": "AAPL", "weight": 60},
                {"ticker": "MSFT", "weight": 40},
            ]
            await client.put(f"/api/portfolios/{pid}/holdings", json=holdings)

            # Mock get_history to return overlapping dates for both tickers
            history_aapl = _make_history(40, base_price=150.0)
            history_msft = _make_history(40, base_price=300.0)

            from dashboard.deps import get_yfinance_provider

            yf = get_yfinance_provider()
            yf.get_history.side_effect = lambda t, **kw: (
                history_aapl if t == "AAPL" else history_msft
            )

            resp = await client.get(f"/api/portfolios/{pid}/analytics?period=1y")
            assert resp.status_code == 200
            data = resp.json()
            assert data["portfolio_id"] == pid
            assert data["period"] == "1y"
            # With valid price histories, analytics should be computed
            assert data["annualized_vol"] != 0
            assert "total_return" in data
            assert "sharpe" in data
            assert "sortino" in data
            assert "max_drawdown" in data
            assert "var_95" in data
            assert "cvar_95" in data
        finally:
            if original_np is None:
                delattr(portfolio_mod, "np")
            else:
                portfolio_mod.np = original_np

    @pytest.mark.asyncio
    async def test_get_analytics_empty_holdings(self, client, app):
        import numpy as np
        import dashboard.routes.portfolio as portfolio_mod

        original_np = getattr(portfolio_mod, "np", None)
        portfolio_mod.np = np

        try:
            create_resp = await client.post(
                "/api/portfolios", json={"name": "Empty Analytics"}
            )
            pid = create_resp.json()["id"]

            resp = await client.get(f"/api/portfolios/{pid}/analytics?period=1y")
            assert resp.status_code == 200
            data = resp.json()
            assert data["portfolio_id"] == pid
            assert data["period"] == "1y"
            # All analytics should be zero for empty portfolio
            assert data["total_return"] == 0
            assert data["annualized_vol"] == 0
            assert data["sharpe"] == 0
            assert data["sortino"] == 0
            assert data["max_drawdown"] == 0
        finally:
            if original_np is None:
                delattr(portfolio_mod, "np")
            else:
                portfolio_mod.np = original_np
