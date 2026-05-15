"""
Telegram inline button callback handlers.

Handles BUY, DENY, REPORT, SELL, and screener alert button presses.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message

from config.settings import Settings
from core.models import OrderRequest, Side
from telegram_bot.formatters import escape_md, format_trade_confirmation

logger = logging.getLogger(__name__)


def _accessible_message(query: CallbackQuery) -> Message | None:
    """Return the callback's originating message if it is still accessible.

    ``CallbackQuery.message`` can be ``None`` or an ``InaccessibleMessage``
    (for example when the original message is too old); in those cases the
    bot cannot read or edit it, so handlers must bail out gracefully rather
    than raise ``AttributeError``.
    """
    message = query.message
    return message if isinstance(message, Message) else None


def _build_buy_order(ticker: str, settings: Settings) -> OrderRequest:
    """Build a buy order using the configured position size settings."""
    unit = settings.position_size_unit
    size = settings.default_position_size
    if unit == "shares":
        return OrderRequest(ticker=ticker, side=Side.BUY, quantity=size)
    return OrderRequest(ticker=ticker, side=Side.BUY, target_value=size)


async def _execute_buy(
    message: Message,
    ticker: str,
    broker: Any,
    settings: Settings,
) -> None:
    """Execute a buy order and send confirmation/error to chat."""
    try:
        order = _build_buy_order(ticker, settings)
        result = await broker.place_order(order)

        if result.success:
            msg = format_trade_confirmation(
                ticker,
                "BUY",
                result.filled_quantity,
                result.filled_price,
            )
            await message.answer(msg)
        else:
            await message.answer(f"❌ Order failed: {escape_md(result.error_message)}")
    except (ConnectionError, TimeoutError) as e:
        logger.error("Broker connection error placing buy for %s: %s", ticker, e)
        await message.answer(f"❌ Broker error: {escape_md(str(e))}")
    except ValueError as e:
        logger.error("Invalid order for %s: %s", ticker, e)
        await message.answer(f"❌ Order error: {escape_md(str(e))}")


def register_callback_handlers(
    dp: Dispatcher,
    settings: Settings,
    broker: Any = None,
) -> None:
    """Register all callback query handlers on the dispatcher."""
    chat_id = settings.telegram_chat_id

    def _authorised(query: CallbackQuery) -> bool:
        message = query.message
        return message is not None and str(message.chat.id) == chat_id

    @dp.callback_query(lambda c: c.data == "buy")
    async def cb_buy(query: CallbackQuery) -> None:
        if not _authorised(query):
            await query.answer("Unauthorised", show_alert=True)
            return

        if not broker:
            await query.answer("No broker connected", show_alert=True)
            return

        message = _accessible_message(query)
        if message is None:
            await query.answer("This message is no longer available", show_alert=True)
            return

        ticker = _extract_ticker(message.text or "")
        if not ticker:
            await query.answer("Could not parse ticker", show_alert=True)
            return

        await query.answer(f"Placing buy order for {ticker}...")
        await _execute_buy(message, ticker, broker, settings)

    @dp.callback_query(lambda c: c.data == "deny")
    async def cb_deny(query: CallbackQuery) -> None:
        if not _authorised(query):
            return
        await query.answer("Alert dismissed")
        # Edit message to show it was denied
        message = _accessible_message(query)
        if message is None:
            return
        try:
            original = message.text or ""
            await message.edit_text(
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

        message = _accessible_message(query)
        if message is None:
            await query.answer("This message is no longer available", show_alert=True)
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
                    ticker,
                    "SELL",
                    result.filled_quantity,
                    result.filled_price,
                )
                await message.answer(msg)
            else:
                await message.answer(f"❌ Sell failed: {escape_md(result.error_message)}")

        except (ConnectionError, TimeoutError) as e:
            logger.error("Broker error selling %s: %s", ticker, e)
            await message.answer(f"❌ Broker error: {escape_md(str(e))}")
        except ValueError as e:
            logger.error("Invalid sell order for %s: %s", ticker, e)
            await message.answer(f"❌ Order error: {escape_md(str(e))}")

    @dp.callback_query(lambda c: c.data and c.data.startswith("screener_buy:"))
    async def cb_screener_buy(query: CallbackQuery) -> None:
        """Handle BUY button press from a screener alert."""
        if not _authorised(query):
            await query.answer("Unauthorised", show_alert=True)
            return

        if not broker:
            await query.answer("No broker connected", show_alert=True)
            return

        ticker = (query.data or "").split(":", 1)[1] if query.data else ""
        if not ticker:
            await query.answer("Invalid ticker", show_alert=True)
            return

        message = _accessible_message(query)
        if message is None:
            await query.answer("This message is no longer available", show_alert=True)
            return

        await query.answer(f"Placing buy order for {ticker}...")
        await _execute_buy(message, ticker, broker, settings)

    @dp.callback_query(lambda c: c.data == "screener_pass")
    async def cb_screener_pass(query: CallbackQuery) -> None:
        """Handle PASS button press from a screener alert."""
        if not _authorised(query):
            return
        await query.answer("Alert passed")
        message = _accessible_message(query)
        if message is None:
            return
        try:
            original = message.text or ""
            await message.edit_text(
                original + "\n\n_⏭ Passed_",
            )
        except Exception:
            pass


def _extract_ticker(text: str) -> str:
    """Extract ticker symbol from alert message text."""
    match = re.search(r"\$([A-Z]{1,5})\b", text)
    if match:
        return match.group(1)
    return ""
