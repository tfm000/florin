"""
Penny Stock Sentinel — Main Entry Point

Starts all services:
  1. Database initialisation
  2. Market data connection
  3. Penny stock scanner
  4. Alert processing pipeline
  5. Position monitoring
  6. Telegram bot
  7. Web dashboard

All services run concurrently via asyncio.gather().
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import NoReturn

from config.settings import get_settings
from core.events import EventBus, EventType
from core.logging import get_logger, setup_logging
from db.database import Database

logger = get_logger(__name__)


class Sentinel:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.event_bus = EventBus()
        self.db: Database | None = None
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Initialise and start all services."""
        setup_logging(self.settings.log_level, self.settings.app_env)
        logger.info(
            "Starting Penny Stock Sentinel",
            env=self.settings.app_env.value,
            llm_mode=self.settings.llm_mode.value,
            price_threshold=self.settings.scan_price_threshold,
            momentum_threshold=self.settings.scan_momentum_threshold,
        )

        # --- Database ---
        self.db = Database(self.settings.database_url)
        await self.db.init()
        logger.info("Database ready")

        # --- Validate required config ---
        warnings = []
        if not self.settings.alpaca_configured:
            warnings.append("Alpaca API not configured — market data unavailable")
        if not self.settings.t212_configured:
            warnings.append("Trading 212 API not configured — trading disabled")
        if not self.settings.telegram_configured:
            warnings.append("Telegram not configured — mobile alerts disabled")

        for w in warnings:
            logger.warning(w)

        # --- Log enabled LLM providers ---
        providers = self.settings.get_enabled_llm_providers()
        logger.info("Enabled LLM providers", providers=[p.value for p in providers])

        # --- Start services ---
        # Each service is a long-running coroutine. They're started as tasks
        # and run concurrently. When shutdown is triggered, all are cancelled.

        services = []

        # Placeholder coroutines — replaced by real implementations in later phases
        services.append(self._heartbeat())

        logger.info(
            "Sentinel started — %d service(s) running",
            len(services),
        )

        # Run all services
        self._tasks = [asyncio.create_task(s, name=f"service-{i}") for i, s in enumerate(services)]

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        # Clean up
        if self.db:
            await self.db.close()

        logger.info("Sentinel shut down cleanly")

    async def _heartbeat(self) -> None:
        """Periodic health check log — proves the event loop is alive."""
        while not self._shutdown_event.is_set():
            logger.debug(
                "Heartbeat",
                events_published=self.event_bus.event_count,
                subscribers=self.event_bus.subscriber_counts,
            )
            await asyncio.sleep(60)

    def shutdown(self) -> None:
        """Trigger graceful shutdown."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()


def cli_entry() -> None:
    """CLI entry point (called by `sentinel` command)."""
    app = Sentinel()

    # Handle Ctrl+C and SIGTERM gracefully
    loop = asyncio.new_event_loop()

    def _signal_handler() -> None:
        app.shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        app.shutdown()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()


if __name__ == "__main__":
    cli_entry()
