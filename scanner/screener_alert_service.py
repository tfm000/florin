"""
Background service that periodically runs active saved screeners
and publishes SCREENER_ALERT events for new matches.

Replaces the old MomentumScanner with a more flexible, user-configurable
alert system built on top of the general-purpose screener engine.

Lifecycle:
  1. Loads all SavedScreenerORM records where is_alert_active=True
  2. For each active screener past its run_interval_seconds:
     a. Runs the screen query via the shared screener engine
     b. Compares results against today's already-alerted tickers
     c. For each new match (up to max_alerts_per_day):
        - Publishes SCREENER_ALERT event
        - Logs to screener_alert_log table
        - Increments alerts_sent_today
  3. Resets daily counters at midnight
  4. Sleeps 60s between check cycles
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from core.events import EventBus, EventType
from core.market_hours import is_market_open
from dashboard.services.screener_engine import (
    ScreenerResult,
    apply_momentum_filter,
    parse_filters_to_kwargs,
    run_screen,
)
from db.database import Database
from db.models import SavedScreenerORM, ScreenerAlertLogORM

logger = logging.getLogger(__name__)

# How often the service checks for screeners that need to run (seconds)
_CHECK_INTERVAL = 60


class ScreenerAlertService:
    """Background service that runs active saved screeners and publishes alerts."""

    def __init__(
        self,
        db: Database,
        event_bus: EventBus,
        yfinance_provider: Any = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus
        self._yf = yfinance_provider
        self._last_reset_date: date | None = None

    async def run(self) -> None:
        """
        Main loop — runs continuously, checking active screeners each cycle.

        Only processes screeners during market hours to avoid stale data.
        Resets daily alert counters at midnight UTC.
        """
        logger.info("Screener alert service started")
        while True:
            try:
                await self._maybe_reset_daily_counters()

                if is_market_open():
                    await self._process_active_screeners()

            except asyncio.CancelledError:
                logger.info("Screener alert service stopped")
                return
            except Exception:
                logger.exception("Screener alert service error")

            try:
                await asyncio.sleep(_CHECK_INTERVAL)
            except asyncio.CancelledError:
                logger.info("Screener alert service stopped")
                return

    async def _process_active_screeners(self) -> None:
        """Load and process all active screeners that are due to run."""
        async with self._db.session() as session:
            result = await session.execute(
                select(SavedScreenerORM).where(
                    SavedScreenerORM.is_alert_active.is_(True)
                )
            )
            screeners = result.scalars().all()

        for screener in screeners:
            if self._should_run(screener):
                try:
                    await self._run_screener(screener)
                except Exception:
                    logger.exception(
                        "Failed to run screener '%s' (id=%s)",
                        screener.name, screener.id,
                    )

    def _should_run(self, screener: SavedScreenerORM) -> bool:
        """Check if enough time has passed since the screener's last run."""
        if screener.last_run_at is None:
            return True
        last_run = screener.last_run_at
        # Ensure timezone-aware comparison (DB may store naive datetimes)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - last_run).total_seconds()
        return elapsed >= screener.run_interval_seconds

    async def _run_screener(self, screener: SavedScreenerORM) -> None:
        """
        Run a single screener and publish alerts for new matches.

        Steps:
          1. Parse filters from filters_json
          2. Run screen query via shared engine
          3. Optionally apply momentum filter
          4. Get today's already-alerted tickers
          5. Filter to new matches only
          6. Publish events up to max_alerts_per_day
          7. Update last_run_at
        """
        filters = json.loads(screener.filters_json)
        kwargs = parse_filters_to_kwargs(filters)
        kwargs["sort_by"] = screener.sort_by
        kwargs["sort_asc"] = screener.sort_asc
        kwargs["limit"] = 100

        results = await run_screen(**kwargs)

        # Apply momentum filter if configured
        momentum_period = str(filters.get("momentum_period") or "")
        raw_min = filters.get("momentum_min")
        raw_max = filters.get("momentum_max")
        momentum_min = float(raw_min) if raw_min is not None and raw_min != "" else None
        momentum_max = float(raw_max) if raw_max is not None and raw_max != "" else None
        if momentum_period and (momentum_min is not None or momentum_max is not None) and self._yf:
            results = await apply_momentum_filter(
                results, momentum_min, momentum_max, momentum_period, self._yf,
            )

        if not results:
            await self._update_last_run(screener.id)
            return

        # Get today's already-alerted tickers for this screener
        alerted_today = await self._get_alerted_tickers_today(screener.id)

        # Filter to new matches only
        new_matches = [r for r in results if r.ticker not in alerted_today]
        if not new_matches:
            await self._update_last_run(screener.id)
            return

        # Respect max_alerts_per_day
        remaining = max(0, screener.max_alerts_per_day - screener.alerts_sent_today)
        if remaining == 0:
            await self._update_last_run(screener.id)
            return

        to_alert = new_matches[:remaining]

        # Publish alerts and log them
        for result in to_alert:
            alert_data = {
                "screener_id": screener.id,
                "screener_name": screener.name,
                "ticker": result.ticker,
                "name": result.name,
                "price": result.price,
                "change_pct": result.change_pct,
                "market_cap": result.market_cap,
                "volume": result.volume,
                "sector": result.sector,
                "exchange": result.exchange,
                "include_llm_report": screener.include_llm_report,
                "filters_summary": self._summarize_filters(filters),
            }

            await self._event_bus.publish(
                EventType.SCREENER_ALERT,
                alert_data,
                source="screener_alert_service",
            )

            await self._log_alert(screener.id, result)

        # Update counters and last_run_at in a single DB call
        await self._update_after_alerts(screener.id, len(to_alert))

        logger.info(
            "Screener '%s': %d new alerts from %d matches",
            screener.name, len(to_alert), len(results),
        )

    async def _get_alerted_tickers_today(self, screener_id: str) -> set[str]:
        """Get the set of tickers already alerted today for this screener."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        async with self._db.session() as session:
            result = await session.execute(
                select(ScreenerAlertLogORM.ticker).where(
                    ScreenerAlertLogORM.screener_id == screener_id,
                    ScreenerAlertLogORM.sent_at >= today_start,
                )
            )
            return {row[0] for row in result.all()}

    async def _log_alert(self, screener_id: str, result: ScreenerResult) -> None:
        """Log an alert to the screener_alert_log table."""
        try:
            alert_data = {
                "name": result.name,
                "sector": result.sector,
                "exchange": result.exchange,
                "market_cap": result.market_cap,
                "volume": result.volume,
                "pe_ratio": result.pe_ratio,
                "dividend_yield": result.dividend_yield,
            }

            async with self._db.session() as session:
                session.add(ScreenerAlertLogORM(
                    screener_id=screener_id,
                    ticker=result.ticker,
                    price=result.price,
                    change_pct=result.change_pct,
                    alert_data_json=json.dumps(alert_data),
                    sent_at=datetime.now(UTC),
                ))
                await session.commit()
        except Exception as e:
            logger.error(
                "Failed to log screener alert for %s: %s", result.ticker, e,
            )

    async def _update_last_run(self, screener_id: str) -> None:
        """Update the last_run_at timestamp for a screener."""
        async with self._db.session() as session:
            result = await session.execute(
                select(SavedScreenerORM).where(SavedScreenerORM.id == screener_id)
            )
            orm = result.scalar()
            if orm:
                orm.last_run_at = datetime.now(UTC)
                await session.commit()

    async def _update_after_alerts(self, screener_id: str, count: int) -> None:
        """Update last_run_at and increment alerts_sent_today in a single transaction."""
        async with self._db.session() as session:
            result = await session.execute(
                select(SavedScreenerORM).where(SavedScreenerORM.id == screener_id)
            )
            orm = result.scalar()
            if orm:
                orm.last_run_at = datetime.now(UTC)
                orm.alerts_sent_today += count
                await session.commit()

    async def _maybe_reset_daily_counters(self) -> None:
        """Reset alerts_sent_today to 0 for all screeners at midnight UTC."""
        today = datetime.now(UTC).date()
        if self._last_reset_date == today:
            return

        self._last_reset_date = today
        async with self._db.session() as session:
            result = await session.execute(
                select(SavedScreenerORM).where(
                    SavedScreenerORM.alerts_sent_today > 0
                )
            )
            for orm in result.scalars().all():
                orm.alerts_sent_today = 0
            await session.commit()

        logger.info("Daily screener alert counters reset")

    _ASSET_TYPE_LABELS = {
        "EQUITY": "Stocks", "ETF": "ETFs", "MUTUALFUND": "Mutual Funds",
        "INDEX": "Indices", "CRYPTOCURRENCY": "Crypto",
    }
    _EXCHANGE_LABELS = {
        "NMS,NGM,NCM": "NASDAQ", "NYQ": "NYSE", "PCX": "NYSE Arca",
        "ASE": "NYSE American", "BTS": "BATS", "PNK,OQB,OQX": "OTC",
        "PAR": "Euronext Paris", "AMS": "Euronext Amsterdam",
        "BRU": "Euronext Brussels", "LIS": "Euronext Lisbon",
        "MIL": "Borsa Italiana", "MAD": "BME Madrid",
        "STO": "Nasdaq Stockholm", "EBS": "SIX Swiss", "SES": "SGX",
        "KSC": "KOSPI", "KOE": "KOSDAQ", "SAO": "B3", "MEX": "BMV",
        "TAI": "TWSE", "TWO": "TPEx", "NZE": "NZX",
        "LSE": "London", "IOB": "IOB", "TOR": "TSX", "VAN": "TSX-V",
        "CNQ": "CSE", "GER": "XETRA", "FRA": "Frankfurt",
        "JPX": "Tokyo", "HKG": "HKEX", "ASX": "ASX",
        "NSI": "NSE", "BSE": "BSE",
    }

    @staticmethod
    def _summarize_filters(filters: dict) -> str:
        """Create a human-readable summary of filter settings."""
        parts = []
        if filters.get("price_min") or filters.get("price_max"):
            pmin = filters.get("price_min", "0")
            pmax = filters.get("price_max", "\u221E")
            parts.append(f"Price: ${pmin}-${pmax}")
        if filters.get("sector"):
            parts.append(filters["sector"])
        if filters.get("asset_type"):
            label = ScreenerAlertService._ASSET_TYPE_LABELS.get(
                filters["asset_type"], filters["asset_type"],
            )
            parts.append(label)
        if filters.get("momentum_period"):
            parts.append(f"Momentum: {filters['momentum_period']}")
        if filters.get("exchange"):
            label = ScreenerAlertService._EXCHANGE_LABELS.get(
                filters["exchange"], filters["exchange"],
            )
            parts.append(label)
        return " | ".join(parts) if parts else "All US assets"
