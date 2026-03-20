"""
Momentum scanner — detects significant price moves in penny stocks.

Triggers alerts when a stock moves more than the configured threshold
(default 5%) from:
  - Today's open price
  - Previous close
  - Rolling N-minute low (intraday reversal detection)

Features:
  - Configurable thresholds (price change %, minimum volume)
  - Per-ticker cooldown to avoid alert spam
  - Runs as a continuous async loop, polling the data provider's cache
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from config.settings import Settings
from core.events import EventBus, EventType
from core.market_hours import is_market_open
from core.models import AlertSignal, AlertSource, StockQuote
from data.alpaca_provider import AlpacaProvider
from scanner.base import Scanner
from scanner.universe import UniverseManager

logger = logging.getLogger(__name__)


class MomentumScanner(Scanner):
    """
    Scans the Alpaca price cache for penny stocks showing momentum.

    Runs on a configurable interval (default 120s), checking every stock
    in the universe for % moves exceeding the threshold.
    """

    def __init__(
        self,
        settings: Settings,
        data_provider: AlpacaProvider,
        universe: UniverseManager,
    ) -> None:
        self._settings = settings
        self._data = data_provider
        self._universe = universe

        # Thresholds from settings
        self._momentum_threshold = settings.scan_momentum_threshold
        self._min_volume = settings.scan_min_volume
        self._interval = settings.scan_interval_seconds
        self._cooldown_minutes = settings.scan_cooldown_minutes

        # Per-ticker cooldown tracking: ticker -> last alert time
        self._cooldowns: dict[str, datetime] = {}

        # State
        self._running = False
        self._scan_count = 0
        self._total_alerts = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def scan_count(self) -> int:
        return self._scan_count

    @property
    def total_alerts(self) -> int:
        return self._total_alerts

    async def run(self, event_bus: EventBus) -> None:
        """
        Main scanner loop. Runs indefinitely until stop() is called.

        Each iteration:
        1. Read prices from the data provider's cache
        2. Check each penny stock for momentum signals
        3. Apply cooldowns and filters
        4. Publish alerts to the event bus
        """
        self._running = True
        logger.info(
            "Momentum scanner started: threshold=%.1f%%, interval=%ds, "
            "min_volume=%d, cooldown=%dm",
            self._momentum_threshold,
            self._interval,
            self._min_volume,
            self._cooldown_minutes,
        )

        # Notify system
        await event_bus.publish(
            EventType.SCANNER_STATUS,
            {"status": "running", "universe_size": self._universe.size},
            source="momentum_scanner",
        )

        while self._running:
            if not is_market_open():
                await asyncio.sleep(60)
                continue

            try:
                alerts = await self.scan_once()

                for alert in alerts:
                    await event_bus.publish(
                        EventType.MOMENTUM_ALERT,
                        alert,
                        source="momentum_scanner",
                    )
                    self._total_alerts += 1

                if alerts:
                    logger.info(
                        "Scan #%d: %d alerts from %d universe stocks",
                        self._scan_count, len(alerts), self._universe.size,
                    )

            except Exception:
                logger.exception("Error during scan #%d", self._scan_count)

            # Wait for next interval
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

        self._running = False
        logger.info("Momentum scanner stopped after %d scans", self._scan_count)

    async def scan_once(self) -> list[AlertSignal]:
        """
        Perform a single scan pass across all universe stocks.

        Returns list of triggered alerts (may be empty).
        """
        self._scan_count += 1
        alerts: list[AlertSignal] = []
        cache = self._data.cache
        now = datetime.now(UTC)

        # Clean expired cooldowns
        self._clean_cooldowns(now)

        for ticker in self._universe.tickers:
            quote = cache.get(ticker)
            if not quote:
                continue  # No price data yet

            alert = self._check_momentum(ticker, quote, now)
            if alert:
                alerts.append(alert)

        return alerts

    async def stop(self) -> None:
        """Signal the scanner to stop."""
        self._running = False
        logger.info("Momentum scanner stop requested")

    def _check_momentum(
        self,
        ticker: str,
        quote: StockQuote,
        now: datetime,
    ) -> AlertSignal | None:
        """
        Check if a single stock qualifies for a momentum alert.

        Returns AlertSignal if triggered, None otherwise.
        """
        # Skip if on cooldown
        if ticker in self._cooldowns:
            return None

        # Volume filter
        if quote.volume < self._min_volume:
            return None

        # Price sanity check
        if quote.price <= 0:
            return None

        # Check % change from various baselines
        change_pct = self._best_change_pct(quote)

        if abs(change_pct) < self._momentum_threshold:
            return None

        # Passed all filters — create alert
        stock_info = self._universe.get(ticker)
        avg_volume = stock_info.avg_volume if stock_info else 0

        alert = AlertSignal(
            id=uuid4().hex[:12],
            ticker=ticker,
            price=quote.price,
            change_pct=change_pct,
            volume=quote.volume,
            avg_volume=avg_volume,
            source=AlertSource.MOMENTUM,
            triggered_at=now,
            metadata={
                "open_price": quote.open_price,
                "prev_close": quote.prev_close,
                "high": quote.high,
                "low": quote.low,
                "change_from_open": quote.change_from_open,
                "change_from_prev_close": quote.change_from_prev_close,
            },
        )

        # Set cooldown
        self._cooldowns[ticker] = now

        logger.info(
            "ALERT: %s %+.2f%% @ $%.4f (vol: %s)",
            ticker, change_pct, quote.price, f"{quote.volume:,}",
        )

        return alert

    def _best_change_pct(self, quote: StockQuote) -> float:
        """
        Return the most significant % change for this quote.

        Checks change from open and from previous close,
        returns whichever has the larger absolute value.
        """
        candidates = []

        if quote.open_price > 0:
            candidates.append(quote.change_from_open)

        if quote.prev_close > 0:
            candidates.append(quote.change_from_prev_close)

        # Also check the explicit change_pct if set by the data provider
        if quote.change_pct != 0:
            candidates.append(quote.change_pct)

        if not candidates:
            return 0.0

        # Return the one with the largest absolute value
        return max(candidates, key=abs)

    def _clean_cooldowns(self, now: datetime) -> None:
        """Remove expired cooldowns."""
        cutoff = now - timedelta(minutes=self._cooldown_minutes)
        expired = [t for t, ts in self._cooldowns.items() if ts < cutoff]
        for ticker in expired:
            del self._cooldowns[ticker]
