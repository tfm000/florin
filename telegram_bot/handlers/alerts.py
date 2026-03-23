"""
Alert display handlers.

Listens for REPORT_READY and SCREENER_ALERT events and sends
formatted alerts to Telegram with appropriate context.
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings
from core.events import EventBus, EventType
from core.models import AnalysisReport
from telegram_bot.formatters import format_alert_message, format_screener_alert_message

logger = logging.getLogger(__name__)


def _format_position_size(settings: Settings) -> str:
    unit = settings.position_size_unit
    size = settings.default_position_size
    if unit == "gbp":
        return f"£{size:.2f}"
    elif unit == "usd":
        return f"${size:.2f}"
    return f"{size:.0f} shares"


async def alert_listener(
    event_bus: EventBus,
    bot: Any,
    broker: Any = None,
    settings: Settings | None = None,
) -> None:
    """
    Background task that listens for REPORT_READY events
    and sends formatted alerts to Telegram with account context.
    """
    async for event in event_bus.subscribe(EventType.REPORT_READY):
        report = event.data
        if not isinstance(report, AnalysisReport):
            continue

        try:
            # Gather account context if broker available
            broker_summary = None
            penny_position_count = 0
            default_order_size = ""

            if broker:
                try:
                    broker_summary = await broker.get_account_summary()
                except Exception:
                    logger.debug("Could not fetch account summary for alert context")

                try:
                    positions = await broker.get_positions()
                    price_max = settings.scan_price_max if settings else 5.0
                    penny_position_count = sum(
                        1 for p in positions
                        if p.current_price and p.current_price < price_max
                    )
                except Exception:
                    logger.debug("Could not fetch positions for alert context")

            if settings:
                default_order_size = _format_position_size(settings)

            message = format_alert_message(
                report,
                broker_summary=broker_summary,
                penny_position_count=penny_position_count,
                default_order_size=default_order_size,
            )
            await bot.send_alert(message)
            logger.info("Sent Telegram alert for %s", report.ticker)
        except Exception:
            logger.exception("Failed to send Telegram alert for %s", report.ticker)


async def screener_alert_listener(
    event_bus: EventBus,
    bot: Any,
    broker: Any = None,
    settings: Settings | None = None,
) -> None:
    """
    Background task that listens for SCREENER_ALERT events
    and sends formatted screener alerts to Telegram.

    Screener alerts include a BUY button if a broker is configured.
    """
    async for event in event_bus.subscribe(EventType.SCREENER_ALERT):
        alert_data = event.data
        if not isinstance(alert_data, dict):
            continue

        ticker = alert_data.get("ticker", "")
        try:
            message = format_screener_alert_message(alert_data)
            await bot.send_screener_alert(message, ticker=ticker)
            logger.info(
                "Sent screener alert for %s (screener: %s)",
                ticker, alert_data.get("screener_name", "?"),
            )
        except Exception:
            logger.exception("Failed to send screener alert for %s", ticker)
