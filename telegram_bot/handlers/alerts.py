"""
Alert display handler.

Listens for REPORT_READY events and sends formatted alerts to Telegram.
"""

from __future__ import annotations

import logging
from typing import Any

from core.events import EventBus, EventType
from core.models import AnalysisReport
from telegram_bot.formatters import format_alert_message

logger = logging.getLogger(__name__)


async def alert_listener(
    event_bus: EventBus,
    bot: Any,
) -> None:
    """
    Background task that listens for REPORT_READY events
    and sends formatted alerts to Telegram.
    """
    async for event in event_bus.subscribe(EventType.REPORT_READY):
        report = event.data
        if not isinstance(report, AnalysisReport):
            continue

        try:
            message = format_alert_message(report)
            await bot.send_alert(message)
            logger.info("Sent Telegram alert for %s", report.ticker)
        except Exception:
            logger.exception("Failed to send Telegram alert for %s", report.ticker)
