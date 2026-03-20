"""
Telegram inline button callback handlers.

Handles BUY, DENY, and REPORT button presses from alert messages.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Dispatcher
from aiogram.types import CallbackQuery

from config.settings import Settings
from core.models import OrderRequest, Side
from telegram_bot.formatters import escape_md, format_trade_confirmation

logger = logging.getLogger(__name__)


def register_callback_handlers(
    dp: Dispatcher,
    settings: Settings,
    broker: Any = None,
) -> None:
    """Register all callback query handlers."""
    chat_id = settings.telegram_chat_id

    def _authorised(query: CallbackQuery) -> bool:
        return str(query.message.chat.id) == chat_id

    @dp.callback_query(lambda c: c.data == "buy")
    async def cb_buy(query: CallbackQuery) -> None:
        if not _authorised(query):
            await query.answer("Unauthorised", show_alert=True)
            return

        if not broker:
            await query.answer("No broker connected", show_alert=True)
            return

        # Extract ticker from the message text
        ticker = _extract_ticker(query.message.text or "")
        if not ticker:
            await query.answer("Could not parse ticker", show_alert=True)
            return

        await query.answer(f"Placing buy order for {ticker}...")

        try:
            order = OrderRequest(
                ticker=ticker,
                side=Side.BUY,
                target_value=settings.default_position_size,
            )
            result = await broker.place_order(order)

            if result.success:
                msg = format_trade_confirmation(
                    ticker, "BUY", result.filled_quantity, result.filled_price,
                )
                await query.message.answer(msg)
            else:
                await query.message.answer(
                    f"❌ Order failed: {escape_md(result.error_message)}"
                )

        except Exception as e:
            await query.message.answer(f"❌ Error: {escape_md(str(e))}")

    @dp.callback_query(lambda c: c.data == "deny")
    async def cb_deny(query: CallbackQuery) -> None:
        if not _authorised(query):
            return
        await query.answer("Alert dismissed")
        # Edit message to show it was denied
        try:
            original = query.message.text or ""
            await query.message.edit_text(
                original + "\n\n_❌ Denied_",
            )
        except Exception:
            pass

    @dp.callback_query(lambda c: c.data == "report")
    async def cb_report(query: CallbackQuery) -> None:
        if not _authorised(query):
            return
        await query.answer("Full report view — coming soon", show_alert=True)

    @dp.callback_query(lambda c: c.data and c.data.startswith("sell:"))
    async def cb_sell(query: CallbackQuery) -> None:
        if not _authorised(query):
            return

        if not broker:
            await query.answer("No broker connected", show_alert=True)
            return

        ticker = (query.data or "").split(":", 1)[1] if query.data else ""
        if not ticker:
            await query.answer("Invalid ticker", show_alert=True)
            return

        try:
            pos = await broker.get_position(ticker)
            if not pos:
                await query.answer(f"No position in {ticker}", show_alert=True)
                return

            order = OrderRequest(
                ticker=ticker,
                side=Side.SELL,
                quantity=pos.quantity,
            )
            result = await broker.place_order(order)

            if result.success:
                msg = format_trade_confirmation(
                    ticker, "SELL", result.filled_quantity, result.filled_price,
                )
                await query.message.answer(msg)
            else:
                await query.message.answer(
                    f"❌ Sell failed: {escape_md(result.error_message)}"
                )

        except Exception as e:
            await query.message.answer(f"❌ Error: {escape_md(str(e))}")


def _extract_ticker(text: str) -> str:
    """Extract ticker symbol from alert message text."""
    # Look for pattern like "ALERT: $TICKER" or "$TICKER"
    import re
    match = re.search(r"\$([A-Z]{1,5})\b", text)
    if match:
        return match.group(1)
    return ""
