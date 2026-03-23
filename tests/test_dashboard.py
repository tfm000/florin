"""Tests for the dashboard FastAPI routes."""

import json
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings, T212Environment
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database
from db.models import ReportORM, TradeORM, UniverseStockORM


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
    await db.create_tables()
    event_bus = EventBus()

    app = create_app(settings, db, event_bus)
    yield app
    await db.close()


@pytest.fixture
async def readonly_app():
    """Create a test app with broker in read-only mode."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="test_key",
        t212_api_secret="test_secret",
        t212_environment=T212Environment.READONLY,
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()

    from broker.paper_broker import PaperBroker
    broker = PaperBroker(initial_cash=10_000.0)
    await broker.connect()

    app = create_app(settings, db, event_bus, broker)
    yield app
    await db.close()


@pytest.fixture
async def broker_app():
    """Create a test app with a PaperBroker and fixed price getter."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="test_key",
        t212_api_secret="test_secret",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()

    from broker.paper_broker import PaperBroker
    broker = PaperBroker(initial_cash=10_000.0, currency="USD")
    await broker.connect()
    # Fixed price getter for deterministic tests
    prices = {"AAPL": 150.0, "TSLA": 200.0, "MSFT": 300.0}
    broker.set_price_getter(lambda t: prices.get(t))

    app = create_app(settings, db, event_bus, broker)
    yield app, db
    await db.close()


@pytest.fixture
async def broker_client(broker_app):
    """AsyncClient backed by a PaperBroker with known prices."""
    app, db = broker_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, db


