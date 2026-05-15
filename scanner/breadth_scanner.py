"""
Market breadth scanner — tracks advance/decline across configurable exchanges.

Runs hourly during market hours:
1. Computes advance/decline via screener engine (paginated, all matching stocks)
2. Optionally uses Alpaca snapshots for faster computation when available
3. Stores results in DB

Uses the shared screener engine for query execution — no duplicate query building.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from db.models import BreadthSnapshotORM

if TYPE_CHECKING:
    from data.alpaca_provider import AlpacaProvider
    from db.database import Database

logger = logging.getLogger(__name__)

# Default US exchange codes used by the background scanner
DEFAULT_EXCHANGES = "NMS,NGM,NCM,NYQ,ASE"


async def compute_breadth(
    exchange: str = DEFAULT_EXCHANGES,
    alpaca: AlpacaProvider | None = None,
    tickers: list[str] | None = None,
) -> dict:
    """Compute advance/decline from live price data.

    Uses Alpaca snapshots if a provider and ticker list are given (fast, batched).
    Otherwise paginates through the screener engine for all matching stocks.

    Args:
        exchange: Comma-separated exchange codes for the screener fallback.
        alpaca: Optional Alpaca provider for snapshot-based computation.
        tickers: Pre-discovered ticker list for Alpaca path. Ignored if alpaca is None.
    """
    from dashboard.services.screener_engine import run_screen

    advancing = 0
    declining = 0
    unchanged = 0

    if alpaca and tickers:
        try:
            snapshots = await alpaca.get_snapshot(tickers)
            for _ticker, quote in snapshots.items():
                change = getattr(quote, "change_pct", 0) or 0
                if change > 0.01:
                    advancing += 1
                elif change < -0.01:
                    declining += 1
                else:
                    unchanged += 1
        except Exception:
            logger.exception("Alpaca breadth snapshot failed")

    # Fallback: paginate through yfinance screener for all matching stocks
    if advancing + declining + unchanged == 0:
        offset = 0
        page_size = 250
        while True:
            results, total = await run_screen(
                exchange=exchange,
                market_cap_min=300_000_000,
                limit=page_size,
                offset=offset,
            )
            for r in results:
                change = r.change_pct or 0
                if change > 0.01:
                    advancing += 1
                elif change < -0.01:
                    declining += 1
                else:
                    unchanged += 1
            offset += page_size
            if not results or offset >= total:
                break

    total = advancing + declining + unchanged
    ad_ratio = advancing / declining if declining > 0 else float(advancing) if advancing > 0 else 0

    return {
        "advancing": advancing,
        "declining": declining,
        "unchanged": unchanged,
        "total": total,
        "ad_ratio": round(ad_ratio, 2),
    }


async def discover_tickers(exchange: str = DEFAULT_EXCHANGES) -> list[str]:
    """Discover ticker symbols via the screener engine.

    Used by the Alpaca path to build a ticker list for snapshot requests.
    Reuses run_screen() to avoid duplicating query-building logic.
    """
    from dashboard.services.screener_engine import run_screen

    all_tickers: list[str] = []
    offset = 0
    page_size = 250
    while True:
        results, total = await run_screen(
            exchange=exchange,
            market_cap_min=300_000_000,
            limit=page_size,
            offset=offset,
        )
        all_tickers.extend(r.ticker for r in results)
        offset += page_size
        if not results or offset >= total:
            break

    logger.info(
        "Breadth scanner: discovered %d equities for exchanges %s", len(all_tickers), exchange
    )
    return all_tickers


async def save_breadth_snapshot(db: Database, data: dict) -> None:
    """Persist a breadth snapshot to the database, skipping if one already exists for this hour."""
    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")
    hour = now.hour

    async with db.session() as session:
        existing = await session.execute(
            select(BreadthSnapshotORM.id).where(
                BreadthSnapshotORM.date == date_str,
                BreadthSnapshotORM.hour == hour,
            )
        )
        if existing.first():
            logger.debug("Breadth snapshot already exists for %s hour %d, skipping", date_str, hour)
            return

        session.add(
            BreadthSnapshotORM(
                date=date_str,
                hour=hour,
                advancing=data["advancing"],
                declining=data["declining"],
                unchanged=data["unchanged"],
                total=data["total"],
                ad_ratio=data["ad_ratio"],
            )
        )
        await session.commit()

    logger.info(
        "Breadth snapshot saved: %d adv / %d dec / %d unch (ratio %.2f)",
        data["advancing"],
        data["declining"],
        data["unchanged"],
        data["ad_ratio"],
    )


async def breadth_scan_loop(
    db: Database,
    alpaca: AlpacaProvider | None = None,
) -> None:
    """Background task: compute and store breadth every hour during market hours."""
    from core.market_hours import is_market_open

    while True:
        try:
            if is_market_open():
                # Only discover tickers if Alpaca is available (screener fallback doesn't need them)
                tickers = await discover_tickers() if alpaca else None
                data = await compute_breadth(alpaca=alpaca, tickers=tickers)
                if data["total"] > 0:
                    await save_breadth_snapshot(db, data)
        except Exception:
            logger.exception("Breadth scan loop error")

        await asyncio.sleep(3600)  # 1 hour
