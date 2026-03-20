"""
Position monitoring handler.

Listens for POSITION_UPDATE events and sends proactive alerts
when positions hit configured thresholds.
"""

from __future__ import annotations

import logging
from typing import Any

from core.events import EventBus, EventType
from core.models import Position
from telegram_bot.formatters import escape_md

logger = logging.getLogger(__name__)

# Alert thresholds for position P&L
POSITION_ALERT_PCT = 10.0  # Alert at ±10%


async def position_listener(
    event_bus: EventBus,
    bot: Any,
    alert_threshold_pct: float = POSITION_ALERT_PCT,
) -> None:
    """
    Background task that listens for POSITION_UPDATE events
    and sends proactive alerts when thresholds are hit.
    """
    # Track which positions we've already alerted on
    alerted: set[str] = set()

    async for event in event_bus.subscribe(EventType.POSITION_UPDATE):
        positions = event.data
        if not isinstance(positions, list):
            continue

        for pos in positions:
            if not isinstance(pos, Position):
                continue

            key = f"{pos.ticker}:{'+' if pos.unrealised_pnl_pct >= 0 else '-'}"

            if abs(pos.unrealised_pnl_pct) >= alert_threshold_pct and key not in alerted:
                emoji = "🟢" if pos.unrealised_pnl_pct >= 0 else "🔴"
                direction = "UP" if pos.unrealised_pnl_pct >= 0 else "DOWN"

                msg = (
                    f"{emoji} *Position Alert: {escape_md(pos.ticker)}*\n"
                    f"{escape_md(direction)} {escape_md(f'{abs(pos.unrealised_pnl_pct):.1f}%')}\n"
                    f"P&L: {escape_md(f'${pos.unrealised_pnl:+.2f}')}"
                )

                try:
                    await bot.send_message(msg)
                    alerted.add(key)
                except Exception:
                    logger.exception(
                        "Failed to send position alert for %s", pos.ticker
                    )

    # Listen for stop-loss events too
    async for event in event_bus.subscribe(EventType.POSITION_STOP_LOSS):
        pos = event.data
        if isinstance(pos, Position):
            msg = (
                f"🛑 *STOP LOSS HIT: {escape_md(pos.ticker)}*\n"
                f"P&L: {escape_md(f'${pos.unrealised_pnl:+.2f}')} "
                f"\\({escape_md(f'{pos.unrealised_pnl_pct:+.1f}%')}\\)"
            )
            try:
                await bot.send_message(msg)
            except Exception:
                logger.exception("Failed to send stop-loss alert for %s", pos.ticker)
