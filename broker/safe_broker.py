"""
Safety wrapper broker that enforces paper trading mode.

When paper_trading=True (the default), ALL order-related methods
(place_order, cancel_order) are routed to a PaperBroker regardless
of the inner broker. Read-only methods (positions, account, history)
pass through to the inner broker so you can see real account data.

This provides a hard, application-level safety boundary that makes
it impossible for orders to reach a live broker by accident.
"""

from __future__ import annotations

import logging

from broker.base import Broker
from broker.paper_broker import PaperBroker
from core.models import (
    AccountSummary,
    OrderRequest,
    OrderResult,
    Position,
    TradeRecord,
)

logger = logging.getLogger(__name__)


class SafeBroker(Broker):
    """
    Application-level paper trading enforcer.

    Wraps any broker and intercepts all mutating operations when
    paper_mode is True. The inner broker is only used for read-only
    data (positions, account summary, trade history).
    """

    def __init__(
        self,
        inner: Broker,
        paper_broker: PaperBroker,
        paper_mode: bool = True,
    ) -> None:
        self._inner = inner
        self._paper = paper_broker
        self._paper_mode = paper_mode

        if self._paper_mode:
            logger.info(
                "SafeBroker: PAPER MODE ACTIVE — all orders routed to paper broker. "
                "Inner broker (%s) is read-only.",
                inner.name,
            )
        else:
            logger.warning(
                "SafeBroker: LIVE TRADING ENABLED — orders will reach %s",
                inner.name,
            )

    @property
    def name(self) -> str:
        if self._paper_mode:
            return f"{self._inner.name} [PAPER MODE]"
        return self._inner.name

    @property
    def is_live(self) -> bool:
        return not self._paper_mode and self._inner.is_live

    @property
    def paper_mode(self) -> bool:
        return self._paper_mode

    @property
    def inner_broker(self) -> Broker:
        """Access to the underlying broker (for health checks, etc.)."""
        return self._inner

    # =========================================================================
    # Read-only: delegate to inner broker (real data)
    # =========================================================================

    async def get_account_summary(self) -> AccountSummary:
        return await self._inner.get_account_summary()

    async def get_positions(self) -> list[Position]:
        return await self._inner.get_positions()

    async def get_position(self, ticker: str) -> Position | None:
        return await self._inner.get_position(ticker)

    async def get_trade_history(self, limit: int = 50) -> list[TradeRecord]:
        if self._paper_mode:
            # In paper mode, show paper trades (real history wouldn't have our paper trades)
            return await self._paper.get_trade_history(limit)
        return await self._inner.get_trade_history(limit)

    async def get_pending_orders(self) -> list[dict]:
        if self._paper_mode:
            return await self._paper.get_pending_orders()
        return await self._inner.get_pending_orders()

    # =========================================================================
    # Mutating: route to paper broker when paper_mode=True
    # =========================================================================

    async def place_order(self, order: OrderRequest) -> OrderResult:
        if self._paper_mode:
            logger.info(
                "PAPER MODE: %s %s %s qty=%.4f routed to paper broker",
                order.side.value, order.order_type.value, order.ticker, order.quantity,
            )
            return await self._paper.place_order(order)
        return await self._inner.place_order(order)

    async def cancel_order(self, order_id: str) -> bool:
        if self._paper_mode:
            return await self._paper.cancel_order(order_id)
        return await self._inner.cancel_order(order_id)

    # =========================================================================
    # Lifecycle: manage both brokers
    # =========================================================================

    async def connect(self) -> None:
        await self._inner.connect()
        await self._paper.connect()

    async def disconnect(self) -> None:
        await self._inner.disconnect()
        await self._paper.disconnect()

    async def health_check(self) -> bool:
        return await self._inner.health_check()
