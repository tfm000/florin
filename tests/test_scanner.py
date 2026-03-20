"""Tests for Phase 2: Scanner and market data modules."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Settings
from core.events import EventBus, EventType
from core.models import AlertSignal, StockInfo, StockQuote
from data.alpaca_provider import AlpacaProvider
from scanner.momentum_scanner import MomentumScanner
from scanner.universe import UniverseManager


# =============================================================================
# Universe Manager tests
# =============================================================================


class TestUniverseManager:
    def _make_universe(self) -> UniverseManager:
        settings = Settings(
            fmp_api_key="test",
            scan_price_threshold=5.0,
        )
        db = MagicMock()
        return UniverseManager(settings, db)

    def test_empty_universe(self) -> None:
        um = self._make_universe()
        assert um.size == 0
        assert um.tickers == []
        assert um.get("AAPL") is None

    def test_get_t212_ticker(self) -> None:
        um = self._make_universe()
        # No stock in universe — falls back to default format
        assert um.get_t212_ticker("AAPL") == "AAPL_US_EQ"

    def test_get_t212_ticker_with_mapping(self) -> None:
        um = self._make_universe()
        um._stocks["AAPL"] = StockInfo(
            ticker="AAPL", t212_ticker="AAPL_US_EQ"
        )
        assert um.get_t212_ticker("AAPL") == "AAPL_US_EQ"

    @pytest.mark.asyncio
    async def test_update_prices_removes_above_threshold(self) -> None:
        um = self._make_universe()
        um._stocks["CHEAP"] = StockInfo(ticker="CHEAP", last_price=1.0)
        um._stocks["EXPENSIVE"] = StockInfo(ticker="EXPENSIVE", last_price=4.0)

        # Price threshold is $5, removal at 1.5x = $7.50
        await um.update_prices({"CHEAP": 2.0, "EXPENSIVE": 8.0})

        # CHEAP should remain, EXPENSIVE should be removed
        assert "CHEAP" in um._stocks
        assert "EXPENSIVE" not in um._stocks
        assert um._stocks["CHEAP"].last_price == 2.0


# =============================================================================
# Momentum Scanner tests
# =============================================================================


class TestMomentumScanner:
    def _make_scanner(
        self,
        threshold: float = 5.0,
        min_volume: int = 10_000,
    ) -> tuple[MomentumScanner, AlpacaProvider, UniverseManager]:
        settings = Settings(
            scan_momentum_threshold=threshold,
            scan_min_volume=min_volume,
            scan_cooldown_minutes=30,
            scan_interval_seconds=10,
        )
        data = MagicMock(spec=AlpacaProvider)
        data.cache = {}

        universe = MagicMock(spec=UniverseManager)
        universe.tickers = []
        universe.size = 0

        scanner = MomentumScanner(settings, data, universe)
        return scanner, data, universe

    @pytest.mark.asyncio
    async def test_scan_empty_universe(self) -> None:
        scanner, data, universe = self._make_scanner()
        alerts = await scanner.scan_once()
        assert alerts == []

    @pytest.mark.asyncio
    async def test_scan_detects_momentum(self) -> None:
        scanner, data, universe = self._make_scanner(threshold=5.0, min_volume=100)

        # Set up universe with one stock
        universe.tickers = ["TEST"]
        universe.size = 1
        universe.get.return_value = StockInfo(ticker="TEST", avg_volume=50000)

        # Set up price cache with a 10% move
        data.cache = {
            "TEST": StockQuote(
                ticker="TEST",
                price=2.20,
                open_price=2.00,
                prev_close=2.00,
                volume=100_000,
            )
        }

        alerts = await scanner.scan_once()
        assert len(alerts) == 1
        assert alerts[0].ticker == "TEST"
        assert alerts[0].change_pct == pytest.approx(10.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_scan_respects_volume_filter(self) -> None:
        scanner, data, universe = self._make_scanner(
            threshold=5.0, min_volume=50_000
        )

        universe.tickers = ["LOW_VOL"]
        universe.size = 1
        universe.get.return_value = StockInfo(ticker="LOW_VOL")

        # Big move but low volume
        data.cache = {
            "LOW_VOL": StockQuote(
                ticker="LOW_VOL",
                price=3.00,
                open_price=2.00,
                volume=1_000,  # Below min_volume
            )
        }

        alerts = await scanner.scan_once()
        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_scan_respects_cooldown(self) -> None:
        scanner, data, universe = self._make_scanner(threshold=5.0, min_volume=100)

        universe.tickers = ["COOL"]
        universe.size = 1
        universe.get.return_value = StockInfo(ticker="COOL", avg_volume=50000)

        data.cache = {
            "COOL": StockQuote(
                ticker="COOL",
                price=2.20,
                open_price=2.00,
                volume=100_000,
            )
        }

        # First scan should trigger
        alerts1 = await scanner.scan_once()
        assert len(alerts1) == 1

        # Second scan should be on cooldown
        alerts2 = await scanner.scan_once()
        assert len(alerts2) == 0

    @pytest.mark.asyncio
    async def test_scan_no_alert_below_threshold(self) -> None:
        scanner, data, universe = self._make_scanner(threshold=5.0, min_volume=100)

        universe.tickers = ["FLAT"]
        universe.size = 1

        # Only 2% move — below 5% threshold
        data.cache = {
            "FLAT": StockQuote(
                ticker="FLAT",
                price=2.04,
                open_price=2.00,
                volume=100_000,
            )
        }

        alerts = await scanner.scan_once()
        assert len(alerts) == 0

    def test_best_change_pct_uses_largest(self) -> None:
        scanner, _, _ = self._make_scanner()

        quote = StockQuote(
            ticker="TEST",
            price=2.50,
            open_price=2.00,   # +25% from open
            prev_close=2.30,   # +8.7% from prev close
            volume=100_000,
        )

        result = scanner._best_change_pct(quote)
        # Should pick +25% from open as it's larger
        assert result == pytest.approx(25.0, abs=0.1)

    def test_scanner_not_running_initially(self) -> None:
        scanner, _, _ = self._make_scanner()
        assert scanner.is_running is False
        assert scanner.scan_count == 0
        assert scanner.total_alerts == 0
