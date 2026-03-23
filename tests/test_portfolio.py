"""Tests for Portfolio management API endpoints."""

import sys
import types

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
    async def test_create_portfolio_with_group(self, client):
        resp = await client.post("/api/portfolios", json={"name": "13F Test", "group": "13F"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "13F Test"
        assert data["group"] == "13F"

    @pytest.mark.asyncio
    async def test_create_portfolio_without_group(self, client):
        resp = await client.post("/api/portfolios", json={"name": "No Group"})
        assert resp.status_code == 201
        assert resp.json()["group"] is None

    @pytest.mark.asyncio
    async def test_list_portfolios_includes_group(self, client):
        await client.post("/api/portfolios", json={"name": "Ungrouped"})
        await client.post("/api/portfolios", json={"name": "Grouped", "group": "13F"})
        resp = await client.get("/api/portfolios")
        data = resp.json()
        assert len(data) == 2
        grouped = next(p for p in data if p["name"] == "Grouped")
        ungrouped = next(p for p in data if p["name"] == "Ungrouped")
        assert grouped["group"] == "13F"
        assert ungrouped["group"] is None

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
    async def test_delete_13f_portfolio_with_holdings(self, client):
        """13F portfolios can be deleted along with their holdings."""
        create_resp = await client.post("/api/portfolios", json={
            "name": "13F Delete Test", "group": "13F",
        })
        pid = create_resp.json()["id"]

        # Add holdings (initial population is allowed for 13F)
        holdings = [
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ]
        await client.put(f"/api/portfolios/{pid}/holdings", json=holdings)

        # Delete should succeed
        resp = await client.delete(f"/api/portfolios/{pid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify portfolio and holdings are gone
        list_resp = await client.get("/api/portfolios")
        assert all(p["id"] != pid for p in list_resp.json())

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

    # ---- Description field ----

    @pytest.mark.asyncio
    async def test_create_portfolio_with_description(self, client):
        resp = await client.post("/api/portfolios", json={
            "name": "Desc Test", "description": "A portfolio for testing",
        })
        assert resp.status_code == 201
        assert resp.json()["description"] == "A portfolio for testing"

    @pytest.mark.asyncio
    async def test_list_includes_description(self, client):
        await client.post("/api/portfolios", json={
            "name": "Desc List", "description": "my desc",
        })
        resp = await client.get("/api/portfolios")
        p = next(p for p in resp.json() if p["name"] == "Desc List")
        assert p["description"] == "my desc"

    @pytest.mark.asyncio
    async def test_create_portfolio_description_default_null(self, client):
        resp = await client.post("/api/portfolios", json={"name": "No Desc"})
        assert resp.status_code == 201
        assert resp.json()["description"] is None

    # ---- PUT /portfolios/{id} ----

    @pytest.mark.asyncio
    async def test_update_description(self, client):
        create = await client.post("/api/portfolios", json={"name": "Update Desc"})
        pid = create.json()["id"]
        resp = await client.put(f"/api/portfolios/{pid}", json={"description": "Updated!"})
        assert resp.status_code == 200
        # Verify it persisted
        listing = await client.get("/api/portfolios")
        p = next(p for p in listing.json() if p["id"] == pid)
        assert p["description"] == "Updated!"

    @pytest.mark.asyncio
    async def test_update_name(self, client):
        create = await client.post("/api/portfolios", json={"name": "Old Name"})
        pid = create.json()["id"]
        resp = await client.put(f"/api/portfolios/{pid}", json={"name": "New Name"})
        assert resp.status_code == 200
        listing = await client.get("/api/portfolios")
        p = next(p for p in listing.json() if p["id"] == pid)
        assert p["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_404(self, client):
        resp = await client.put("/api/portfolios/fake_id", json={"description": "x"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_13f_portfolio_name_change_rejected(self, client):
        """13F portfolios cannot have their name changed."""
        create = await client.post("/api/portfolios", json={
            "name": "13F Locked", "group": "13F",
        })
        pid = create.json()["id"]
        resp = await client.put(f"/api/portfolios/{pid}", json={"name": "Renamed"})
        assert resp.status_code == 403
        assert "13F" in resp.json()["detail"]
        # Name should be unchanged
        listing = await client.get("/api/portfolios")
        p = next(p for p in listing.json() if p["id"] == pid)
        assert p["name"] == "13F Locked"

    @pytest.mark.asyncio
    async def test_13f_portfolio_description_editable(self, client):
        """13F portfolios CAN have their description changed."""
        create = await client.post("/api/portfolios", json={
            "name": "13F Desc Edit", "group": "13F",
        })
        pid = create.json()["id"]
        resp = await client.put(f"/api/portfolios/{pid}", json={"description": "Notes"})
        assert resp.status_code == 200
        listing = await client.get("/api/portfolios")
        p = next(p for p in listing.json() if p["id"] == pid)
        assert p["description"] == "Notes"

    # ---- 13F holdings restriction ----

    @pytest.mark.asyncio
    async def test_13f_portfolio_initial_holdings_allowed(self, client):
        """13F portfolios allow initial holdings population (empty → populated)."""
        create = await client.post("/api/portfolios", json={
            "name": "13F Initial", "group": "13F",
        })
        pid = create.json()["id"]
        resp = await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    @pytest.mark.asyncio
    async def test_13f_portfolio_holdings_modification_rejected(self, client):
        """13F portfolios cannot have their holdings modified after initial population."""
        create = await client.post("/api/portfolios", json={
            "name": "13F No Edit", "group": "13F",
        })
        pid = create.json()["id"]
        # Initial population — allowed
        resp1 = await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])
        assert resp1.status_code == 200
        # Subsequent modification — blocked
        resp2 = await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "MSFT", "weight": 50}, {"ticker": "GOOG", "weight": 50},
        ])
        assert resp2.status_code == 403
        assert "13F" in resp2.json()["detail"]

    # ---- GET /portfolios/{id}/holdings-info ----

    @pytest.mark.asyncio
    async def test_holdings_info_empty(self, client):
        create = await client.post("/api/portfolios", json={"name": "Empty Info"})
        pid = create.json()["id"]
        resp = await client.get(f"/api/portfolios/{pid}/holdings-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert data["holdings"] == []
        assert data["weighted_pe"] is None

    @pytest.mark.asyncio
    async def test_holdings_info_with_data(self, client):
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        # Mock get_info to return different data per ticker
        def mock_info(ticker):
            info = {
                "AAPL": {"sector": "Technology", "industry": "Consumer Electronics",
                         "pe_ratio": 30.0, "forward_pe": 28.0, "dividend_yield": 0.005,
                         "beta": 1.2, "market_cap": 3e12, "current_price": 195.0},
                "MSFT": {"sector": "Technology", "industry": "Software",
                         "pe_ratio": 35.0, "forward_pe": 32.0, "dividend_yield": 0.008,
                         "beta": 0.9, "market_cap": 2.8e12, "current_price": 420.0},
            }
            return info.get(ticker, {})

        yf_mock.get_info.side_effect = mock_info

        create = await client.post("/api/portfolios", json={"name": "Info Test"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/holdings-info")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["holdings"]) == 2

        aapl = next(h for h in data["holdings"] if h["ticker"] == "AAPL")
        assert aapl["sector"] == "Technology"
        assert aapl["industry"] == "Consumer Electronics"
        assert aapl["pe_ratio"] == 30.0
        assert aapl["current_price"] == 195.0
        assert aapl["weight"] == 60.0

        msft = next(h for h in data["holdings"] if h["ticker"] == "MSFT")
        assert msft["sector"] == "Technology"
        assert msft["industry"] == "Software"

        # Weighted PE: (0.6*30 + 0.4*35) = 32.0
        assert data["weighted_pe"] == pytest.approx(32.0, abs=0.1)
        # Weighted Forward PE: (0.6*28 + 0.4*32) = 29.6
        assert data["weighted_forward_pe"] == pytest.approx(29.6, abs=0.1)
        # Weighted Beta: (0.6*1.2 + 0.4*0.9) = 1.08
        assert data["weighted_beta"] == pytest.approx(1.08, abs=0.01)
        # Weighted Dividend Yield: (0.6*0.005 + 0.4*0.008) = 0.0062
        assert data["weighted_dividend_yield"] == pytest.approx(0.0062, abs=0.0001)

        # Restore mock
        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = {"currency": "USD"}

    @pytest.mark.asyncio
    async def test_holdings_info_weighted_avg_excludes_nulls(self, client):
        """Weighted averages skip holdings where the metric is null."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        def mock_info(ticker):
            if ticker == "AAPL":
                return {"pe_ratio": 30.0, "beta": 1.2, "sector": "Tech"}
            return {"sector": "Finance"}  # No PE or beta

        yf_mock.get_info.side_effect = mock_info

        create = await client.post("/api/portfolios", json={"name": "Null Avg"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "JPM", "weight": 40},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/holdings-info")
        data = resp.json()
        # Only AAPL has PE, so weighted PE = AAPL's PE (renormalized)
        assert data["weighted_pe"] == pytest.approx(30.0, abs=0.1)
        assert data["weighted_beta"] == pytest.approx(1.2, abs=0.01)

        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = {"currency": "USD"}

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
    async def test_analytics_values_nonzero(self, client, app):
        """With valid history, analytics values should be nonzero and reasonable."""
        import numpy as np
        import dashboard.routes.portfolio as portfolio_mod

        original_np = getattr(portfolio_mod, "np", None)
        portfolio_mod.np = np

        try:
            create_resp = await client.post(
                "/api/portfolios", json={"name": "Values Test"}
            )
            pid = create_resp.json()["id"]
            await client.put(f"/api/portfolios/{pid}/holdings", json=[
                {"ticker": "AAPL", "weight": 100},
            ])

            from dashboard.deps import get_yfinance_provider
            yf = get_yfinance_provider()
            yf.get_history.side_effect = lambda t, **kw: _make_history(40, base_price=100.0)

            resp = await client.get(f"/api/portfolios/{pid}/analytics?period=1y")
            assert resp.status_code == 200
            data = resp.json()
            # With valid history, analytics should be computed (non-zero)
            assert data["total_return"] != 0
            assert data["annualized_vol"] > 0
            assert data["sharpe"] != 0
            assert data["max_drawdown"] >= 0
            # VaR and CVaR should be computed (non-zero)
            assert data["var_95"] != 0
            assert data["cvar_95"] != 0
            assert data["cvar_95"] <= data["var_95"]
        finally:
            if original_np is None:
                delattr(portfolio_mod, "np")
            else:
                portfolio_mod.np = original_np

    @pytest.mark.asyncio
    async def test_analytics_nonexistent_portfolio(self, client, app):
        """Analytics for a non-existent portfolio returns zeros."""
        import numpy as np
        import dashboard.routes.portfolio as portfolio_mod

        original_np = getattr(portfolio_mod, "np", None)
        portfolio_mod.np = np

        try:
            resp = await client.get("/api/portfolios/nonexistent_id/analytics?period=1y")
            assert resp.status_code == 200
            data = resp.json()
            assert data["portfolio_id"] == "nonexistent_id"
            assert data["total_return"] == 0
            assert data["sharpe"] == 0
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


# ---------------------------------------------------------------------------
# Portfolio returns endpoint
# ---------------------------------------------------------------------------

class TestPortfolioReturns:
    @pytest.mark.asyncio
    async def test_returns_basic(self, client):
        """Returns endpoint produces a cumulative return time series."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]
        yf_mock.get_history.side_effect = lambda t, **kw: _make_history(40, base_price=100.0)

        create = await client.post("/api/portfolios", json={"name": "Returns Basic"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/returns?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert isinstance(data["returns"], list)
        assert len(data["returns"]) > 0

        # Each point has date and portfolio fields
        pt = data["returns"][0]
        assert "date" in pt
        assert "portfolio" in pt

        # First point should be 0% (or close) since it's the start
        assert data["returns"][0]["portfolio"] == 0.0

        # Last point should be positive (prices go up in _make_history)
        assert data["returns"][-1]["portfolio"] > 0

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)

    @pytest.mark.asyncio
    async def test_returns_empty_holdings(self, client):
        """Empty portfolio returns empty returns list."""
        create = await client.post("/api/portfolios", json={"name": "Empty Returns"})
        pid = create.json()["id"]

        resp = await client.get(f"/api/portfolios/{pid}/returns?period=1y")
        assert resp.status_code == 200
        assert resp.json()["returns"] == []

    @pytest.mark.asyncio
    async def test_returns_prorated(self, client):
        """Prorated mode includes dates where some holdings are missing."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        # AAPL has 40 days, MSFT has only 20 (shorter)
        history_aapl = _make_history(40, base_price=100.0)
        history_msft = _make_history(20, base_price=200.0)

        yf_mock.get_history.side_effect = lambda t, **kw: (
            history_aapl if t == "AAPL" else history_msft
        )

        create = await client.post("/api/portfolios", json={"name": "Prorated"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        # Non-prorated: only overlapping dates
        resp_normal = await client.get(f"/api/portfolios/{pid}/returns?period=1y&prorated=false")
        normal_len = len(resp_normal.json()["returns"])

        # Prorated: all available dates
        resp_prorated = await client.get(f"/api/portfolios/{pid}/returns?period=1y&prorated=true")
        prorated_len = len(resp_prorated.json()["returns"])

        # Prorated should have more dates since it includes AAPL-only dates
        assert prorated_len >= normal_len

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)

    @pytest.mark.asyncio
    async def test_returns_start_end(self, client):
        """Returns endpoint accepts start/end params."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        call_args = []
        async def mock_hist(t, **kw):
            call_args.append(kw)
            return _make_history(40, base_price=100.0)

        yf_mock.get_history.side_effect = mock_hist

        create = await client.post("/api/portfolios", json={"name": "Returns Range"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(
            f"/api/portfolios/{pid}/returns?start=2024-01-01&end=2024-06-01"
        )
        assert resp.status_code == 200
        assert any(kw.get("start") == "2024-01-01" for kw in call_args)

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)


# ---------------------------------------------------------------------------
# Holdings info — per-holding return and volatility
# ---------------------------------------------------------------------------

class TestHoldingsInfoReturnVol:
    @pytest.mark.asyncio
    async def test_holdings_info_includes_return_and_vol(self, client):
        """Per-holding period_return and period_vol are computed from history."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        yf_mock.get_info.side_effect = lambda t: {"sector": "Tech", "industry": "Software"}
        yf_mock.get_history.side_effect = lambda t, **kw: _make_history(40, base_price=100.0)

        create = await client.post("/api/portfolios", json={"name": "RetVol Test"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/holdings-info")
        assert resp.status_code == 200
        data = resp.json()
        h = data["holdings"][0]
        assert h["period_return"] is not None
        assert h["period_return"] > 0  # prices go up in _make_history
        assert h["period_vol"] is not None
        assert h["period_vol"] > 0

        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = {"currency": "USD"}
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)

    @pytest.mark.asyncio
    async def test_holdings_info_period_param(self, client):
        """Period query param is passed to history fetch."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        call_args = []
        async def mock_hist(t, **kw):
            call_args.append(kw)
            return _make_history(20, base_price=100.0)

        yf_mock.get_info.side_effect = lambda t: {"sector": "Tech"}
        yf_mock.get_history.side_effect = mock_hist

        create = await client.post("/api/portfolios", json={"name": "Period Param"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/holdings-info?period=3m")
        assert resp.status_code == 200
        # Verify period was passed through
        assert any(kw.get("period") == "3m" for kw in call_args)

        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = {"currency": "USD"}
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)

    @pytest.mark.asyncio
    async def test_holdings_info_start_end_params(self, client):
        """Custom start/end range is passed to history fetch."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        call_args = []
        async def mock_hist(t, **kw):
            call_args.append(kw)
            return _make_history(20, base_price=100.0)

        yf_mock.get_info.side_effect = lambda t: {"sector": "Tech"}
        yf_mock.get_history.side_effect = mock_hist

        create = await client.post("/api/portfolios", json={"name": "StartEnd"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(
            f"/api/portfolios/{pid}/holdings-info?start=2024-01-01&end=2024-06-01"
        )
        assert resp.status_code == 200
        assert any(kw.get("start") == "2024-01-01" for kw in call_args)

        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = {"currency": "USD"}
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)

    @pytest.mark.asyncio
    async def test_holdings_info_short_history_returns_null(self, client):
        """Holdings with < 2 data points get null return/vol."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        yf_mock.get_info.side_effect = lambda t: {"sector": "Tech"}
        yf_mock.get_history.side_effect = lambda t, **kw: _make_history(1)

        create = await client.post("/api/portfolios", json={"name": "Short Hist"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/holdings-info")
        data = resp.json()
        h = data["holdings"][0]
        assert h["period_return"] is None
        assert h["period_vol"] is None

        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = {"currency": "USD"}
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)


# ---------------------------------------------------------------------------
# Analytics — start/end custom date range
# ---------------------------------------------------------------------------

class TestAnalyticsCustomRange:
    @pytest.mark.asyncio
    async def test_analytics_with_start_end(self, client, app):
        """Analytics endpoint accepts start/end custom date range."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        call_args = []
        async def mock_hist(t, **kw):
            call_args.append(kw)
            return _make_history(40, base_price=100.0)

        yf_mock.get_history.side_effect = mock_hist

        create = await client.post("/api/portfolios", json={"name": "Custom Range"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(
            f"/api/portfolios/{pid}/analytics?start=2024-01-01&end=2024-06-01"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert data["annualized_vol"] != 0
        # Verify start/end was passed through
        assert any(kw.get("start") == "2024-01-01" for kw in call_args)

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)


# ---------------------------------------------------------------------------
# Portfolio regime endpoint
# ---------------------------------------------------------------------------

def _ensure_statsmodels_modules():
    """Ensure mock statsmodels module hierarchy exists for patching."""
    modules = [
        "statsmodels",
        "statsmodels.tsa",
        "statsmodels.tsa.regime_switching",
        "statsmodels.tsa.regime_switching.markov_regression",
    ]
    for name in modules:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
    sys.modules["statsmodels"].tsa = sys.modules["statsmodels.tsa"]
    sys.modules["statsmodels.tsa"].regime_switching = sys.modules["statsmodels.tsa.regime_switching"]
    mreg = sys.modules["statsmodels.tsa.regime_switching.markov_regression"]
    sys.modules["statsmodels.tsa.regime_switching"].markov_regression = mreg
    mreg.MarkovRegression = MagicMock()


def _make_random_history(num_days: int, base_price: float = 100.0, seed: int = 42):
    """Generate random-walk history for regime testing (ending today)."""
    rng = np.random.default_rng(seed)
    from datetime import date, timedelta
    start = date.today() - timedelta(days=num_days - 1)
    history = []
    price = base_price
    for i in range(num_days):
        d = start + timedelta(days=i)
        ret = rng.normal(0.0005, 0.015)
        price *= 1 + ret
        history.append({
            "date": d.isoformat(),
            "open": round(price * 0.999, 2),
            "high": round(price * 1.005, 2),
            "low": round(price * 0.995, 2),
            "close": round(price, 2),
            "volume": 1_000_000,
        })
    return history


class TestPortfolioRegime:
    @pytest.mark.asyncio
    async def test_portfolio_regime_basic(self, client):
        """Portfolio regime endpoint returns valid regime structure."""
        _ensure_statsmodels_modules()
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        history = _make_random_history(200)
        yf_mock.get_history.side_effect = lambda t, **kw: history
        yf_mock.get_histories_batch.return_value = {"AAPL": history, "MSFT": history}

        create = await client.post("/api/portfolios", json={"name": "Regime Test"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        # Mock MarkovRegression result
        n_obs = 199  # 200 common dates -> 199 returns
        mock_probs = np.zeros((n_obs, 2))
        for i in range(n_obs):
            regime = 0 if (i // 50) % 2 == 0 else 1
            mock_probs[i, regime] = 0.95
            mock_probs[i, 1 - regime] = 0.05

        mock_result = MagicMock()
        mock_result.smoothed_marginal_probabilities = mock_probs
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result

        with patch(
            "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
            return_value=mock_model,
        ):
            resp = await client.get(f"/api/portfolios/{pid}/regime")

        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert data["n_regimes"] == 2
        assert isinstance(data["regimes"], list)
        assert len(data["regimes"]) > 0
        assert isinstance(data["stats"], list)
        assert len(data["stats"]) == 2

        # Verify regime point structure
        r = data["regimes"][0]
        assert "date" in r
        assert "regime" in r
        assert "probability" in r

        # Verify stats structure
        s = data["stats"][0]
        assert "regime" in s
        assert "mean_return" in s
        assert "volatility" in s
        assert "count" in s

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)
        yf_mock.get_histories_batch.side_effect = None

    @pytest.mark.asyncio
    async def test_portfolio_regime_insufficient_data(self, client):
        """Short portfolio history returns empty regimes."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        short_hist = _make_history(5)
        yf_mock.get_history.side_effect = lambda t, **kw: short_hist
        yf_mock.get_histories_batch.return_value = {"AAPL": short_hist}

        create = await client.post("/api/portfolios", json={"name": "Short Regime"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regimes"] == []
        assert data["stats"] == []

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)
        yf_mock.get_histories_batch.side_effect = None

    @pytest.mark.asyncio
    async def test_portfolio_regime_empty_holdings(self, client):
        """Portfolio with no holdings returns empty regime response."""
        create = await client.post("/api/portfolios", json={"name": "Empty Regime"})
        pid = create.json()["id"]

        resp = await client.get(f"/api/portfolios/{pid}/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert data["regimes"] == []
        assert data["stats"] == []

    @pytest.mark.asyncio
    async def test_portfolio_regime_3_regimes(self, client):
        """Portfolio regime with n_regimes=3 returns 3 stats."""
        _ensure_statsmodels_modules()
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        history = _make_random_history(200)
        yf_mock.get_history.side_effect = lambda t, **kw: history
        yf_mock.get_histories_batch.return_value = {"AAPL": history}

        create = await client.post("/api/portfolios", json={"name": "3 Regime"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 100},
        ])

        n_obs = 199
        mock_probs = np.zeros((n_obs, 3))
        for i in range(n_obs):
            regime = i % 3
            mock_probs[i, regime] = 0.90
            for j in range(3):
                if j != regime:
                    mock_probs[i, j] = 0.05

        mock_result = MagicMock()
        mock_result.smoothed_marginal_probabilities = mock_probs
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result

        with patch(
            "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
            return_value=mock_model,
        ):
            resp = await client.get(f"/api/portfolios/{pid}/regime?n_regimes=3")

        assert resp.status_code == 200
        data = resp.json()
        assert data["n_regimes"] == 3
        assert len(data["stats"]) == 3

        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)
        yf_mock.get_histories_batch.side_effect = None


# ---------------------------------------------------------------------------
# Shared regime function unit tests
# ---------------------------------------------------------------------------

class TestFitMarkovRegimes:
    def test_fit_markov_regimes_too_short(self):
        """Returns None when fewer than 30 data points."""
        from stats.regime import fit_markov_regimes
        result = fit_markov_regimes(
            np.random.randn(10), [f"2024-01-{i+1:02d}" for i in range(10)],
        )
        assert result is None

    def test_fit_markov_regimes_with_mock(self):
        """Valid data with mocked MarkovRegression returns correct structure."""
        _ensure_statsmodels_modules()

        n_obs = 100
        mock_probs = np.zeros((n_obs, 2))
        for i in range(n_obs):
            regime = 0 if i < 50 else 1
            mock_probs[i, regime] = 0.95
            mock_probs[i, 1 - regime] = 0.05

        mock_result = MagicMock()
        mock_result.smoothed_marginal_probabilities = mock_probs
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result

        from stats.regime import fit_markov_regimes
        dates = [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n_obs)]

        with patch(
            "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
            return_value=mock_model,
        ):
            result = fit_markov_regimes(np.random.randn(n_obs) * 100, dates, n_regimes=2)

        assert result is not None
        assert "regimes" in result
        assert "stats" in result
        assert len(result["stats"]) == 2
        assert len(result["regimes"]) == n_obs

    def test_fit_markov_regimes_display_filter(self):
        """Display start/end filters the returned regimes."""
        _ensure_statsmodels_modules()

        n_obs = 100
        mock_probs = np.zeros((n_obs, 2))
        for i in range(n_obs):
            mock_probs[i, 0] = 0.9
            mock_probs[i, 1] = 0.1

        mock_result = MagicMock()
        mock_result.smoothed_marginal_probabilities = mock_probs
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result

        from stats.regime import fit_markov_regimes
        from datetime import date, timedelta
        start = date(2024, 1, 2)
        dates = [(start + timedelta(days=i)).isoformat() for i in range(n_obs)]

        with patch(
            "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
            return_value=mock_model,
        ):
            result = fit_markov_regimes(
                np.random.randn(n_obs) * 100, dates, n_regimes=2,
                display_start="2024-02-01", display_end="2024-03-01",
            )

        assert result is not None
        # All returned dates should be within display range
        for r in result["regimes"]:
            assert r["date"] >= "2024-02-01"
            assert r["date"] <= "2024-03-01"
        # Stats should still be computed from full history
        total_count = sum(s["count"] for s in result["stats"])
        assert total_count == n_obs


# ---------------------------------------------------------------------------
# Priceable ticker filtering
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Intraday endpoints
# ---------------------------------------------------------------------------

class TestIntradayReturns:
    @pytest.fixture
    async def intraday_client(self):
        """Client with mocked Alpaca data provider."""
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

        alpaca_mock = AsyncMock()
        alpaca_mock.get_intraday_bars.return_value = {
            "AAPL": [
                {"timestamp": "2026-03-20T14:30:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
                {"timestamp": "2026-03-20T14:35:00Z", "open": 100, "high": 102, "low": 100, "close": 101, "volume": 1200},
                {"timestamp": "2026-03-20T14:40:00Z", "open": 101, "high": 103, "low": 101, "close": 102, "volume": 800},
            ],
            "MSFT": [
                {"timestamp": "2026-03-20T14:30:00Z", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 500},
                {"timestamp": "2026-03-20T14:35:00Z", "open": 200, "high": 202, "low": 200, "close": 201, "volume": 600},
                {"timestamp": "2026-03-20T14:40:00Z", "open": 201, "high": 203, "low": 200, "close": 200, "volume": 400},
            ],
        }

        app = create_app(settings, db, event_bus)
        set_state("yfinance_provider", yf_mock)
        set_state("data_provider", alpaca_mock)
        set_state("event_bus", event_bus)
        set_state("rf_fetcher", None)

        from httpx import ASGITransport, AsyncClient as HttpxClient
        transport = ASGITransport(app=app)
        async with HttpxClient(transport=transport, base_url="http://test") as c:
            # Create portfolio with holdings
            resp = await c.post("/api/portfolios", json={"name": "Intraday Test"})
            pid = resp.json()["id"]
            await c.put(f"/api/portfolios/{pid}/holdings", json=[
                {"ticker": "AAPL", "weight": 60},
                {"ticker": "MSFT", "weight": 40},
            ])
            yield c, pid, alpaca_mock

        await db.close()

    @pytest.mark.asyncio
    async def test_intraday_returns(self, intraday_client):
        client, pid, _ = intraday_client
        resp = await client.get(f"/api/portfolios/{pid}/intraday/returns?interval=5Min")
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval"] == "5Min"
        assert len(data["returns"]) == 3
        # First bar should be ~0% (starting point)
        assert data["returns"][0]["portfolio"] == 0.0

    @pytest.mark.asyncio
    async def test_intraday_analytics(self, intraday_client):
        client, pid, _ = intraday_client
        resp = await client.get(f"/api/portfolios/{pid}/intraday/analytics?interval=5Min")
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval"] == "5Min"
        assert "daily_return" in data
        assert "daily_vol" in data
        # AAPL went 100→102 (2%), MSFT 200→200 (0%), weighted ~1.2%
        assert data["daily_return"] > 0

    @pytest.mark.asyncio
    async def test_intraday_invalid_interval(self, intraday_client):
        client, pid, _ = intraday_client
        resp = await client.get(f"/api/portfolios/{pid}/intraday/returns?interval=10Min")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_intraday_calls_alpaca_not_yfinance(self, intraday_client):
        client, pid, alpaca_mock = intraday_client
        await client.get(f"/api/portfolios/{pid}/intraday/returns?interval=5Min")
        alpaca_mock.get_intraday_bars.assert_called_once()


class TestPriceableTickerFilter:
    def test_equity_tickers_are_priceable(self):
        from dashboard.routes.portfolio import _is_priceable_ticker
        assert _is_priceable_ticker("AAPL") is True
        assert _is_priceable_ticker("BRK-B") is True
        assert _is_priceable_ticker("MSFT") is True

    def test_bond_descriptions_are_not_priceable(self):
        from dashboard.routes.portfolio import _is_priceable_ticker
        assert _is_priceable_ticker("RIVN 3.625 10/15/30") is False
        assert _is_priceable_ticker("BAC 0.6 05/25/27 MTN") is False
        assert _is_priceable_ticker("SPOT 0 03/15/26") is False

    def test_empty_ticker_is_not_priceable(self):
        from dashboard.routes.portfolio import _is_priceable_ticker
        assert _is_priceable_ticker("") is False

    def test_priceable_weights_rescale_100(self):
        from dashboard.routes.portfolio import _priceable_weights
        from types import SimpleNamespace

        holdings = [
            SimpleNamespace(ticker="AAPL", weight=60),
            SimpleNamespace(ticker="RIVN 3.625 10/15/30", weight=30),
            SimpleNamespace(ticker="MSFT", weight=10),
        ]
        weights = _priceable_weights(holdings, rescale=100)
        # Bond filtered out, remaining rescaled to sum to 100%:
        # AAPL=60/70*100=85.71%, MSFT=10/70*100=14.29% → as fractions /100
        assert "RIVN 3.625 10/15/30" not in weights
        assert set(weights.keys()) == {"AAPL", "MSFT"}
        assert abs(sum(weights.values()) - 1.0) < 1e-9
        assert abs(weights["AAPL"] - 60 / 70) < 1e-9
        assert abs(weights["MSFT"] - 10 / 70) < 1e-9

    def test_priceable_weights_no_rescale(self):
        from dashboard.routes.portfolio import _priceable_weights
        from types import SimpleNamespace

        holdings = [
            SimpleNamespace(ticker="AAPL", weight=60),
            SimpleNamespace(ticker="RIVN 3.625 10/15/30", weight=30),
            SimpleNamespace(ticker="MSFT", weight=10),
        ]
        weights = _priceable_weights(holdings, rescale=None)
        # No rescaling: raw weights / 100 → AAPL=0.6, MSFT=0.1
        assert abs(weights["AAPL"] - 0.6) < 1e-9
        assert abs(weights["MSFT"] - 0.1) < 1e-9
        assert abs(sum(weights.values()) - 0.7) < 1e-9

    def test_priceable_weights_rescale_custom_target(self):
        from dashboard.routes.portfolio import _priceable_weights
        from types import SimpleNamespace

        holdings = [
            SimpleNamespace(ticker="AAPL", weight=60),
            SimpleNamespace(ticker="RIVN 3.625 10/15/30", weight=30),
            SimpleNamespace(ticker="MSFT", weight=10),
        ]
        # Rescale to 50% — as if you want the equity portion to represent half
        weights = _priceable_weights(holdings, rescale=50)
        assert abs(sum(weights.values()) - 0.5) < 1e-9
        assert abs(weights["AAPL"] - (60 / 70 * 50 / 100)) < 1e-9

    def test_priceable_weights_all_bonds_returns_empty(self):
        from dashboard.routes.portfolio import _priceable_weights
        from types import SimpleNamespace

        holdings = [
            SimpleNamespace(ticker="RIVN 3.625 10/15/30", weight=50),
            SimpleNamespace(ticker="BAC 0.6 05/25/27 MTN", weight=50),
        ]
        assert _priceable_weights(holdings) == {}


class TestConsolidatedSummary:
    """Tests for the consolidated /summary and /holdings-info-page endpoints."""

    @pytest.mark.asyncio
    async def test_summary_empty_portfolio(self, client):
        create = await client.post("/api/portfolios", json={"name": "Empty Summary"})
        pid = create.json()["id"]
        resp = await client.get(f"/api/portfolios/{pid}/summary?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert data["period"] == "1y"
        assert data["analytics"]["total_return"] == 0
        assert data["returns"] == []
        assert data["holdings"] == []
        assert data["holdings_count"] == 0
        assert data["priceable_count"] == 0

    @pytest.mark.asyncio
    async def test_summary_with_holdings(self, client):
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        history_aapl = _make_history(40, base_price=150.0)
        history_msft = _make_history(40, base_price=300.0)

        yf_mock.get_history.side_effect = lambda t, **kw: (
            history_aapl if t == "AAPL" else history_msft
        )
        yf_mock.get_histories_batch.return_value = {
            "AAPL": history_aapl,
            "MSFT": history_msft,
        }
        yf_mock.get_info_batch.return_value = {
            "AAPL": {"sector": "Technology", "pe_ratio": 30.0, "beta": 1.2},
            "MSFT": {"sector": "Technology", "pe_ratio": 35.0, "beta": 0.9},
        }

        create = await client.post("/api/portfolios", json={"name": "Summary Test"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/summary?period=1y")
        assert resp.status_code == 200
        data = resp.json()

        # Analytics populated
        assert data["analytics"]["portfolio_id"] == pid
        assert data["analytics"]["total_return"] != 0
        assert data["analytics"]["annualized_vol"] > 0
        assert data["analytics"]["sharpe"] != 0

        # Returns populated
        assert len(data["returns"]) > 0
        assert "date" in data["returns"][0]
        assert "portfolio" in data["returns"][0]

        # Holdings populated with info
        assert len(data["holdings"]) == 2
        aapl = next(h for h in data["holdings"] if h["ticker"] == "AAPL")
        assert aapl["sector"] == "Technology"
        assert aapl["pe_ratio"] == 30.0
        assert aapl["period_return"] is not None

        # Counts
        assert data["holdings_count"] == 2
        assert data["priceable_count"] == 2

        # Weighted averages
        assert data["weighted_pe"] is not None

        # Restore mocks
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _make_history(40)
        yf_mock.get_histories_batch.side_effect = None
        yf_mock.get_info_batch.side_effect = None

    @pytest.mark.asyncio
    async def test_summary_with_bonds(self, client):
        """Bond holdings (with spaces in ticker) appear in holdings but not in analytics."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        history = _make_history(40, base_price=100.0)

        yf_mock.get_histories_batch.return_value = {"AAPL": history}
        yf_mock.get_info_batch.return_value = {
            "AAPL": {"sector": "Technology"},
        }

        create = await client.post("/api/portfolios", json={"name": "Bond Test"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "RIVN 3.625 10/15/30", "weight": 40},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/summary?period=1y")
        assert resp.status_code == 200
        data = resp.json()

        # Both holdings present
        assert data["holdings_count"] == 2
        assert data["priceable_count"] == 1
        assert len(data["holdings"]) == 2

        # Bond is in holdings but without price data
        bond = next(h for h in data["holdings"] if "RIVN" in h["ticker"])
        assert bond["period_return"] is None

        # Restore mocks
        yf_mock.get_histories_batch.side_effect = None
        yf_mock.get_info_batch.side_effect = None

    @pytest.mark.asyncio
    async def test_holdings_info_page_basic(self, client):
        """Paginated holdings info endpoint returns correct page."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        history = _make_history(40, base_price=100.0)

        yf_mock.get_info_batch.return_value = {
            "AAPL": {"sector": "Technology", "pe_ratio": 30.0},
            "MSFT": {"sector": "Technology", "pe_ratio": 35.0},
        }
        yf_mock.get_histories_batch.return_value = {
            "AAPL": history,
            "MSFT": history,
        }

        create = await client.post("/api/portfolios", json={"name": "Page Test"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        resp = await client.get(f"/api/portfolios/{pid}/holdings-info-page?offset=0&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["offset"] == 0
        assert data["limit"] == 1
        assert len(data["holdings"]) == 1
        # First by weight should be AAPL (60%)
        assert data["holdings"][0]["ticker"] == "AAPL"

        # Second page
        resp2 = await client.get(f"/api/portfolios/{pid}/holdings-info-page?offset=1&limit=1")
        data2 = resp2.json()
        assert len(data2["holdings"]) == 1
        assert data2["holdings"][0]["ticker"] == "MSFT"

        # Past the end
        resp3 = await client.get(f"/api/portfolios/{pid}/holdings-info-page?offset=5&limit=1")
        assert resp3.json()["holdings"] == []

        # Restore mocks
        yf_mock.get_info_batch.side_effect = None
        yf_mock.get_histories_batch.side_effect = None

    @pytest.mark.asyncio
    async def test_holdings_info_page_empty(self, client):
        create = await client.post("/api/portfolios", json={"name": "Empty Page"})
        pid = create.json()["id"]
        resp = await client.get(f"/api/portfolios/{pid}/holdings-info-page?offset=0&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["holdings"] == []


class TestYFinanceBatchMethods:
    """Tests for get_histories_batch and get_info_batch on YFinanceProvider."""

    @pytest.mark.asyncio
    async def test_get_histories_batch_basic(self):
        from data.yfinance_provider import YFinanceProvider, _cache
        import pandas as pd
        from datetime import date, timedelta

        provider = YFinanceProvider()
        _cache.clear()

        # Use recent dates so they survive the 1y slice
        recent_start = date.today() - timedelta(days=10)
        dates = pd.date_range(recent_start.isoformat(), periods=5, freq="B")
        arrays = {
            ("Open", "AAPL"): [150.0, 151.0, 152.0, 153.0, 154.0],
            ("High", "AAPL"): [155.0, 156.0, 157.0, 158.0, 159.0],
            ("Low", "AAPL"): [149.0, 150.0, 151.0, 152.0, 153.0],
            ("Close", "AAPL"): [152.0, 153.0, 154.0, 155.0, 156.0],
            ("Volume", "AAPL"): [1000000, 1100000, 1200000, 1300000, 1400000],
            ("Open", "MSFT"): [300.0, 301.0, 302.0, 303.0, 304.0],
            ("High", "MSFT"): [305.0, 306.0, 307.0, 308.0, 309.0],
            ("Low", "MSFT"): [299.0, 300.0, 301.0, 302.0, 303.0],
            ("Close", "MSFT"): [302.0, 303.0, 304.0, 305.0, 306.0],
            ("Volume", "MSFT"): [2000000, 2100000, 2200000, 2300000, 2400000],
        }
        df = pd.DataFrame(arrays, index=dates)
        df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Price", "Ticker"])

        with patch("yfinance.download", return_value=df):
            result = await provider.get_histories_batch(["AAPL", "MSFT"], period="1y")

        assert "AAPL" in result
        assert "MSFT" in result
        assert len(result["AAPL"]) == 5
        assert len(result["MSFT"]) == 5
        assert result["AAPL"][0]["close"] == 152.0
        assert result["MSFT"][-1]["close"] == 306.0

        # Verify cache was populated
        assert any("history:AAPL" in k for k in _cache)
        assert any("history:MSFT" in k for k in _cache)

    @pytest.mark.asyncio
    async def test_get_histories_batch_single_ticker(self):
        from data.yfinance_provider import YFinanceProvider, _cache
        import pandas as pd
        from datetime import date, timedelta

        provider = YFinanceProvider()
        _cache.clear()

        recent_start = date.today() - timedelta(days=10)
        dates = pd.date_range(recent_start.isoformat(), periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [103.0, 104.0, 105.0],
            "Volume": [500000, 600000, 700000],
        }, index=dates)

        with patch("yfinance.download", return_value=df):
            result = await provider.get_histories_batch(["SOLO"], period="6m")

        assert "SOLO" in result
        assert len(result["SOLO"]) == 3
        assert result["SOLO"][0]["close"] == 103.0

    @pytest.mark.asyncio
    async def test_get_histories_batch_empty(self):
        from data.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()
        result = await provider.get_histories_batch([], period="1y")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_histories_batch_uses_cache(self):
        from data.yfinance_provider import YFinanceProvider, _cache, _set_cached
        import pandas as pd

        provider = YFinanceProvider()
        _cache.clear()

        cached_data = [{"date": "2024-01-02", "close": 100.0}]
        _set_cached("history:AAPL:1y::1d", cached_data)

        with patch("yfinance.download") as mock_dl:
            mock_dl.return_value = pd.DataFrame()
            result = await provider.get_histories_batch(["AAPL"], period="1y")

        assert result["AAPL"] == cached_data
        # download should not have been called (cache hit)
        mock_dl.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_info_batch_throttled(self):
        from data.yfinance_provider import YFinanceProvider

        provider = YFinanceProvider()
        provider.get_info = AsyncMock(side_effect=lambda t: {"ticker": t, "sector": "Tech"})

        result = await provider.get_info_batch(["AAPL", "MSFT", "GOOG"], max_concurrent=2)

        assert len(result) == 3
        assert result["AAPL"]["sector"] == "Tech"
        assert provider.get_info.call_count == 3

    @pytest.mark.asyncio
    async def test_get_info_batch_empty(self):
        from data.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()
        result = await provider.get_info_batch([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_5y_cache_serves_shorter_periods(self):
        """After fetching 1y (which downloads 5y internally), switching to 6m uses cache."""
        from data.yfinance_provider import YFinanceProvider, _cache
        import pandas as pd
        from datetime import date, timedelta

        provider = YFinanceProvider()
        _cache.clear()

        # Generate 1y of daily dates (recent)
        start_date = date.today() - timedelta(days=365)
        dates = pd.bdate_range(start_date.isoformat(), periods=252)
        n = len(dates)
        arrays = {
            ("Open", "AAPL"): list(range(100, 100 + n)),
            ("High", "AAPL"): list(range(105, 105 + n)),
            ("Low", "AAPL"): list(range(95, 95 + n)),
            ("Close", "AAPL"): list(range(102, 102 + n)),
            ("Volume", "AAPL"): [1000000] * n,
        }
        df = pd.DataFrame(arrays, index=dates)
        df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Price", "Ticker"])

        with patch("yfinance.download", return_value=df) as mock_dl:
            # First call: period=1y → internally fetches 5y, caches it
            result_1y = await provider.get_histories_batch(["AAPL"], period="1y")
            assert len(result_1y["AAPL"]) > 0
            assert mock_dl.call_count == 1

            # Second call: period=6m → should serve from 5y cache, no new download
            result_6m = await provider.get_histories_batch(["AAPL"], period="6m")
            assert len(result_6m["AAPL"]) > 0
            assert mock_dl.call_count == 1  # No additional call!

            # 6m should have fewer records than 1y
            assert len(result_6m["AAPL"]) <= len(result_1y["AAPL"])

    @pytest.mark.asyncio
    async def test_5y_cache_serves_custom_range(self):
        """Custom date range within 5y is served from cached 5y data."""
        from data.yfinance_provider import YFinanceProvider, _cache, _set_cached
        from datetime import date, timedelta

        provider = YFinanceProvider()
        _cache.clear()

        # Pre-populate 5y cache with some records
        today = date.today()
        records = [
            {"date": (today - timedelta(days=i)).isoformat(), "open": 100, "high": 105,
             "low": 95, "close": 102, "volume": 1000000}
            for i in range(500, 0, -1)
        ]
        _set_cached("history:AAPL:5y::1d", records)

        with patch("yfinance.download") as mock_dl:
            start = (today - timedelta(days=90)).isoformat()
            end = (today - timedelta(days=30)).isoformat()
            result = await provider.get_histories_batch(
                ["AAPL"], start=start, end=end
            )
            assert len(result["AAPL"]) > 0
            assert len(result["AAPL"]) < len(records)
            mock_dl.assert_not_called()  # Served from cache

    @pytest.mark.asyncio
    async def test_get_history_uses_wide_cache(self):
        """Single-ticker get_history() benefits from 5y batch cache."""
        from data.yfinance_provider import YFinanceProvider, _cache, _set_cached
        from datetime import date, timedelta

        provider = YFinanceProvider()
        _cache.clear()

        today = date.today()
        records = [
            {"date": (today - timedelta(days=i)).isoformat(), "open": 100, "high": 105,
             "low": 95, "close": 102, "volume": 1000000}
            for i in range(400, 0, -1)
        ]
        _set_cached("history:AAPL:5y::1d", records)

        # get_history for 1y should slice from 5y cache
        result = await provider.get_history("AAPL", period="1y")
        assert len(result) > 0
        assert len(result) < len(records)  # Sliced, not full 5y


# ---------------------------------------------------------------------------
# Portfolio Cache Service Tests
# ---------------------------------------------------------------------------

class TestPortfolioCacheService:
    """Test the DB-level portfolio summary cache."""

    @pytest.mark.asyncio
    async def test_save_and_load_cache(self, app):
        """Save a summary, then load it back — round-trip fidelity."""
        from datetime import date, timedelta
        from dashboard.deps import get_db
        from dashboard.services.portfolio_cache import PortfolioCacheService
        from db.models import PortfolioORM

        db = get_db()
        svc = PortfolioCacheService(db)

        # Create the parent portfolio so FK constraints are satisfied
        async with db.session() as session:
            session.add(PortfolioORM(id="test_port_1", name="Test Portfolio Cache"))
            await session.commit()

        today = date.today()
        d1 = (today - timedelta(days=150)).isoformat()
        d2 = (today - timedelta(days=75)).isoformat()
        d3 = today.isoformat()

        returns_non_prorated = [
            {"date": d1, "portfolio": 0.0},
            {"date": d2, "portfolio": 5.5},
            {"date": d3, "portfolio": 12.3},
        ]
        returns_prorated = [
            {"date": d1, "portfolio": 0.0},
            {"date": d2, "portfolio": 6.1},
            {"date": d3, "portfolio": 13.0},
        ]
        summary_dict = {
            "analytics": {
                "total_return": 12.3,
                "annualized_vol": 15.0,
                "sharpe": 0.82,
                "sortino": 1.1,
                "max_drawdown": -5.0,
                "var_95": -2.1,
                "cvar_95": -3.0,
            },
            "weighted_pe": 20.5,
            "weighted_forward_pe": 18.0,
            "weighted_dividend_yield": 1.5,
            "weighted_beta": 1.1,
            "avg_pe": 22.0,
            "avg_forward_pe": 19.0,
            "avg_dividend_yield": 1.8,
            "avg_beta": 1.0,
            "max_pe": 30.0,
            "max_forward_pe": 25.0,
            "max_dividend_yield": 3.0,
            "max_beta": 1.5,
            "min_pe": 10.0,
            "min_forward_pe": 8.0,
            "min_dividend_yield": 0.5,
            "min_beta": 0.6,
            "holdings_count": 5,
            "priceable_count": 4,
        }

        await svc.save_summary("test_port_1", summary_dict, returns_prorated, returns_non_prorated)

        # Load non-prorated using custom date range that matches the cache
        result = await svc.get_cached_summary("test_port_1", "", False, start=d1, end=d3)
        assert result is not None
        assert len(result["returns"]) == 3
        assert result["weighted_pe"] == 20.5
        assert result["avg_beta"] == 1.0
        assert result["holdings_count"] == 5
        assert result["cached"] is True

        # Load prorated
        result_pr = await svc.get_cached_summary("test_port_1", "", True, start=d1, end=d3)
        assert result_pr is not None
        assert result_pr["returns"][2]["portfolio"] == 13.0

    @pytest.mark.asyncio
    async def test_cache_serves_stale_data_for_wider_period(self, app):
        """Cache with narrower data still serves for wider period requests."""
        from dashboard.deps import get_db
        from dashboard.services.portfolio_cache import PortfolioCacheService
        from db.models import PortfolioORM

        db = get_db()
        svc = PortfolioCacheService(db)

        async with db.session() as session:
            session.add(PortfolioORM(id="test_port_2", name="Test Portfolio Cache 2"))
            await session.commit()

        # Cache only 180 days of data
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=180)).isoformat()
        end = date.today().isoformat()

        returns = [
            {"date": start, "portfolio": 0.0},
            {"date": end, "portfolio": 5.0},
        ]
        summary_dict = {"analytics": {}, "holdings_count": 2, "priceable_count": 2}

        await svc.save_summary("test_port_2", summary_dict, returns, returns)

        # Request 1y — cache only has 180 days, but should still serve it
        result = await svc.get_cached_summary("test_port_2", "1y", False)
        assert result is not None
        assert result["cached"] is True
        assert len(result["returns"]) >= 1  # At least some data returned

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, app):
        """Invalidation should remove all cached data for the portfolio."""
        from datetime import date, timedelta
        from dashboard.deps import get_db
        from dashboard.services.portfolio_cache import PortfolioCacheService
        from db.models import PortfolioORM

        db = get_db()
        svc = PortfolioCacheService(db)

        async with db.session() as session:
            session.add(PortfolioORM(id="test_port_3", name="Test Portfolio Cache 3"))
            await session.commit()

        today = date.today()
        returns = [
            {"date": (today - timedelta(days=100)).isoformat(), "portfolio": 0.0},
            {"date": today.isoformat(), "portfolio": 10.0},
        ]
        summary_dict = {"analytics": {}, "holdings_count": 1, "priceable_count": 1}

        d1 = (today - timedelta(days=100)).isoformat()
        d2 = today.isoformat()
        await svc.save_summary("test_port_3", summary_dict, returns, returns)

        # Verify cache exists (using custom range matching the data)
        result = await svc.get_cached_summary("test_port_3", "", False, start=d1, end=d2)
        assert result is not None

        # Invalidate
        await svc.invalidate("test_port_3")

        # Verify cache is gone
        result = await svc.get_cached_summary("test_port_3", "", False, start=d1, end=d2)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_covers_narrower_period(self, app):
        """Cache with wide date range serves narrower period requests."""
        from dashboard.deps import get_db
        from dashboard.services.portfolio_cache import PortfolioCacheService
        from db.models import PortfolioORM
        from datetime import date, timedelta

        db = get_db()
        svc = PortfolioCacheService(db)

        async with db.session() as session:
            session.add(PortfolioORM(id="test_port_4", name="Test Portfolio Cache 4"))
            await session.commit()

        # Cache 3 years of data
        today = date.today()
        returns = []
        for i in range(0, 1100, 10):
            d = (today - timedelta(days=1100 - i)).isoformat()
            returns.append({"date": d, "portfolio": round(i * 0.01, 2)})

        summary_dict = {"analytics": {}, "holdings_count": 3, "priceable_count": 3}
        await svc.save_summary("test_port_4", summary_dict, returns, returns)

        # Request 1y — should succeed and return only recent ~366 days
        result = await svc.get_cached_summary("test_port_4", "1y", False)
        assert result is not None
        # All returned dates should be within last ~366 days
        cutoff = (today - timedelta(days=366)).isoformat()
        for r in result["returns"]:
            assert r["date"] >= cutoff


# ---------------------------------------------------------------------------
# SSE Endpoint Tests
# ---------------------------------------------------------------------------

def _make_recent_history(num_days: int, base_price: float = 100.0):
    """Generate history ending today so cache period checks work."""
    from datetime import date, timedelta
    start = date.today() - timedelta(days=num_days - 1)
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


class TestPortfolioSSE:
    """Test the SSE streaming endpoint for portfolio summary."""

    @pytest.mark.asyncio
    async def test_sse_cold_start(self, client):
        """No cache — should get loading then fresh then done events."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        history = _make_recent_history(100)
        yf_mock.get_histories_batch.return_value = {"AAPL": history, "MSFT": history}
        yf_mock.get_info_batch.return_value = {}

        # Create portfolio with holdings
        create = await client.post("/api/portfolios", json={"name": "SSE Test Cold"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        # Request SSE stream
        resp = await client.get(f"/api/portfolios/{pid}/summary/stream?period=3mo")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        body = resp.text
        # Should have loading (no cache) and fresh events
        assert "event: loading" in body or "event: cached" in body
        assert "event: fresh" in body
        assert "event: done" in body

    @pytest.mark.asyncio
    async def test_sse_warm_cache(self, client):
        """After cold start populates cache, second request should get cached event."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        history = _make_recent_history(100)
        yf_mock.get_histories_batch.return_value = {"AAPL": history, "MSFT": history}
        yf_mock.get_info_batch.return_value = {}

        # Create portfolio
        create = await client.post("/api/portfolios", json={"name": "SSE Test Warm"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])

        # First request — populates cache (use 3mo which fits 100 days)
        await client.get(f"/api/portfolios/{pid}/summary/stream?period=3mo")

        # Second request — should hit cache
        resp = await client.get(f"/api/portfolios/{pid}/summary/stream?period=3mo")
        body = resp.text
        assert "event: cached" in body
        assert "event: fresh" in body
        assert "event: done" in body

    @pytest.mark.asyncio
    async def test_sse_invalidation_on_holdings_change(self, client):
        """Changing holdings should invalidate the cache."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        history = _make_recent_history(100)
        yf_mock.get_histories_batch.return_value = {"AAPL": history, "MSFT": history}
        yf_mock.get_info_batch.return_value = {}

        # Create portfolio and populate cache
        create = await client.post("/api/portfolios", json={"name": "SSE Invalidate"})
        pid = create.json()["id"]
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 60},
            {"ticker": "MSFT", "weight": 40},
        ])
        await client.get(f"/api/portfolios/{pid}/summary/stream?period=3mo")

        # Change holdings — should invalidate cache
        await client.put(f"/api/portfolios/{pid}/holdings", json=[
            {"ticker": "AAPL", "weight": 50},
            {"ticker": "MSFT", "weight": 50},
        ])

        # Next request should get loading (cache was invalidated)
        resp = await client.get(f"/api/portfolios/{pid}/summary/stream?period=3mo")
        body = resp.text
        assert "event: loading" in body
        assert "event: fresh" in body
