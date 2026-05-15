"""Tests for Phase 5: Broker modules."""

from __future__ import annotations

import pytest

from broker.paper_broker import PaperBroker
from broker.trading212 import RateLimiter, Trading212Broker
from config.settings import Settings, T212Environment
from core.models import OrderRequest, OrderType, Side

# =============================================================================
# Paper Broker tests
# =============================================================================


class TestPaperBroker:
    @pytest.mark.asyncio
    async def test_initial_state(self) -> None:
        broker = PaperBroker(initial_cash=10_000.0)
        await broker.connect()

        summary = await broker.get_account_summary()
        assert summary.cash_available == 10_000.0
        assert summary.invested_value == 0.0
        assert summary.total_value == 10_000.0

        positions = await broker.get_positions()
        assert positions == []

        assert broker.name == "Paper Broker"
        assert broker.is_live is False

    @pytest.mark.asyncio
    async def test_buy_order(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()

        # Set a price getter
        broker.set_price_getter(lambda t: 2.50 if t == "TEST" else None)

        order = OrderRequest(ticker="TEST", side=Side.BUY, quantity=10.0)
        result = await broker.place_order(order)

        assert result.success is True
        assert result.filled_quantity == 10.0
        assert result.filled_price == 2.50

        # Check position
        pos = await broker.get_position("TEST")
        assert pos is not None
        assert pos.quantity == 10.0
        assert pos.avg_price == 2.50

        # Check cash deducted
        summary = await broker.get_account_summary()
        assert summary.cash_available == pytest.approx(975.0)

    @pytest.mark.asyncio
    async def test_buy_insufficient_cash(self) -> None:
        broker = PaperBroker(initial_cash=10.0)
        await broker.connect()
        broker.set_price_getter(lambda t: 100.0)

        order = OrderRequest(ticker="EXPENSIVE", side=Side.BUY, quantity=1.0)
        result = await broker.place_order(order)

        assert result.success is False
        assert "Insufficient cash" in result.error_message

    @pytest.mark.asyncio
    async def test_sell_order(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()
        broker.set_price_getter(lambda t: 2.50)

        # Buy first
        buy = OrderRequest(ticker="TEST", side=Side.BUY, quantity=10.0)
        await broker.place_order(buy)

        # Sell at a profit
        broker.set_price_getter(lambda t: 3.00)
        sell = OrderRequest(ticker="TEST", side=Side.SELL, quantity=10.0)
        result = await broker.place_order(sell)

        assert result.success is True
        assert result.filled_price == 3.00

        # Position should be closed
        pos = await broker.get_position("TEST")
        assert pos is None

        # Cash should reflect profit
        summary = await broker.get_account_summary()
        assert summary.cash_available == pytest.approx(1005.0)  # 1000 - 25 + 30 = 1005

    @pytest.mark.asyncio
    async def test_sell_insufficient_position(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()
        broker.set_price_getter(lambda t: 5.0)

        sell = OrderRequest(ticker="NONE", side=Side.SELL, quantity=10.0)
        result = await broker.place_order(sell)

        assert result.success is False
        assert "Insufficient position" in result.error_message

    @pytest.mark.asyncio
    async def test_value_based_order(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()
        broker.set_price_getter(lambda t: 2.00)

        # Buy $100 worth
        order = OrderRequest(
            ticker="TEST",
            side=Side.BUY,
            target_value=100.0,
        )
        result = await broker.place_order(order)

        assert result.success is True
        assert result.filled_quantity == pytest.approx(50.0)
        assert result.filled_price == 2.00

    @pytest.mark.asyncio
    async def test_multiple_buys_average_price(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()

        # Buy 10 @ $2.00
        broker.set_price_getter(lambda t: 2.00)
        await broker.place_order(OrderRequest(ticker="TEST", side=Side.BUY, quantity=10.0))

        # Buy 10 @ $3.00
        broker.set_price_getter(lambda t: 3.00)
        await broker.place_order(OrderRequest(ticker="TEST", side=Side.BUY, quantity=10.0))

        pos = await broker.get_position("TEST")
        assert pos is not None
        assert pos.quantity == 20.0
        assert pos.avg_price == pytest.approx(2.50)  # (20 + 30) / 20

    @pytest.mark.asyncio
    async def test_trade_history(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()
        broker.set_price_getter(lambda t: 2.00)

        await broker.place_order(OrderRequest(ticker="A", side=Side.BUY, quantity=5.0))
        await broker.place_order(OrderRequest(ticker="B", side=Side.BUY, quantity=5.0))

        history = await broker.get_trade_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_pending_order_and_cancel(self) -> None:
        broker = PaperBroker(initial_cash=1_000.0)
        await broker.connect()

        # Limit order goes to pending
        order = OrderRequest(
            ticker="TEST",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10.0,
            limit_price=1.50,
        )
        result = await broker.place_order(order)
        assert result.success is True

        pending = await broker.get_pending_orders()
        assert len(pending) == 1

        # Cancel it
        cancelled = await broker.cancel_order(result.order_id)
        assert cancelled is True

        pending = await broker.get_pending_orders()
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        broker = PaperBroker()
        assert await broker.health_check() is False

        await broker.connect()
        assert await broker.health_check() is True

        await broker.disconnect()
        assert await broker.health_check() is False


# =============================================================================
# Trading 212 Broker tests (unit — no real API calls)
# =============================================================================


class TestTrading212Broker:
    def test_ticker_mapping(self) -> None:
        settings = Settings(t212_api_key="test", t212_api_secret="test")
        from unittest.mock import MagicMock

        db = MagicMock()
        broker = Trading212Broker(settings, db)

        assert broker._to_t212_ticker("AAPL") == "AAPL_US_EQ"
        assert broker._to_t212_ticker("AAPL_US_EQ") == "AAPL_US_EQ"
        assert broker._from_t212_ticker("AAPL_US_EQ") == "AAPL"
        assert broker._from_t212_ticker("TSLA_US_EQ") == "TSLA"

    def test_name_and_live_flag(self) -> None:
        from unittest.mock import MagicMock

        db = MagicMock()

        demo = Trading212Broker(Settings(t212_api_key="k", t212_api_secret="s"), db)
        assert "DEMO" in demo.name
        assert demo.is_live is False

        live = Trading212Broker(
            Settings(
                t212_api_key="k",
                t212_api_secret="s",
                t212_environment=T212Environment.LIVE,
            ),
            db,
        )
        assert "LIVE" in live.name
        assert live.is_live is True

    def test_circuit_breaker_initially_closed(self) -> None:
        from unittest.mock import MagicMock

        db = MagicMock()
        broker = Trading212Broker(Settings(t212_api_key="k", t212_api_secret="s"), db)
        assert broker._is_circuit_open() is False


# =============================================================================
# Rate Limiter tests
# =============================================================================


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_rate_limiter_allows_first_call(self) -> None:
        limiter = RateLimiter()
        # Should not block
        await limiter.acquire("test", 0.1)

    @pytest.mark.asyncio
    async def test_different_endpoints_independent(self) -> None:
        import time

        limiter = RateLimiter()

        start = time.monotonic()
        await limiter.acquire("endpoint_a", 10.0)
        await limiter.acquire("endpoint_b", 10.0)
        elapsed = time.monotonic() - start

        # Both should complete quickly since they're different endpoints
        assert elapsed < 1.0
