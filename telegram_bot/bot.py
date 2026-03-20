"""
Main Telegram bot setup using aiogram 3.x.

Handles bot initialisation, dispatcher setup, and polling lifecycle.
Restricted to configured chat ID for security.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import Settings
from core.events import EventBus

logger = logging.getLogger(__name__)


class SentinelBot:
    """
    Telegram bot for Penny Stock Sentinel.

    Provides:
    - Alert notifications with BUY/DENY buttons
    - Position monitoring with SELL/STOP-LOSS buttons
    - Commands: /start, /status, /balance, /positions, /settings, /mode, /kill
    """

    def __init__(
        self,
        settings: Settings,
        event_bus: EventBus,
        broker: Any = None,
    ) -> None:
        self._settings = settings
        self._event_bus = event_bus
        self._broker = broker

        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None
        self._chat_id = settings.telegram_chat_id

    @property
    def bot(self) -> Bot:
        if self._bot is None:
            raise RuntimeError("Bot not initialised — call setup() first")
        return self._bot

    async def setup(self) -> None:
        """Initialise bot and register handlers."""
        if not self._settings.telegram_configured:
            logger.warning("Telegram bot not configured — skipping setup")
            return

        self._bot = Bot(
            token=self._settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
        )
        self._dp = Dispatcher()

        # Register handlers
        from telegram_bot.handlers.commands import register_command_handlers
        from telegram_bot.handlers.callbacks import register_callback_handlers

        register_command_handlers(self._dp, self._settings, self._broker)
        register_callback_handlers(self._dp, self._settings, self._broker)

        logger.info("Telegram bot setup complete")

    async def start_polling(self) -> None:
        """Start the bot polling loop."""
        if not self._dp or not self._bot:
            logger.warning("Bot not set up — cannot start polling")
            return

        logger.info("Starting Telegram bot polling...")
        try:
            await self._dp.start_polling(self._bot)
        except Exception:
            logger.exception("Telegram polling error")

    async def stop(self) -> None:
        """Stop the bot."""
        if self._dp:
            await self._dp.stop_polling()
        if self._bot:
            await self._bot.session.close()
        logger.info("Telegram bot stopped")

    async def send_alert(self, message: str) -> int | None:
        """
        Send an alert message to the configured chat.

        Returns the message ID for later editing, or None on failure.
        """
        if not self._bot or not self._chat_id:
            return None

        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="📈 BUY", callback_data="buy"),
                    InlineKeyboardButton(text="❌ DENY", callback_data="deny"),
                ],
                [
                    InlineKeyboardButton(text="📋 Full Report", callback_data="report"),
                ],
            ])

            result = await self._bot.send_message(
                chat_id=self._chat_id,
                text=message,
                reply_markup=keyboard,
            )
            return result.message_id

        except Exception:
            logger.exception("Failed to send Telegram alert")
            return None

    async def send_message(self, text: str) -> int | None:
        """Send a plain message without buttons."""
        if not self._bot or not self._chat_id:
            return None

        try:
            result = await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
            )
            return result.message_id
        except Exception:
            logger.exception("Failed to send Telegram message")
            return None

    async def edit_message(self, message_id: int, text: str) -> bool:
        """Edit an existing message."""
        if not self._bot or not self._chat_id:
            return False

        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=text,
            )
            return True
        except Exception:
            logger.exception("Failed to edit Telegram message %d", message_id)
            return False
