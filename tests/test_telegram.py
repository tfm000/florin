"""Tests for Telegram formatters."""

from datetime import UTC, datetime

from core.models import AccountSummary, Position
from telegram_bot.formatters import (
    escape_md,
    format_account_summary,
    format_position_message,
    format_positions_list,
    format_trade_confirmation,
)


class TestEscapeMd:
    def test_escapes_special_chars(self):
        assert escape_md("hello_world") == "hello\\_world"
        assert escape_md("price: 5.00") == "price: 5\\.00"

    def test_no_special_chars(self):
        assert escape_md("hello") == "hello"

    def test_all_special_chars(self):
        for ch in r"_*[]()~`>#+-=|{}.!":
            assert escape_md(ch) == f"\\{ch}"

    def test_numbers_unchanged(self):
        assert escape_md("12345") == "12345"


class TestFormatPositionMessage:
    def test_positive_pnl(self):
        pos = Position(
            ticker="AAPL",
            quantity=10.0,
            avg_price=1.50,
            current_price=2.00,
            opened_at=datetime.now(UTC),
        )
        msg = format_position_message(pos)
        assert "AAPL" in msg
        assert "🟢" in msg

    def test_negative_pnl(self):
        pos = Position(
            ticker="SCAM",
            quantity=10.0,
            avg_price=2.00,
            current_price=1.00,
            opened_at=datetime.now(UTC),
        )
        pos.update_pnl(1.00)
        msg = format_position_message(pos)
        assert "🔴" in msg


class TestFormatPositionsList:
    def test_empty_positions(self):
        msg = format_positions_list([])
        assert "No open positions" in msg

    def test_with_positions(self):
        positions = [
            Position(
                ticker="TICK",
                quantity=5.0,
                avg_price=1.00,
                current_price=1.50,
                opened_at=datetime.now(UTC),
            ),
        ]
        msg = format_positions_list(positions)
        assert "TICK" in msg
        assert "Open Positions" in msg
        assert "Total P&L" in msg


class TestFormatAccountSummary:
    def test_account_summary(self):
        acc = AccountSummary(
            currency="GBP",
            cash_available=5000.0,
            invested_value=3000.0,
            total_value=8000.0,
            unrealised_pnl=200.0,
            realised_pnl=100.0,
            updated_at=datetime.now(UTC),
        )
        msg = format_account_summary(acc)
        assert "Account Summary" in msg
        assert "GBP" in msg
        assert "5000" in msg


class TestFormatTradeConfirmation:
    def test_buy_trade(self):
        msg = format_trade_confirmation("AAPL", "BUY", 10.0, 1.50)
        assert "🟢" in msg
        assert "BUY" in msg
        assert "AAPL" in msg

    def test_sell_trade(self):
        msg = format_trade_confirmation("AAPL", "SELL", 10.0, 2.00)
        assert "🔴" in msg
        assert "SELL" in msg