@pytest.fixture
async def client(app):
    """AsyncClient for testing the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def readonly_client(readonly_app):
    """AsyncClient for read-only mode app."""
    transport = ASGITransport(app=readonly_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestUniverseRoutes:
    @pytest.mark.asyncio
    async def test_get_universe_empty(self, client):
        resp = await client.get("/api/universe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_get_scanner_settings(self, client):
        resp = await client.get("/api/universe/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "price_max" in data
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
        assert "llm" in section_ids
        assert "broker" in section_ids
        assert "trading" in section_ids
        # Scanner section was removed (replaced by per-screener configs)
        assert "scanner" not in section_ids

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
            "settings": [{"key": "default_position_size", "value": "250.0"}]
        })
        resp = await client.get("/api/settings")
        data = resp.json()
        trading = next(s for s in data["sections"] if s["id"] == "trading")
        size_field = next(f for f in trading["fields"] if f["key"] == "default_position_size")
        assert size_field["value"] == "250.0"
        assert size_field["has_db_override"] is True

    @pytest.mark.asyncio
    async def test_delete_setting(self, client):
        # Set then delete
        await client.put("/api/settings", json={
            "settings": [{"key": "log_level", "value": "DEBUG"}]
        })
        resp = await client.delete("/api/settings/log_level")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "log_level"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_setting(self, client):
        resp = await client.delete("/api/settings/totally_fake_key")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is None

    @pytest.mark.asyncio
    async def test_update_restart_required_true(self, client):
        """Updating a broker key should flag restart_required."""
        resp = await client.put("/api/settings", json={
            "settings": [{"key": "t212_api_key", "value": "new_key_value"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["restart_required"] is True

    @pytest.mark.asyncio
    async def test_update_restart_required_false(self, client):
        """Updating a scanner key should NOT flag restart_required."""
        resp = await client.put("/api/settings", json={
            "settings": [{"key": "scan_interval_seconds", "value": "120"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["restart_required"] is False

    @pytest.mark.asyncio
    async def test_update_skips_masked_secret(self, client):
        """If value contains mask chars (•), the key is skipped."""
        resp = await client.put("/api/settings", json={
            "settings": [{"key": "groq_api_key", "value": "abc••••hij"}]
        })
        assert resp.status_code == 200
        # Key should NOT be in updated list since it was masked
        assert "groq_api_key" not in resp.json()["updated"]

    @pytest.mark.asyncio
    async def test_update_invalid_key_skipped(self, client):
        """Non-existent keys are silently skipped."""
        resp = await client.put("/api/settings", json={
            "settings": [{"key": "fake_setting_xyz", "value": "whatever"}]
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == []

    @pytest.mark.asyncio
    async def test_settings_field_types(self, client):
        """Number fields should have type='number', enum fields type='select'."""
        resp = await client.get("/api/settings")
        data = resp.json()
        trading = next(s for s in data["sections"] if s["id"] == "trading")
        size_field = next(f for f in trading["fields"] if f["key"] == "default_position_size")
        assert size_field["type"] == "number"

        analysis = next(s for s in data["sections"] if s["id"] == "analysis")
        mode_field = next(f for f in analysis["fields"] if f["key"] == "llm_mode")
        assert mode_field["type"] == "select"
        assert "single" in mode_field["choices"]
        assert "consensus" in mode_field["choices"]


class TestReadOnlyMode:
    @pytest.mark.asyncio
    async def test_buy_blocked_in_readonly(self, readonly_client):
        resp = await readonly_client.post("/api/orders/buy", json={"ticker": "AAPL"})
        assert resp.status_code == 403
        assert "read-only" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_sell_blocked_in_readonly(self, readonly_client):
        resp = await readonly_client.post("/api/orders/sell", json={"ticker": "AAPL", "quantity": 1})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_stoploss_blocked_in_readonly(self, readonly_client):
        resp = await readonly_client.post("/api/orders/stoploss", json={
            "ticker": "AAPL", "quantity": 1, "stop_price": 1.0,
        })
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_blocked_in_readonly(self, readonly_client):
        resp = await readonly_client.delete("/api/orders/some_id")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_positions_readable_in_readonly(self, readonly_client):
        """Read-only mode should still allow viewing positions."""
        resp = await readonly_client.get("/api/positions")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_account_readable_in_readonly(self, readonly_client):
        """Read-only mode should still allow viewing account."""
        resp = await readonly_client.get("/api/account")
        assert resp.status_code == 200


class TestHealthRoutes:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "setup_required")
        assert data["database"] is True
        assert "broker" in data
        assert "setup_checklist" in data

    @pytest.mark.asyncio
    async def test_health_check_ok_when_configured(self, client):
        """Health returns 'ok' when all required services are configured."""
        from dashboard.deps import get_settings as get_dashboard_settings
        settings = get_dashboard_settings()
        original_alpaca_key = settings.alpaca_api_key
        original_alpaca_secret = settings.alpaca_api_secret
        try:
            settings.alpaca_api_key = "test_key"
            settings.alpaca_api_secret = "test_secret"
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            settings.alpaca_api_key = original_alpaca_key
            settings.alpaca_api_secret = original_alpaca_secret

    @pytest.mark.asyncio
    async def test_health_broker_object_structure(self, client):
        """Health check broker field has connected, name, is_live."""
        resp = await client.get("/api/health")
        broker = resp.json()["broker"]
        assert "connected" in broker
        assert "name" in broker
        assert "is_live" in broker
        assert isinstance(broker["is_live"], bool)

    @pytest.mark.asyncio
    async def test_health_market_data_structure(self, client):
        resp = await client.get("/api/health")
        md = resp.json()["market_data"]
        assert "alpaca_configured" in md
        assert "alpaca_connected" in md
        assert isinstance(md["alpaca_configured"], bool)

    @pytest.mark.asyncio
    async def test_health_universe_structure(self, client):
        resp = await client.get("/api/health")
        uni = resp.json()["universe"]
        assert "ticker_count" in uni
        assert "last_refresh" in uni
        assert isinstance(uni["ticker_count"], int)

    @pytest.mark.asyncio
    async def test_health_scanner_structure(self, client):
        resp = await client.get("/api/health")
        scanner = resp.json()["scanner"]
        assert "active" in scanner
        assert isinstance(scanner["active"], bool)

    @pytest.mark.asyncio
    async def test_health_setup_checklist_structure(self, client):
        resp = await client.get("/api/health")
        checklist = resp.json()["setup_checklist"]
        assert len(checklist) >= 1
        item = checklist[0]
        assert "key" in item
        assert "label" in item
        assert "description" in item
        assert "configured" in item
        assert isinstance(item["configured"], bool)

    @pytest.mark.asyncio
    async def test_health_trading_mode_field(self, client):
        resp = await client.get("/api/health")
        data = resp.json()
        assert data["trading_mode"] in ("PAPER", "LIVE")
        assert isinstance(data["paper_trading"], bool)
        assert isinstance(data["telegram_configured"], bool)

    @pytest.mark.asyncio
    async def test_terminate_no_handler(self, client):
        """Terminate without a shutdown callback registered."""
        resp = await client.post("/api/terminate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no shutdown handler registered"

    @pytest.mark.asyncio
    async def test_terminate_with_handler(self, client):
        """Terminate with a shutdown callback registered."""
        called = []
        set_state("shutdown_callback", lambda: called.append(True))
        resp = await client.post("/api/terminate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "shutting_down"


# =========================================================================
# Deep tests — validate response data, not just status codes
# =========================================================================


class TestAccountDeep:
    """Validate account summary response fields with a live PaperBroker."""

    @pytest.mark.asyncio
    async def test_account_initial_state(self, broker_client):
        client, _ = broker_client
        resp = await client.get("/api/account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "USD"
        assert data["cash_available"] == 10_000.0
        assert data["invested_value"] == 0.0
        assert data["total_value"] == 10_000.0
        assert data["unrealised_pnl"] == 0.0
        assert data["realised_pnl"] == 0.0
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_account_after_buy(self, broker_client):
        """Buying reduces cash and increases invested_value."""
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 10})
        resp = await client.get("/api/account")
        data = resp.json()
        # 10 shares @ $150 = $1500
        assert data["cash_available"] == pytest.approx(10_000.0 - 1500.0)
        assert data["invested_value"] == pytest.approx(1500.0)
        assert data["total_value"] == pytest.approx(10_000.0)  # no price change

    @pytest.mark.asyncio
    async def test_account_after_round_trip(self, broker_client):
        """Buy then sell records realised P&L."""
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 5})
        await client.post("/api/orders/sell", json={"ticker": "AAPL", "quantity": 5})
        resp = await client.get("/api/account")
        data = resp.json()
        # Bought and sold at same price ($150) → P&L = 0
        assert data["realised_pnl"] == pytest.approx(0.0)
        assert data["cash_available"] == pytest.approx(10_000.0)
        assert data["invested_value"] == pytest.approx(0.0)


class TestOrdersDeep:
    """Validate order placement, fill data, and error handling."""

    @pytest.mark.asyncio
    async def test_buy_market_response_fields(self, broker_client):
        client, _ = broker_client
        resp = await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["ticker"] == "AAPL"
        assert data["side"] == "BUY"
        assert data["filled_quantity"] == 5.0
        assert data["filled_price"] == 150.0
        assert data["status"] == "FILLED"
        assert data["order_id"]  # non-empty

    @pytest.mark.asyncio
    async def test_sell_market_response_fields(self, broker_client):
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "TSLA", "quantity": 3})
        resp = await client.post("/api/orders/sell", json={"ticker": "TSLA", "quantity": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["ticker"] == "TSLA"
        assert data["side"] == "SELL"
        assert data["filled_quantity"] == 3.0
        assert data["filled_price"] == 200.0
        assert data["status"] == "FILLED"

    @pytest.mark.asyncio
    async def test_buy_insufficient_cash(self, broker_client):
        """Buying more than cash allows returns 400 with error message."""
        client, _ = broker_client
        # 100 shares @ $300 = $30,000 > $10,000 cash
        resp = await client.post("/api/orders/buy", json={"ticker": "MSFT", "quantity": 100})
        assert resp.status_code == 400
        assert "insufficient cash" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_sell_insufficient_position(self, broker_client):
        """Selling shares you don't own returns 400."""
        client, _ = broker_client
        resp = await client.post("/api/orders/sell", json={"ticker": "AAPL", "quantity": 10})
        assert resp.status_code == 400
        assert "insufficient position" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_buy_no_price_available(self, broker_client):
        """Buying a ticker with no price returns 400."""
        client, _ = broker_client
        resp = await client.post("/api/orders/buy", json={"ticker": "UNKNOWN", "quantity": 1})
        assert resp.status_code == 400
        assert "no price" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_limit_order_goes_pending(self, broker_client):
        client, _ = broker_client
        resp = await client.post("/api/orders/buy", json={
            "ticker": "AAPL", "quantity": 5, "limit_price": 140.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "SUBMITTED"
        # Should appear in pending orders
        pending = await client.get("/api/orders/pending")
        assert len(pending.json()) == 1
        assert pending.json()[0]["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_cancel_order(self, broker_client):
        client, _ = broker_client
        resp = await client.post("/api/orders/buy", json={
            "ticker": "AAPL", "quantity": 5, "limit_price": 140.0,
        })
        order_id = resp.json()["order_id"]
        cancel_resp = await client.delete(f"/api/orders/{order_id}")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["cancelled"] is True
        assert cancel_resp.json()["order_id"] == order_id
        # Pending should be empty now
        pending = await client.get("/api/orders/pending")
        assert pending.json() == []

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, broker_client):
        client, _ = broker_client
        resp = await client.delete("/api/orders/doesnotexist")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_stoploss_order(self, broker_client):
        client, _ = broker_client
        # Need a position first for the stop to make sense (stop is a sell)
        await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 10})
        resp = await client.post("/api/orders/stoploss", json={
            "ticker": "AAPL", "quantity": 10, "stop_price": 130.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_value_based_buy(self, broker_client):
        """Buy by target_value instead of quantity."""
        client, _ = broker_client
        resp = await client.post("/api/orders/buy", json={
            "ticker": "AAPL", "target_value": 750.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # $750 / $150 = 5 shares
        assert data["filled_quantity"] == pytest.approx(5.0)
        assert data["filled_price"] == 150.0


class TestPositionsDeep:
    """Validate position response fields after trading."""

    @pytest.mark.asyncio
    async def test_positions_empty(self, broker_client):
        client, _ = broker_client
        resp = await client.get("/api/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_position_after_buy(self, broker_client):
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 10})
        resp = await client.get("/api/positions")
        assert resp.status_code == 200
        positions = resp.json()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["ticker"] == "AAPL"
        assert pos["quantity"] == 10.0
        assert pos["avg_price"] == 150.0
        assert pos["current_price"] == 150.0
        assert pos["market_value"] == pytest.approx(1500.0)
        assert pos["unrealised_pnl"] == pytest.approx(0.0)
        assert pos["unrealised_pnl_pct"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_position_by_ticker(self, broker_client):
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "TSLA", "quantity": 2})
        resp = await client.get("/api/positions/TSLA")
        assert resp.status_code == 200
        pos = resp.json()
        assert pos["ticker"] == "TSLA"
        assert pos["quantity"] == 2.0
        assert pos["avg_price"] == 200.0

    @pytest.mark.asyncio
    async def test_position_not_found(self, broker_client):
        client, _ = broker_client
        resp = await client.get("/api/positions/NOPE")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_position_removed_after_full_sell(self, broker_client):
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 5})
        await client.post("/api/orders/sell", json={"ticker": "AAPL", "quantity": 5})
        resp = await client.get("/api/positions")
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_multiple_positions(self, broker_client):
        client, _ = broker_client
        await client.post("/api/orders/buy", json={"ticker": "AAPL", "quantity": 5})
        await client.post("/api/orders/buy", json={"ticker": "TSLA", "quantity": 3})
        resp = await client.get("/api/positions")
        positions = resp.json()
        assert len(positions) == 2
        tickers = {p["ticker"] for p in positions}
        assert tickers == {"AAPL", "TSLA"}


