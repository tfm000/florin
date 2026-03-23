"""
Shared dashboard dependencies.

Stores references to the database, event bus, broker, settings,
and WebSocket manager. Set during app startup via create_app().
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings
    from core.events import EventBus
    from db.database import Database
    from dashboard.ws import ConnectionManager

_state: dict = {}


def set_state(key: str, value: object) -> None:
    _state[key] = value


def get_db() -> "Database":
    return _state["db"]


def get_event_bus() -> "EventBus":
    return _state["event_bus"]


def get_settings() -> "Settings":
    return _state["settings"]


def get_broker():
    return _state.get("broker")


def get_ws_manager() -> "ConnectionManager":
    return _state["ws_manager"]


def get_shutdown_callback():
    return _state.get("shutdown_callback")


def get_screener_alert_service():
    return _state.get("screener_alert_service")


def get_data_provider():
    return _state.get("data_provider")


def get_yfinance_provider():
    return _state.get("yfinance_provider")


def get_sentiment_aggregator():
    return _state.get("sentiment_aggregator")


def get_rf_fetcher():
    return _state.get("rf_fetcher")


def get_policy_rate_fetcher():
    return _state.get("policy_rate_fetcher")
