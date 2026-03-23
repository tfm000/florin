"""
FastAPI Depends() callables for the Florin Terminal dashboard.

These provide idiomatic FastAPI dependency injection for new routes,
wrapping the existing service locator in dashboard/deps.py.

Usage in route handlers:
    @router.get("/something")
    async def get_something(
        settings: Settings = Depends(get_settings_dep),
        session: AsyncSession = Depends(get_db_session),
    ):
        ...
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ServiceUnavailableError
from dashboard.deps import (
    get_broker,
    get_data_provider,
    get_db,
    get_event_bus,
    get_settings,
    get_yfinance_provider,
)

if TYPE_CHECKING:
    from broker.base import Broker
    from config.settings import Settings
    from core.events import EventBus
    from data.yfinance_provider import YFinanceProvider


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session. Auto-commits on success, rolls back on error."""
    db = get_db()
    async with db.session() as session:
        yield session


def get_settings_dep() -> "Settings":
    """Return the application settings."""
    return get_settings()


def get_yfinance_dep() -> "YFinanceProvider":
    """Return the yfinance provider."""
    provider = get_yfinance_provider()
    if provider is None:
        raise ServiceUnavailableError("YFinance provider not initialised")
    return provider


def get_broker_dep() -> "Broker":
    """Return the broker, raising 503 if not configured."""
    broker = get_broker()
    if broker is None:
        raise ServiceUnavailableError("Broker not configured")
    return broker


def get_event_bus_dep() -> "EventBus":
    """Return the event bus."""
    return get_event_bus()


def get_data_provider_dep():
    """Return the market data provider, raising 503 if not configured."""
    provider = get_data_provider()
    if provider is None:
        raise ServiceUnavailableError("Market data provider not configured")
    return provider
