"""
Paper trading broker for testing and validation.

Simulates the Trading 212 API without executing real trades.
Uses the market data provider's price cache for realistic price simulation.
Tracks virtual positions, P&L, and trade history in memory.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from broker.base import Broker
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

logger = logging.getLogger(__name__)


class PaperBroker(Broker):
    """
    Virtual broker for paper trading.

    Simulates order execution with realistic fills at current market prices.
    All state is held in memory — resets on restart.
    """

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        currency: str = "GBP",
    ) -> None:
        self._initial_cash = initial_cash
        self._currency = currency
        self._cash = initial_cash
        self._positions: dict[str, Position] = {}
        self._trades: list[TradeRecord] = []
        self._max_trade_history = 10_000  # Cap to prevent unbounded memory growth
        self._pending_orders: list[dict] = []
        self._connected = False

        # Optional: reference to a price provider for realistic fills
        self._price_getter: Callable | None = None

    @property
    def name(self) -> str:
        return "Paper Broker"

    @property
    def is_live(self) -> bool:
        return False

    def set_price_getter(self, fn: Callable) -> None:
        """
        Set a function to get current prices for realistic fills.
        fn(ticker: str) -> float | None
        """
        self._price_getter = fn

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        self._connected = True
        logger.info(
            "Paper broker connected: initial cash = %s %.2f",
            self._currency,
            self._initial_cash,
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("Paper broker disconnected")

    async def health_check(self) -> bool:
        return self._connected

    # =========================================================================
    # Account
    # =========================================================================

    async def get_account_summary(self) -> AccountSummary:
        invested = sum(pos.quantity * pos.avg_price for pos in self._positions.values())
        market_value = sum(pos.quantity * pos.current_price for pos in self._positions.values())
        unrealised_pnl = market_value - invested
        realised_pnl = sum(t.realised_pnl or 0.0 for t in self._trades if t.is_closing_trade)

        return AccountSummary(
            currency=self._currency,
            cash_available=self._cash,
            invested_value=invested,
            total_value=self._cash + market_value,
            unrealised_pnl=unrealised_pnl,
            realised_pnl=realised_pnl,
            updated_at=datetime.now(UTC),
        )

    # =========================================================================
    # Positions
    # =========================================================================

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def update_position_price(self, ticker: str, price: float) -> None:
        """Update a position's current price for P&L calculation."""
        pos = self._positions.get(ticker)
        if pos:
            pos.update_pnl(price)

    # =========================================================================
    # Orders
    # =========================================================================

    async def place_order(self, order: OrderRequest) -> OrderResult:
        """
        Simulate order execution.

        Market orders fill immediately at the current price.
        Limit/stop orders are stored as pending (simplified — no fill simulation).
        """
        if order.order_type == OrderType.MARKET:
            return await self._fill_market_order(order)

        # Limit and stop orders go to pending
        pending_id = uuid4().hex[:12]
        self._pending_orders.append(
            {
                "id": pending_id,
                "ticker": order.ticker,
                "side": order.side.value,
                "type": order.order_type.value,
                "quantity": order.quantity,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        logger.info(
            "Paper: pending %s %s %s qty=%.4f",
            order.order_type.value,
            order.side.value,
            order.ticker,
            order.quantity,
        )

        return OrderResult(
            success=True,
            order_id=pending_id,
            ticker=order.ticker,
            side=order.side,
            status=OrderStatus.SUBMITTED,
        )

    async def cancel_order(self, order_id: str) -> bool:
        for i, pending in enumerate(self._pending_orders):
            if pending["id"] == order_id:
                self._pending_orders.pop(i)
                logger.info("Paper: cancelled order %s", order_id)
                return True
        return False

    async def get_pending_orders(self) -> list[dict]:
        return list(self._pending_orders)

    # =========================================================================
    # History
    # =========================================================================

    async def get_trade_history(self, limit: int = 50) -> list[TradeRecord]:
        return sorted(self._trades, key=lambda t: t.executed_at, reverse=True)[:limit]

    # =========================================================================
    # Internal: fill simulation
    # =========================================================================

    async def _fill_market_order(self, order: OrderRequest) -> OrderResult:
        """Simulate immediate market order fill."""
        # Get fill price
        fill_price = self._get_current_price(order.ticker)
        if fill_price is None:
            return OrderResult(
                success=False,
                ticker=order.ticker,
                side=order.side,
                error_message="No price available for paper fill",
            )

        # Calculate quantity if value-based order
        quantity = order.quantity
        if order.target_value and order.target_value > 0 and fill_price > 0:
            quantity = order.target_value / fill_price

        if quantity <= 0:
            return OrderResult(
                success=False,
                ticker=order.ticker,
                side=order.side,
                error_message="Invalid order quantity",
            )

        total_value = quantity * fill_price

        if order.side == Side.BUY:
            return await self._execute_buy(order.ticker, quantity, fill_price, total_value)
        else:
            return await self._execute_sell(order.ticker, quantity, fill_price, total_value)

    async def _execute_buy(
        self,
        ticker: str,
        quantity: float,
        price: float,
        total_value: float,
    ) -> OrderResult:
        """Execute a paper buy."""
        if total_value > self._cash:
            return OrderResult(
                success=False,
                ticker=ticker,
                side=Side.BUY,
                error_message=f"Insufficient cash: need {total_value:.2f}, have {self._cash:.2f}",
            )

        self._cash -= total_value

        # Update or create position
        existing = self._positions.get(ticker)
        if existing:
            # Average up/down
            total_qty = existing.quantity + quantity
            total_cost = (existing.quantity * existing.avg_price) + total_value
            existing.quantity = total_qty
            existing.avg_price = total_cost / total_qty if total_qty > 0 else 0
            existing.update_pnl(price)
        else:
            pos = Position(
                ticker=ticker,
                quantity=quantity,
                avg_price=price,
                current_price=price,
                opened_at=datetime.now(UTC),
            )
            pos.update_pnl(price)
            self._positions[ticker] = pos

        trade = TradeRecord(
            id=uuid4().hex[:12],
            ticker=ticker,
            side=Side.BUY,
            quantity=quantity,
            price=price,
            total_value=total_value,
            status=OrderStatus.FILLED,
            executed_at=datetime.now(UTC),
        )
        self._trades.append(trade)
        if len(self._trades) > self._max_trade_history:
            self._trades = self._trades[-self._max_trade_history :]

        logger.info(
            "Paper BUY: %s qty=%.4f @ $%.4f (total=$%.2f)", ticker, quantity, price, total_value
        )

        return OrderResult(
            success=True,
            order_id=trade.id,
            ticker=ticker,
            side=Side.BUY,
            filled_quantity=quantity,
            filled_price=price,
            status=OrderStatus.FILLED,
        )

    async def _execute_sell(
        self,
        ticker: str,
        quantity: float,
        price: float,
        total_value: float,
    ) -> OrderResult:
        """Execute a paper sell."""
        existing = self._positions.get(ticker)
        if not existing or existing.quantity < quantity:
            avail = existing.quantity if existing else 0
            return OrderResult(
                success=False,
                ticker=ticker,
                side=Side.SELL,
                error_message=f"Insufficient position: need {quantity:.4f}, have {avail:.4f}",
            )

        self._cash += total_value

        # Calculate P&L
        cost_basis = quantity * existing.avg_price
        realised_pnl = total_value - cost_basis
        realised_pnl_pct = (realised_pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        # Update position
        existing.quantity -= quantity
        if math.isclose(existing.quantity, 0.0, abs_tol=1e-9) or existing.quantity < 0:
            del self._positions[ticker]
        else:
            existing.update_pnl(price)

        trade = TradeRecord(
            id=uuid4().hex[:12],
            ticker=ticker,
            side=Side.SELL,
            quantity=quantity,
            price=price,
            total_value=total_value,
            status=OrderStatus.FILLED,
            is_closing_trade=True,
            realised_pnl=realised_pnl,
            realised_pnl_pct=realised_pnl_pct,
            executed_at=datetime.now(UTC),
        )
        self._trades.append(trade)
        if len(self._trades) > self._max_trade_history:
            self._trades = self._trades[-self._max_trade_history :]

        logger.info(
            "Paper SELL: %s qty=%.4f @ $%.4f P&L=$%.2f (%.1f%%)",
            ticker,
            quantity,
            price,
            realised_pnl,
            realised_pnl_pct,
        )

        return OrderResult(
            success=True,
            order_id=trade.id,
            ticker=ticker,
            side=Side.SELL,
            filled_quantity=quantity,
            filled_price=price,
            status=OrderStatus.FILLED,
        )

    def _get_current_price(self, ticker: str) -> float | None:
        """Get current price from price getter or existing position."""
        if self._price_getter:
            price = self._price_getter(ticker)
            if price is not None:
                return price

        # Fall back to position's last known price
        pos = self._positions.get(ticker)
        if pos and pos.current_price > 0:
            return pos.current_price

        return None
