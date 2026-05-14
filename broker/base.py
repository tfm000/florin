"""
Abstract interface for broker integrations.

Implementations: Trading212Broker, PaperBroker
Swappable — use PaperBroker for testing, Trading212Broker for live.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import (
    AccountSummary,
    OrderRequest,
    OrderResult,
    Position,
    TradeRecord,
)


class Broker(ABC):
    """
    Interface for any brokerage API.

    Handles order execution, position monitoring, and account data.
    Implementations must be rate-limit aware and handle retries internally.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Broker name (e.g., 'Trading 212', 'Paper')."""
        ...

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """Whether this broker executes real trades."""
        ...

    # --- Account ---

    @abstractmethod
    async def get_account_summary(self) -> AccountSummary:
        """Get account balance, invested value, and totals."""
        ...

    # --- Positions ---

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    async def get_position(self, ticker: str) -> Position | None:
        """Get a specific position by ticker, or None if not held."""
        ...

    # --- Orders ---

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """
        Place a buy or sell order.

        For sell orders, quantity should be positive — the broker
        implementation handles the sign convention internally.

        Returns OrderResult with success/failure and fill details.
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if cancelled."""
        ...

    @abstractmethod
    async def get_pending_orders(self) -> list[dict]:
        """Get all pending/open orders."""
        ...

    # --- History ---

    @abstractmethod
    async def get_trade_history(self, limit: int = 50) -> list[TradeRecord]:
        """Get executed trade history, most recent first."""
        ...

    # --- Lifecycle ---

    @abstractmethod
    async def connect(self) -> None:
        """Initialise connection, validate credentials."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if broker API is reachable and authenticated."""
        ...

    async def __aenter__(self) -> Broker:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()
