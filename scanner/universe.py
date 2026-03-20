"""
Penny stock universe manager.

Responsibilities:
  1. On startup, discover all penny stocks via yfinance screener (primary) or Alpaca (fallback)
  2. Update live prices from Alpaca snapshots
  3. Enrich with market cap/sector from yfinance
  4. Cross-reference with Trading 212 instruments for ticker mapping
  5. Cache results in SQLite — refresh daily at market open
  6. Provide fast in-memory access to the active universe

Data flow:
  yfinance screener → price/market cap filter → Alpaca live prices → yfinance enrichment → SQLite cache
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select, update

from config.constants import SUPPORTED_EXCHANGES, T212_TICKER_SUFFIX
from config.settings import Settings
from core.models import StockInfo
from db.database import Database
from db.models import UniverseStockORM

if TYPE_CHECKING:
    from data.alpaca_provider import AlpacaProvider
    from data.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


class UniverseManager:
    """
    Manages the set of penny stocks being actively monitored.

    The universe is the list of all stocks that qualify for scanning:
    - Listed on NASDAQ or NYSE
    - Price within configurable range (default $0.01–$5)
    - Actively trading (not halted/delisted)

    Primary source: yfinance screener (no API key, price + market cap filtering).
    Supplementary: Alpaca for live price updates.
    Optional enrichment: yfinance for missing market cap/sector data.

    The universe is cached in SQLite and refreshed daily.
    An in-memory dict provides O(1) lookups during scanning.
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        data_provider: AlpacaProvider | None = None,
        yfinance_provider: YFinanceProvider | None = None,
    ) -> None:
        self._settings = settings
        self._db = db
        self._data_provider = data_provider
        self._yfinance = yfinance_provider

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
        2. If cache is stale (>24h) or empty, refresh from Alpaca/yfinance
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

        Primary: yfinance screener (price + market cap filtering, no API key needed).
        Supplementary: Alpaca snapshots update live prices for the discovered set.
        Optional: yfinance enrichment for missing market cap/sector data.
        """
        stocks: list[StockInfo] = []

        # Primary: yfinance screener
        if self._yfinance:
            logger.info("Refreshing penny stock universe from yfinance...")
            try:
                stocks = await self._yfinance.filter_penny_stocks(
                    price_min=self._settings.scan_price_min,
                    price_max=self._settings.scan_price_max,
                    market_cap_min=self._settings.scan_market_cap_min,
                    market_cap_max=self._settings.scan_market_cap_max,
                )
            except Exception:
                logger.exception("yfinance universe discovery failed")

        # Fallback: Alpaca discovery if yfinance returned nothing
        if not stocks and self._data_provider:
            logger.info("Falling back to Alpaca for universe discovery...")
            try:
                stocks = await self._data_provider.get_penny_stock_universe(
                    price_min=self._settings.scan_price_min,
                    price_max=self._settings.scan_price_max,
                )
            except Exception:
                logger.exception("Alpaca universe discovery failed")

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

        # Supplementary: update live prices from Alpaca snapshots
        await self._update_prices_from_alpaca()

        # Optional: yfinance enrichment for market cap/sector (background, rate-limited)
        await self._enrich_from_yfinance()

    async def _update_prices_from_alpaca(self) -> None:
        """Update live prices for discovered stocks from Alpaca snapshots."""
        if not self._data_provider:
            return

        tickers = list(self._stocks.keys())
        if not tickers:
            return

        logger.info("Updating live prices from Alpaca for %d tickers...", len(tickers))
        try:
            snapshots = await self._data_provider.get_snapshot(tickers)
            updated = 0
            for ticker, snap in snapshots.items():
                stock = self._stocks.get(ticker)
                if stock and snap:
                    # snap is a StockQuote Pydantic model, not a dict
                    price = getattr(snap, "price", None) or getattr(snap, "close", None)
                    if price:
                        stock.last_price = price
                        updated += 1
            if updated:
                logger.info("Alpaca price update: %d/%d tickers updated", updated, len(tickers))
        except Exception:
            logger.exception("Alpaca price update failed")

    async def _enrich_from_yfinance(self) -> None:
        """Enrich stocks missing market cap data using yfinance."""
        if not self._yfinance:
            return

        # Find tickers without market cap data
        missing = [t for t, s in self._stocks.items() if not s.market_cap]
        if not missing:
            return

        logger.info("Enriching %d tickers with yfinance data...", len(missing))
        try:
            enriched = await self._yfinance.enrich_batch(missing, max_calls=50)

            for ticker, data in enriched.items():
                stock = self._stocks.get(ticker)
                if stock:
                    stock.market_cap = data.get("market_cap")
                    stock.sector = data.get("sector", "")
                    stock.industry = data.get("industry", "")
                    stock.shares_outstanding = data.get("shares_outstanding")
                    # Compute inferred market cap
                    if stock.shares_outstanding and stock.last_price:
                        stock.inferred_market_cap = stock.shares_outstanding * stock.last_price

            # Re-apply market cap filter and re-save
            if enriched:
                filtered = self._apply_market_cap_filter(list(self._stocks.values()))
                self._stocks = {s.ticker: s for s in filtered}
                await self._save_to_cache(list(self._stocks.values()))
                logger.info("yfinance enrichment complete: %d tickers updated", len(enriched))

        except Exception:
            logger.exception("yfinance enrichment failed")

    def _apply_market_cap_filter(self, stocks: list[StockInfo]) -> list[StockInfo]:
        """Filter stocks by market cap if thresholds are configured."""
        min_cap = self._settings.scan_market_cap_min
        max_cap = self._settings.scan_market_cap_max

        if not min_cap and not max_cap:
            return stocks

        use_inferred = self._settings.market_cap_source == "inferred"

        filtered = []
        for stock in stocks:
            cap = stock.inferred_market_cap if use_inferred else stock.market_cap
            # If no market cap data, keep the stock (will be enriched later)
            if not cap:
                filtered.append(stock)
                continue
            if min_cap and cap < min_cap:
                continue
            if max_cap and cap > max_cap:
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
                        shares_outstanding=row.shares_outstanding,
                        inferred_market_cap=row.inferred_market_cap,
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
                        existing.shares_outstanding = stock.shares_outstanding
                        existing.inferred_market_cap = stock.inferred_market_cap
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
                            shares_outstanding=stock.shares_outstanding,
                            inferred_market_cap=stock.inferred_market_cap,
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
