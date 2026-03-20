"""
Penny stock universe manager.

Responsibilities:
  1. On startup, discover all penny stocks via Alpaca (primary) or FMP (fallback)
  2. Optionally enrich with market cap/sector from FMP
  3. Cross-reference with Trading 212 instruments for ticker mapping
  4. Cache results in SQLite — refresh daily at market open
  5. Provide fast in-memory access to the active universe

Data flow:
  Alpaca assets + snapshots → price filter → FMP enrichment (optional) → SQLite cache → in-memory dict
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select, update

from config.constants import SUPPORTED_EXCHANGES, T212_TICKER_SUFFIX
from config.settings import Settings
from core.models import StockInfo
from data.fmp_provider import FMPProvider
from db.database import Database
from db.models import UniverseStockORM

if TYPE_CHECKING:
    from data.alpaca_provider import AlpacaProvider

logger = logging.getLogger(__name__)


class UniverseManager:
    """
    Manages the set of penny stocks being actively monitored.

    The universe is the list of all stocks that qualify for scanning:
    - Listed on NASDAQ or NYSE
    - Price within configurable range (default $0.01–$5)
    - Actively trading (not halted/delisted)

    Primary source: Alpaca (free, reliable).
    Optional enrichment: FMP for market cap/sector data.

    The universe is cached in SQLite and refreshed daily.
    An in-memory dict provides O(1) lookups during scanning.
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        data_provider: AlpacaProvider | None = None,
    ) -> None:
        self._settings = settings
        self._db = db
        self._data_provider = data_provider
        self._fmp = FMPProvider(settings) if settings.fmp_api_key else None

        # In-memory cache: ticker -> StockInfo
        self._stocks: dict[str, StockInfo] = {}
        self._last_refresh: datetime | None = None

    @property
    def tickers(self) -> list[str]:
        """All tickers currently in the universe."""
        return list(self._stocks.keys())

    @property
    def size(self) -> int:
        return len(self._stocks)

    @property
    def last_refresh(self) -> datetime | None:
        return self._last_refresh

    def get(self, ticker: str) -> StockInfo | None:
        """Look up a single stock by ticker."""
        return self._stocks.get(ticker)

    def get_all(self) -> list[StockInfo]:
        """Return all stocks in the universe."""
        return list(self._stocks.values())

    def get_t212_ticker(self, ticker: str) -> str:
        """Convert standard ticker to Trading 212 format."""
        stock = self._stocks.get(ticker)
        if stock and stock.t212_ticker:
            return stock.t212_ticker
        return f"{ticker}{T212_TICKER_SUFFIX}"

    async def initialise(self) -> None:
        """
        Load universe on startup.

        Strategy:
        1. Try loading from SQLite cache (fast)
        2. If cache is stale (>24h) or empty, refresh from Alpaca/FMP
        """
        # Try cache first
        cached = await self._load_from_cache()
        if cached:
            self._stocks = {s.ticker: s for s in cached}
            self._last_refresh = max(
                (s.last_price for s in cached),  # rough proxy
                default=None
            )
            logger.info(
                "Universe loaded from cache: %d stocks", len(self._stocks)
            )

            # Check if cache is fresh enough
            if await self._is_cache_fresh():
                return

            logger.info("Cache is stale — refreshing")

        # Full refresh
        await self.refresh()

    def __len__(self) -> int:
        return len(self._stocks)

    async def refresh(self) -> None:
        """
        Full universe refresh.

        Primary: Alpaca (assets + snapshots filtered by price range).
        Fallback: FMP stock screener (if Alpaca unavailable).
        Optional: FMP enrichment for market cap/sector.
        """
        stocks: list[StockInfo] = []

        # Primary: Alpaca
        if self._data_provider:
            logger.info("Refreshing penny stock universe from Alpaca...")
            try:
                stocks = await self._data_provider.get_penny_stock_universe(
                    price_min=self._settings.scan_price_min,
                    price_max=self._settings.scan_price_max,
                )
            except Exception:
                logger.exception("Alpaca universe discovery failed")

        # Fallback: FMP screener
        if not stocks and self._fmp:
            logger.info("Falling back to FMP for universe discovery...")
            try:
                async with self._fmp:
                    stocks = await self._fmp.get_penny_stocks()
            except Exception:
                logger.exception("FMP universe discovery failed")

        if not stocks:
            if self._stocks:
                logger.warning("No stocks discovered — keeping existing cache")
            else:
                logger.warning("No stocks discovered and no cache available")
            return

        # Map T212 tickers
        for stock in stocks:
            stock.t212_ticker = f"{stock.ticker}{T212_TICKER_SUFFIX}"

        # Apply market cap filter if we have market cap data and filters are set
        stocks = self._apply_market_cap_filter(stocks)

        # Update in-memory cache
        self._stocks = {s.ticker: s for s in stocks}
        self._last_refresh = datetime.now(UTC)

        # Persist to SQLite
        await self._save_to_cache(stocks)

        logger.info(
            "Universe refreshed: %d penny stocks across NASDAQ/NYSE",
            len(self._stocks),
        )

        # Optional: FMP enrichment for market cap/sector (background, rate-limited)
        await self._enrich_from_fmp()

    async def _enrich_from_fmp(self) -> None:
        """Enrich stocks missing market cap data using FMP profiles."""
        if not self._fmp or not self._settings.fmp_api_key:
            return

        # Find tickers without market cap data
        missing = [t for t, s in self._stocks.items() if not s.market_cap]
        if not missing:
            return

        logger.info("Enriching %d tickers with FMP market cap data...", len(missing))
        try:
            async with self._fmp:
                enriched = await self._fmp.enrich_batch(missing, max_calls=50)

            for ticker, data in enriched.items():
                stock = self._stocks.get(ticker)
                if stock:
                    stock.market_cap = data.get("market_cap", 0)
                    stock.sector = data.get("sector", "")
                    stock.industry = data.get("industry", "")

            # Re-apply market cap filter and re-save
            if enriched:
                filtered = self._apply_market_cap_filter(list(self._stocks.values()))
                self._stocks = {s.ticker: s for s in filtered}
                await self._save_to_cache(list(self._stocks.values()))
                logger.info("FMP enrichment complete: %d tickers updated", len(enriched))

        except Exception:
            logger.exception("FMP enrichment failed")

    def _apply_market_cap_filter(self, stocks: list[StockInfo]) -> list[StockInfo]:
        """Filter stocks by market cap if thresholds are configured."""
        min_cap = self._settings.scan_market_cap_min
        max_cap = self._settings.scan_market_cap_max

        if not min_cap and not max_cap:
            return stocks

        filtered = []
        for stock in stocks:
            # If no market cap data, keep the stock (will be enriched later)
            if not stock.market_cap:
                filtered.append(stock)
                continue
            if min_cap and stock.market_cap < min_cap:
                continue
            if max_cap and stock.market_cap > max_cap:
                continue
            filtered.append(stock)

        removed = len(stocks) - len(filtered)
        if removed:
            logger.info(
                "Market cap filter removed %d stocks (min=$%.0f, max=$%.0f)",
                removed, min_cap, max_cap,
            )
        return filtered

    async def update_prices(self, prices: dict[str, float]) -> None:
        """
        Update cached prices from market data provider.
        Called periodically to keep universe prices current.

        Also removes stocks that have moved above the threshold.
        """
        removed = []
        for ticker, price in prices.items():
            stock = self._stocks.get(ticker)
            if stock:
                stock.last_price = price
                # Check if stock has graduated out of penny stock territory
                if price > self._settings.scan_price_max * 1.5:
                    # 50% buffer to avoid constant churn at the boundary
                    stock.in_universe = False
                    removed.append(ticker)

        if removed:
            for ticker in removed:
                del self._stocks[ticker]
            logger.info(
                "Removed %d stocks above price threshold: %s",
                len(removed),
                removed[:10],
            )

    async def _load_from_cache(self) -> list[StockInfo]:
        """Load universe from SQLite cache."""
        try:
            async with self._db.session() as session:
                result = await session.execute(
                    select(UniverseStockORM).where(
                        UniverseStockORM.in_universe.is_(True)
                    )
                )
                rows = result.scalars().all()

                return [
                    StockInfo(
                        ticker=row.ticker,
                        name=row.name,
                        exchange=row.exchange,
                        t212_ticker=row.t212_ticker,
                        sector=row.sector,
                        industry=row.industry,
                        market_cap=row.market_cap,
                        avg_volume=row.avg_volume,
                        last_price=row.last_price,
                        in_universe=row.in_universe,
                    )
                    for row in rows
                ]
        except Exception:
            logger.exception("Failed to load universe from cache")
            return []

    async def _save_to_cache(self, stocks: list[StockInfo]) -> None:
        """Persist universe to SQLite, replacing existing data."""
        try:
            async with self._db.session() as session:
                # Mark all existing as out of universe
                await session.execute(
                    update(UniverseStockORM).values(in_universe=False)
                )

                # Upsert each stock
                for stock in stocks:
                    existing = await session.get(UniverseStockORM, stock.ticker)
                    if existing:
                        existing.name = stock.name
                        existing.exchange = stock.exchange
                        existing.t212_ticker = stock.t212_ticker
                        existing.sector = stock.sector
                        existing.industry = stock.industry
                        existing.market_cap = stock.market_cap
                        existing.avg_volume = stock.avg_volume
                        existing.last_price = stock.last_price
                        existing.in_universe = True
                        existing.updated_at = datetime.now(UTC)
                    else:
                        session.add(UniverseStockORM(
                            ticker=stock.ticker,
                            name=stock.name,
                            exchange=stock.exchange,
                            t212_ticker=stock.t212_ticker,
                            sector=stock.sector,
                            industry=stock.industry,
                            market_cap=stock.market_cap,
                            avg_volume=stock.avg_volume,
                            last_price=stock.last_price,
                            in_universe=True,
                            updated_at=datetime.now(UTC),
                        ))

                await session.commit()
                logger.info("Universe cache updated: %d stocks", len(stocks))

        except Exception:
            logger.exception("Failed to save universe to cache")

    async def _is_cache_fresh(self) -> bool:
        """Check if cache was updated within the last 24 hours."""
        try:
            async with self._db.session() as session:
                result = await session.execute(
                    select(UniverseStockORM.updated_at)
                    .where(UniverseStockORM.in_universe.is_(True))
                    .order_by(UniverseStockORM.updated_at.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return False

                age = datetime.now(UTC) - row
                return age < timedelta(hours=24)
        except Exception:
            return False
