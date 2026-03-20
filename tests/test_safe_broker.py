"""Tests for SafeBroker paper trading safety wrapper.

CRITICAL: These tests verify that paper_mode=True makes it IMPOSSIBLE
for orders to reach the inner (potentially live) broker.
"""

import pytest
from unittest.mock import AsyncMock

from broker.base import Broker
from broker.paper_broker import PaperBroker
from broker.safe_broker import SafeBroker
from core.models import (
    AccountSummary,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TradeRecord,
)


def _make_order(ticker: str = "AAPL", side: Side = Side.BUY) -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        side=side,
        order_type=OrderType.MARKET,
        quantity=10.0,
    )


def _make_order_result(success: bool = True) -> OrderResult:
    return OrderResult(
        success=success,
        order_id="test-123",
        ticker="AAPL",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        filled_quantity=10.0,
        filled_price=1.50,
    )


@pytest.fixture
def inner_mock() -> AsyncMock:
    """Mock of the inner (potentially live) broker. Must NEVER be called in paper mode."""
    mock = AsyncMock(spec=Broker)
    mock.name = "Trading 212 (LIVE)"
    mock.is_live = True
    mock.place_order.return_value = _make_order_result()
    mock.cancel_order.return_value = True
    mock.get_account_summary.return_value = AccountSummary(
        currency="GBP",
        cash_available=5000.0,
        invested_value=3000.0,
        total_value=8000.0,
    )
    mock.get_positions.return_value = [
        Position(ticker="AAPL", quantity=10, avg_price=1.5, current_price=1.6),
    ]
    mock.get_pending_orders.return_value = []
    mock.get_trade_history.return_value = []
    mock.health_check.return_value = True
    return mock


@pytest.fixture
def paper_broker() -> PaperBroker:
    """Real PaperBroker (safe — in-memory only)."""
    broker = PaperBroker(initial_cash=10_000.0, currency="GBP")
    return broker


class TestPaperModeBlocksLiveOrders:
    """The most critical test class — verifies orders NEVER reach live broker."""

    @pytest.mark.asyncio
    async def test_place_order_routes_to_paper_broker(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()

        # Give paper broker a price so it can fill
        paper_broker.set_price_getter(lambda t: 1.50)

        order = _make_order()
        result = await safe.place_order(order)

        # Order should succeed via paper broker
        assert result.success is True

        # CRITICAL: inner broker must NEVER have been called for place_order
        inner_mock.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_order_routes_to_paper_broker(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()

        await safe.cancel_order("some-order-id")

        # CRITICAL: inner broker must NEVER have been called
        inner_mock.cancel_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_sell_order_routes_to_paper_broker(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()
        paper_broker.set_price_getter(lambda t: 1.50)

        # First buy to have a position
        buy_order = _make_order(side=Side.BUY)
        await safe.place_order(buy_order)

        # Then sell
        sell_order = _make_order(side=Side.SELL)
        await safe.place_order(sell_order)

        # CRITICAL: inner broker must NEVER have been called
        inner_mock.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_orders_never_reach_inner(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()
        paper_broker.set_price_getter(lambda t: 1.50)

        for _ in range(10):
            await safe.place_order(_make_order())

        # CRITICAL: zero calls to inner broker
        assert inner_mock.place_order.call_count == 0


class TestPaperModeReadThroughToInner:
    """Read-only methods should delegate to the inner (real) broker."""

    @pytest.mark.asyncio
    async def test_get_account_summary_from_inner(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        summary = await safe.get_account_summary()

        assert summary.cash_available == 5000.0
        inner_mock.get_account_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_positions_from_inner(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        positions = await safe.get_positions()

        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        inner_mock.get_positions.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_from_inner(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        result = await safe.health_check()

        assert result is True
        inner_mock.health_check.assert_called_once()


class TestPaperModeProperties:
    def test_is_live_false_in_paper_mode(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        assert safe.is_live is False

    def test_is_live_true_when_not_paper_mode(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=False)
        assert safe.is_live is True

    def test_name_includes_paper_mode_label(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        assert "PAPER MODE" in safe.name

    def test_name_shows_inner_when_live(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=False)
        assert "PAPER MODE" not in safe.name

    def test_paper_mode_property(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        assert safe.paper_mode is True


class TestLiveModePassthrough:
    """When paper_mode=False, orders should go to the inner broker."""

    @pytest.mark.asyncio
    async def test_place_order_goes_to_inner(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=False)
        order = _make_order()
        result = await safe.place_order(order)

        assert result.success is True
        inner_mock.place_order.assert_called_once_with(order)

    @pytest.mark.asyncio
    async def test_cancel_order_goes_to_inner(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=False)
        await safe.cancel_order("order-123")

        inner_mock.cancel_order.assert_called_once_with("order-123")

    @pytest.mark.asyncio
    async def test_trade_history_from_inner_when_live(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=False)
        await safe.get_trade_history()

        inner_mock.get_trade_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_orders_from_inner_when_live(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=False)
        await safe.get_pending_orders()

        inner_mock.get_pending_orders.assert_called_once()


class TestPaperModeTradeHistory:
    """In paper mode, trade history and pending orders come from paper broker."""

    @pytest.mark.asyncio
    async def test_trade_history_from_paper_broker(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()
        paper_broker.set_price_getter(lambda t: 1.50)

        # Place a paper order to generate history
        await safe.place_order(_make_order())
        history = await safe.get_trade_history()

        assert len(history) == 1
        # Inner broker should NOT be called for trade history in paper mode
        inner_mock.get_trade_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_orders_from_paper_broker(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()

        await safe.get_pending_orders()
        inner_mock.get_pending_orders.assert_not_called()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_connect_connects_both(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()

        inner_mock.connect.assert_called_once()
        assert paper_broker._connected is True

    @pytest.mark.asyncio
    async def test_disconnect_disconnects_both(self, inner_mock, paper_broker):
        safe = SafeBroker(inner=inner_mock, paper_broker=paper_broker, paper_mode=True)
        await safe.connect()
        await safe.disconnect()

        inner_mock.disconnect.assert_called_once()
        assert paper_broker._connected is False
