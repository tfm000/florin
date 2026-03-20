"""
Telegram command handlers.

Commands: /start, /status, /balance, /positions, /settings, /mode, /kill
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from config.settings import Settings
from telegram_bot.formatters import (
    escape_md,
    format_account_summary,
    format_positions_list,
)

logger = logging.getLogger(__name__)


def register_command_handlers(
    dp: Dispatcher,
    settings: Settings,
    broker: Any = None,
) -> None:
    """Register all command handlers on the dispatcher."""
    chat_id = settings.telegram_chat_id

    def _authorised(message: Message) -> bool:
        return str(message.chat.id) == chat_id

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not _authorised(message):
            return
        await message.answer(
            "🤖 *Penny Stock Sentinel*\n\n"
            "Commands:\n"
            "/status \\- System health\n"
            "/balance \\- Account summary\n"
            "/positions \\- Open positions\n"
            "/settings \\- View config\n"
            "/mode \\- Switch LLM mode\n"
            "/kill \\- Emergency stop"
        )

    @dp.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not _authorised(message):
            return

        lines = [
            "📡 *System Status*",
            escape_md("━" * 25),
            f"🔧 Mode: {escape_md(settings.llm_mode.value)}",
            f"💹 Price threshold: {escape_md(f'${settings.scan_price_threshold:.2f}')}",
            f"📊 Momentum threshold: {escape_md(f'{settings.scan_momentum_threshold:.1f}%')}",
            f"⏱ Scan interval: {escape_md(f'{settings.scan_interval_seconds}s')}",
            f"🤖 Default LLM: {escape_md(settings.llm_default_provider.value)}",
        ]

        if broker:
            try:
                health = await broker.health_check()
                status = "✅ Connected" if health else "❌ Disconnected"
            except Exception:
                status = "❌ Error"
            lines.append(f"🏦 Broker: {escape_md(status)}")

        await message.answer("\n".join(lines))

    @dp.message(Command("balance"))
    async def cmd_balance(message: Message) -> None:
        if not _authorised(message):
            return

        if not broker:
            await message.answer("🏦 No broker connected")
            return

        try:
            summary = await broker.get_account_summary()
            await message.answer(format_account_summary(summary))
        except Exception as e:
            await message.answer(f"❌ Error: {escape_md(str(e))}")

    @dp.message(Command("positions"))
    async def cmd_positions(message: Message) -> None:
        if not _authorised(message):
            return

        if not broker:
            await message.answer("🏦 No broker connected")
            return

        try:
            positions = await broker.get_positions()
            await message.answer(format_positions_list(positions))
        except Exception as e:
            await message.answer(f"❌ Error: {escape_md(str(e))}")

    @dp.message(Command("settings"))
    async def cmd_settings(message: Message) -> None:
        if not _authorised(message):
            return

        providers = settings.get_enabled_llm_providers()
        provider_str = escape_md(", ".join(p.value for p in providers))

        lines = [
            "⚙️ *Settings*",
            escape_md("━" * 25),
            f"Price threshold: {escape_md(f'${settings.scan_price_threshold:.2f}')}",
            f"Momentum threshold: {escape_md(f'{settings.scan_momentum_threshold:.1f}%')}",
            f"Min volume: {escape_md(f'{settings.scan_min_volume:,}')}",
            f"Scan interval: {escape_md(f'{settings.scan_interval_seconds}s')}",
            f"Cooldown: {escape_md(f'{settings.scan_cooldown_minutes} min')}",
            f"LLM mode: {escape_md(settings.llm_mode.value)}",
            f"Default LLM: {escape_md(settings.llm_default_provider.value)}",
            f"Enabled LLMs: {provider_str}",
            f"Position size: {escape_md(f'${settings.default_position_size:.2f}')}",
            f"Stop loss: {escape_md(f'{settings.default_stop_loss_pct:.1f}%')}",
            f"Max positions: {escape_md(str(settings.max_open_positions))}",
        ]

        await message.answer("\n".join(lines))

    @dp.message(Command("mode"))
    async def cmd_mode(message: Message) -> None:
        if not _authorised(message):
            return

        current = settings.llm_mode.value
        await message.answer(
            f"Current mode: *{escape_md(current)}*\n\n"
            f"_Single mode uses one LLM\\. "
            f"Consensus mode uses all enabled LLMs and synthesises\\._"
        )

    @dp.message(Command("kill"))
    async def cmd_kill(message: Message) -> None:
        if not _authorised(message):
            return

        lines = ["🛑 *Emergency Stop*"]

        if broker:
            try:
                pending = await broker.get_pending_orders()
                cancelled = 0
                for order in pending:
                    order_id = order.get("id", "")
                    if order_id and await broker.cancel_order(order_id):
                        cancelled += 1
                lines.append(
                    f"Cancelled {escape_md(str(cancelled))} pending orders"
                )
            except Exception as e:
                lines.append(f"Error cancelling orders: {escape_md(str(e))}")

        lines.append("Scanner paused \\(restart to resume\\)")
        await message.answer("\n".join(lines))