class TestTradesDeep:
    """Validate trade history with seeded DB data."""

    @pytest.fixture
    async def seeded_client(self, app):
        """Seed the DB with trade records and return a client."""
        from dashboard.deps import get_db
        db = get_db()
        async with db.session() as session:
            session.add(TradeORM(
                id="trade_win_01", ticker="AAPL", side="BUY",
                order_type="MARKET", quantity=10, price=100.0,
                total_value=1000.0, status="FILLED",
                executed_at=datetime(2025, 1, 10, tzinfo=UTC),
            ))
            session.add(TradeORM(
                id="trade_win_02", ticker="AAPL", side="SELL",
                order_type="MARKET", quantity=10, price=120.0,
                total_value=1200.0, status="FILLED",
                is_closing_trade=True, realised_pnl=200.0,
                realised_pnl_pct=20.0,
                executed_at=datetime(2025, 1, 15, tzinfo=UTC),
            ))
            session.add(TradeORM(
                id="trade_loss_01", ticker="TSLA", side="BUY",
                order_type="MARKET", quantity=5, price=200.0,
                total_value=1000.0, status="FILLED",
                executed_at=datetime(2025, 1, 20, tzinfo=UTC),
            ))
            session.add(TradeORM(
                id="trade_loss_02", ticker="TSLA", side="SELL",
                order_type="MARKET", quantity=5, price=180.0,
                total_value=900.0, status="FILLED",
                is_closing_trade=True, realised_pnl=-100.0,
                realised_pnl_pct=-10.0,
                executed_at=datetime(2025, 1, 25, tzinfo=UTC),
            ))
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_trades_response_fields(self, seeded_client):
        resp = await seeded_client.get("/api/trades")
        assert resp.status_code == 200
        trades = resp.json()
        assert len(trades) == 4
        # Most recent first (trade_loss_02)
        t = trades[0]
        assert t["id"] == "trade_loss_02"
        assert t["ticker"] == "TSLA"
        assert t["side"] == "SELL"
        assert t["order_type"] == "MARKET"
        assert t["quantity"] == 5.0
        assert t["price"] == 180.0
        assert t["total_value"] == 900.0
        assert t["status"] == "FILLED"
        assert t["is_closing_trade"] is True
        assert t["realised_pnl"] == -100.0
        assert t["realised_pnl_pct"] == -10.0
        assert "executed_at" in t

    @pytest.mark.asyncio
    async def test_trades_filter_by_ticker(self, seeded_client):
        resp = await seeded_client.get("/api/trades?ticker=AAPL")
        trades = resp.json()
        assert len(trades) == 2
        assert all(t["ticker"] == "AAPL" for t in trades)

    @pytest.mark.asyncio
    async def test_trades_filter_by_side(self, seeded_client):
        resp = await seeded_client.get("/api/trades?side=SELL")
        trades = resp.json()
        assert len(trades) == 2
        assert all(t["side"] == "SELL" for t in trades)

    @pytest.mark.asyncio
    async def test_trades_pagination(self, seeded_client):
        resp = await seeded_client.get("/api/trades?limit=2&offset=0")
        assert len(resp.json()) == 2
        resp2 = await seeded_client.get("/api/trades?limit=2&offset=2")
        assert len(resp2.json()) == 2
        # No overlap
        ids_page1 = {t["id"] for t in resp.json()}
        ids_page2 = {t["id"] for t in resp2.json()}
        assert ids_page1.isdisjoint(ids_page2)


