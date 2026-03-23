"""
Market breadth scanner — tracks advance/decline across configurable exchanges.

Runs hourly during market hours:
1. Discovers tickers via yfinance screener (configurable exchanges)
2. Fetches live prices via Alpaca snapshots (batched) when available
3. Computes advance/decline and stores in DB
4. Falls back to paginated yfinance screener if Alpaca not available

The ticker list is cached for 24 hours (constituents don't change intraday).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from db.models import BreadthSnapshotORM

if TYPE_CHECKING:
    from data.alpaca_provider import AlpacaProvider
    from data.yfinance_provider import YFinanceProvider
    from db.database import Database

logger = logging.getLogger(__name__)

# Default US exchange codes used by the background scanner
DEFAULT_EXCHANGES = "NMS,NGM,NCM,NYQ,ASE"

# Cache: (timestamp, exchange_key, ticker_list)
_ticker_cache: tuple[float, str, list[str]] = (0.0, "", [])
_TICKER_CACHE_TTL = 86400  # 24 hours


async def discover_tickers(
    yf: YFinanceProvider,
    exchange: str = DEFAULT_EXCHANGES,
) -> list[str]:
    """Discover large/mid-cap equities via yfinance screener.

    Args:
        yf: YFinance provider (unused directly; screener runs via yfinance).
        exchange: Comma-separated exchange codes (e.g. "NMS,NGM,NCM,NYQ").
    """
    global _ticker_cache
    now = time.time()
    cache_key = exchange
    if (
        now - _ticker_cache[0] < _TICKER_CACHE_TTL
        and _ticker_cache[1] == cache_key
        and _ticker_cache[2]
    ):
        return _ticker_cache[2]

    exchange_codes = [e.strip() for e in exchange.split(",") if e.strip()]

    def _screen():
        try:
            from yfinance import EquityQuery, screen

            operands = [
                EquityQuery("gt", ["intradaymarketcap", 300_000_000]),
            ]

            if exchange_codes:
                if len(exchange_codes) == 1:
                    operands.append(EquityQuery("eq", ["exchange", exchange_codes[0]]))
                else:
                    operands.append(EquityQuery("or", [
                        EquityQuery("eq", ["exchange", e]) for e in exchange_codes
                    ]))
            else:
                operands.append(EquityQuery("eq", ["region", "us"]))

            # EquityQuery AND requires at least 2 operands
            if len(operands) < 2:
                operands.append(EquityQuery("gt", ["intradayprice", 0]))

            query = EquityQuery("and", operands)

            all_tickers = []
            offset = 0
            page_size = 250

            while offset < 10000:  # Safety cap
                resp = screen(query, size=page_size, offset=offset,
                              sortField="intradaymarketcap", sortAsc=False)
                quotes = resp.get("quotes", []) if resp else []
                if not quotes:
                    break
                for q in quotes:
                    sym = q.get("symbol", "")
                    if sym:
                        all_tickers.append(sym)
                offset += page_size
                if len(quotes) < page_size:
                    break

            # Deduplicate
            seen = set()
            unique = []
            for t in all_tickers:
                if t not in seen:
                    seen.add(t)
                    unique.append(t)

            logger.info("Breadth scanner: discovered %d equities for exchanges %s", len(unique), exchange)
            return unique

        except Exception:
            logger.exception("Failed to discover tickers for exchanges %s", exchange)
            return []

    tickers = await asyncio.to_thread(_screen)
    _ticker_cache = (now, cache_key, tickers)
    return tickers


async def compute_breadth(
    tickers: list[str],
    alpaca: AlpacaProvider | None = None,
    yf: YFinanceProvider | None = None,
    exchange: str = DEFAULT_EXCHANGES,
) -> dict:
    """Compute advance/decline from live price data.

    Uses Alpaca snapshots if available (fast, batched).
    Falls back to paginated yfinance screener results if not.
    """
    advancing = 0
    declining = 0
    unchanged = 0

    if alpaca:
        try:
            snapshots = await alpaca.get_snapshot(tickers)
            for ticker, quote in snapshots.items():
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
        from dashboard.services.screener_engine import run_screen

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

        session.add(BreadthSnapshotORM(
            date=date_str,
            hour=hour,
            advancing=data["advancing"],
            declining=data["declining"],
            unchanged=data["unchanged"],
            total=data["total"],
            ad_ratio=data["ad_ratio"],
        ))
        await session.commit()

    logger.info(
        "Breadth snapshot saved: %d adv / %d dec / %d unch (ratio %.2f)",
        data["advancing"], data["declining"], data["unchanged"], data["ad_ratio"],
    )


async def breadth_scan_loop(
    db: Database,
    yf: YFinanceProvider,
    alpaca: AlpacaProvider | None = None,
) -> None:
    """Background task: compute and store breadth every hour during market hours."""
    from core.market_hours import is_market_open

    while True:
        try:
            if is_market_open():
                tickers = await discover_tickers(yf)
                if tickers:
                    data = await compute_breadth(tickers, alpaca=alpaca, yf=yf)
                    if data["total"] > 0:
                        await save_breadth_snapshot(db, data)
        except Exception:
            logger.exception("Breadth scan loop error")

        await asyncio.sleep(3600)  # 1 hour