class TestReportsDeep:
    """Validate report listing and detail endpoints with seeded data."""

    @pytest.fixture
    async def seeded_client(self, app):
        from dashboard.deps import get_db
        db = get_db()
        report_data = {"analysis": "test analysis content", "signals": ["bullish"]}
        async with db.session() as session:
            session.add(ReportORM(
                id="rpt_001", ticker="AAPL", mode="single",
                alert_price=2.50, alert_change_pct=15.0, alert_volume=500_000,
                final_recommendation="BUY", final_score=7.5, final_confidence=0.85,
                fraud_risk_level="LOW", fraud_risk_score=1.2,
                fraud_flags=json.dumps(["low_float"]),
                reddit_mentions=42, stocktwits_bullish=10, stocktwits_bearish=3,
                insider_buys=2, insider_sells=0, news_count=5,
                report_json=json.dumps(report_data),
                user_action="PENDING",
                generated_at=datetime(2025, 2, 1, tzinfo=UTC),
            ))
            session.add(ReportORM(
                id="rpt_002", ticker="TSLA", mode="consensus",
                alert_price=180.0, alert_change_pct=-5.0, alert_volume=1_000_000,
                final_recommendation="AVOID", final_score=3.0, final_confidence=0.70,
                fraud_risk_level="MEDIUM", fraud_risk_score=5.5,
                fraud_flags=json.dumps([]),
                reddit_mentions=100, stocktwits_bullish=20, stocktwits_bearish=30,
                insider_buys=0, insider_sells=3, news_count=12,
                report_json=json.dumps({}),
                user_action="DENY",
                generated_at=datetime(2025, 2, 5, tzinfo=UTC),
            ))
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_reports_list_fields(self, seeded_client):
        resp = await seeded_client.get("/api/reports")
        assert resp.status_code == 200
        reports = resp.json()
        assert len(reports) == 2
        # Most recent first
        r = reports[0]
        assert r["id"] == "rpt_002"
        assert r["ticker"] == "TSLA"
        assert r["mode"] == "consensus"
        assert r["alert_price"] == 180.0
        assert r["alert_change_pct"] == -5.0
        assert r["final_recommendation"] == "AVOID"
        assert r["final_score"] == 3.0
        assert r["final_confidence"] == 0.70
        assert r["fraud_risk_level"] == "MEDIUM"
        assert r["fraud_risk_score"] == 5.5
        assert r["fraud_flags"] == []
        assert r["reddit_mentions"] == 100
        assert r["stocktwits_bullish"] == 20
        assert r["stocktwits_bearish"] == 30
        assert r["insider_buys"] == 0
        assert r["insider_sells"] == 3
        assert r["news_count"] == 12
        assert r["user_action"] == "DENY"
        assert "generated_at" in r

    @pytest.mark.asyncio
    async def test_reports_filter_by_ticker(self, seeded_client):
        resp = await seeded_client.get("/api/reports?ticker=AAPL")
        reports = resp.json()
        assert len(reports) == 1
        assert reports[0]["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_reports_filter_by_recommendation(self, seeded_client):
        resp = await seeded_client.get("/api/reports?recommendation=BUY")
        reports = resp.json()
        assert len(reports) == 1
        assert reports[0]["final_recommendation"] == "BUY"

    @pytest.mark.asyncio
    async def test_report_detail_includes_report_data(self, seeded_client):
        resp = await seeded_client.get("/api/reports/rpt_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "rpt_001"
        assert data["ticker"] == "AAPL"
        assert data["fraud_flags"] == ["low_float"]
        # Detail endpoint includes the full report_data
        assert "report_data" in data
        assert data["report_data"]["analysis"] == "test analysis content"
        assert data["report_data"]["signals"] == ["bullish"]

    @pytest.mark.asyncio
    async def test_report_detail_not_found(self, seeded_client):
        resp = await seeded_client.get("/api/reports/nonexistent")
        assert resp.status_code == 404


class TestUniverseDeep:
    """Validate universe listing with seeded stocks and filtering."""

    @pytest.fixture
    async def seeded_client(self, app):
        from dashboard.deps import get_db
        db = get_db()
        async with db.session() as session:
            session.add(UniverseStockORM(
                ticker="PENNY", name="Penny Corp", exchange="NASDAQ",
                t212_ticker="PENNY_US", sector="Technology", industry="Software",
                market_cap=50_000_000, avg_volume=200_000,
                last_price=2.50, in_universe=True,
                updated_at=datetime(2025, 1, 1, tzinfo=UTC),
            ))
            session.add(UniverseStockORM(
                ticker="CHEAP", name="Cheap Inc", exchange="NYSE",
                t212_ticker="CHEAP_US", sector="Healthcare", industry="Biotech",
                market_cap=20_000_000, avg_volume=500_000,
                last_price=0.80, in_universe=True,
                updated_at=datetime(2025, 1, 1, tzinfo=UTC),
            ))
            session.add(UniverseStockORM(
                ticker="EXPNSV", name="Expensive Ltd", exchange="NASDAQ",
                t212_ticker="EXPNSV_US", sector="Finance", industry="Banking",
                market_cap=500_000_000, avg_volume=1_000_000,
                last_price=25.00, in_universe=False,
                updated_at=datetime(2025, 1, 1, tzinfo=UTC),
            ))
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_universe_response_fields(self, seeded_client):
        resp = await seeded_client.get("/api/universe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # only in_universe=True
        items = data["items"]
        assert len(items) == 2
        # Sorted by ticker by default
        p = items[0]
        assert p["ticker"] == "CHEAP"
        assert p["name"] == "Cheap Inc"
        assert p["exchange"] == "NYSE"
        assert p["sector"] == "Healthcare"
        assert p["industry"] == "Biotech"
        assert p["market_cap"] == 20_000_000
        assert p["avg_volume"] == 500_000
        assert p["last_price"] == 0.80
        assert p["in_universe"] is True
        assert p["is_monitored"] is False
        assert "updated_at" in p

    @pytest.mark.asyncio
    async def test_universe_include_not_in_universe(self, seeded_client):
        resp = await seeded_client.get("/api/universe?in_universe=false")
        data = resp.json()
        assert data["total"] == 3  # all stocks

    @pytest.mark.asyncio
    async def test_universe_filter_by_exchange(self, seeded_client):
        resp = await seeded_client.get("/api/universe?exchange=NYSE")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["ticker"] == "CHEAP"

    @pytest.mark.asyncio
    async def test_universe_filter_by_price(self, seeded_client):
        resp = await seeded_client.get("/api/universe?min_price=1.0&max_price=5.0")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["ticker"] == "PENNY"

    @pytest.mark.asyncio
    async def test_universe_filter_by_market_cap(self, seeded_client):
        resp = await seeded_client.get("/api/universe?min_market_cap=30000000")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["ticker"] == "PENNY"

    @pytest.mark.asyncio
    async def test_universe_pagination(self, seeded_client):
        resp = await seeded_client.get("/api/universe?limit=1&offset=0")
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["has_more"] is True
        resp2 = await seeded_client.get("/api/universe?limit=1&offset=1")
        assert len(resp2.json()["items"]) == 1
        assert resp2.json()["has_more"] is False

    @pytest.mark.asyncio
    async def test_universe_sort_by_last_price(self, seeded_client):
        resp = await seeded_client.get("/api/universe?sort_by=last_price")
        items = resp.json()["items"]
        assert items[0]["ticker"] == "PENNY"  # $2.50 > $0.80 (desc)


class TestStatsDeep:
    """Validate trading stats computation with seeded trade data."""

    @pytest.fixture
    async def seeded_client(self, app):
        from dashboard.deps import get_db
        db = get_db()
        async with db.session() as session:
            # 2 buy trades + 2 closing sell trades (1 win, 1 loss)
            session.add(TradeORM(
                id="s_buy_1", ticker="AAPL", side="BUY",
                quantity=10, price=100.0, total_value=1000.0,
                status="FILLED",
                executed_at=datetime(2025, 1, 5, tzinfo=UTC),
            ))
            session.add(TradeORM(
                id="s_sell_1", ticker="AAPL", side="SELL",
                quantity=10, price=120.0, total_value=1200.0,
                status="FILLED", is_closing_trade=True,
                realised_pnl=200.0, realised_pnl_pct=20.0,
                executed_at=datetime(2025, 1, 10, tzinfo=UTC),
            ))
            session.add(TradeORM(
                id="s_buy_2", ticker="TSLA", side="BUY",
                quantity=5, price=200.0, total_value=1000.0,
                status="FILLED",
                executed_at=datetime(2025, 1, 15, tzinfo=UTC),
            ))
            session.add(TradeORM(
                id="s_sell_2", ticker="TSLA", side="SELL",
                quantity=5, price=180.0, total_value=900.0,
                status="FILLED", is_closing_trade=True,
                realised_pnl=-100.0, realised_pnl_pct=-10.0,
                executed_at=datetime(2025, 1, 20, tzinfo=UTC),
            ))
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_stats_computation(self, seeded_client):
        resp = await seeded_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 4
        assert data["round_trip_trades"] == 2
        assert data["winning_trades"] == 1
        assert data["losing_trades"] == 1
        assert data["win_rate"] == 50.0
        assert data["total_pnl"] == 100.0  # 200 - 100
        assert data["avg_pnl_per_trade"] == 50.0  # 100 / 2
        assert data["best_trade_pnl"] == 200.0
        assert data["worst_trade_pnl"] == -100.0


# ---------------------------------------------------------------------------
# SPA Routing Tests
# ---------------------------------------------------------------------------

class TestSPARouting:
    """Test that the catch-all SPA route serves index.html for frontend routes."""

    @pytest.mark.asyncio
    async def test_api_routes_take_precedence(self, app):
        """API routes should still return JSON, not index.html."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data or "paper_trading" in data

    @pytest.mark.asyncio
    async def test_frontend_route_returns_spa_fallback(self, app):
        """Non-API routes should return index.html or a 404 if frontend not built."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/research")
            # In test env, static dir may not exist, so we get the "not built" message
            # or index.html if the build exists
            assert resp.status_code in (200, 404)
            if resp.status_code == 404:
                assert "not built" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_deeply_nested_frontend_route(self, app):
        """Deeply nested SPA routes should also be handled."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/research/AAPL/quantitative")
            assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_catch_all_does_not_break_api_health(self, app):
        """The catch-all route must not interfere with existing API endpoints."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Existing API endpoints should work normally
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert "application/json" in resp.headers.get("content-type", "")
