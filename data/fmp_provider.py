"""
Financial Modeling Prep (FMP) provider for penny stock universe discovery.

FMP free tier provides:
  - Stock Screener: filter by price, exchange, market cap in a single call
  - Stock list: all tradeable tickers with basic metadata
  - Rate limit: ~250 calls/day on free tier

This is NOT a real-time data provider — it's used specifically for
discovering which stocks qualify as penny stocks (price < threshold).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import Settings
from core.models import StockInfo

logger = logging.getLogger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
FMP_STABLE_URL = "https://financialmodelingprep.com/stable"


class FMPProvider:
    """
    Fetches penny stock universe from Financial Modeling Prep.

    Used at startup and daily refresh to build the list of stocks
    to monitor. Not used for real-time price data.
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.fmp_api_key
        self._price_min = settings.scan_price_min
        self._price_max = settings.scan_price_max
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        if not self._client:
            raise RuntimeError("FMPProvider not connected — call connect() first")
        if not self._api_key:
            raise RuntimeError("FMP API key not configured")

        params = params or {}
        params["apikey"] = self._api_key

        url = f"{FMP_BASE_URL}/{endpoint}"
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_penny_stocks(self) -> list[StockInfo]:
        """
        Fetch all stocks under the price threshold on NASDAQ/NYSE.

        Uses the FMP Stock Screener endpoint which filters server-side,
        minimising API calls on the free tier.
        """
        all_stocks: list[StockInfo] = []

        for exchange in ("NASDAQ", "NYSE"):
            try:
                data = await self._get("stock-screener", params={
                    "priceLowerThan": self._price_max,
                    "priceMoreThan": self._price_min,
                    "exchange": exchange,
                    "isActivelyTrading": "true",
                    "limit": 5000,
                })

                if not isinstance(data, list):
                    logger.warning("FMP screener returned non-list for %s", exchange)
                    continue

                for item in data:
                    stock = StockInfo(
                        ticker=item.get("symbol", ""),
                        name=item.get("companyName", ""),
                        exchange=exchange,
                        sector=item.get("sector", "") or "",
                        industry=item.get("industry", "") or "",
                        market_cap=item.get("marketCap"),
                        avg_volume=item.get("volume", 0) or 0,
                        last_price=item.get("price", 0.0) or 0.0,
                        in_universe=True,
                    )
                    if stock.ticker:
                        all_stocks.append(stock)

                logger.info(
                    "FMP: found %d penny stocks on %s ($%.2f–$%.2f)",
                    len(data), exchange, self._price_min, self._price_max,
                )

            except httpx.HTTPStatusError as e:
                logger.error("FMP screener request failed for %s: %s", exchange, e)
            except Exception:
                logger.exception("Unexpected error fetching FMP data for %s", exchange)

        logger.info("FMP: total penny stocks discovered: %d", len(all_stocks))
        return all_stocks

    async def get_stock_profile(self, ticker: str) -> dict[str, Any] | None:
        """
        Get a single stock's profile (market cap, sector, industry).

        Uses the /stable/profile endpoint which works on free tier
        for individual symbols. Rate-limited to ~250 calls/day.
        """
        if not self._client:
            raise RuntimeError("FMPProvider not connected — call connect() first")
        if not self._api_key:
            return None

        try:
            resp = await self._client.get(
                f"{FMP_STABLE_URL}/profile",
                params={"symbol": ticker, "apikey": self._api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("FMP profile fetch failed for %s", ticker)
        return None

    async def enrich_batch(
        self, tickers: list[str], max_calls: int = 50,
    ) -> dict[str, dict[str, Any]]:
        """
        Enrich a batch of tickers with market cap/sector data.

        Rate-limited: fetches up to max_calls profiles per invocation.
        Returns dict of ticker -> {market_cap, sector, industry}.
        """
        import asyncio

        results: dict[str, dict[str, Any]] = {}
        for ticker in tickers[:max_calls]:
            profile = await self.get_stock_profile(ticker)
            if profile:
                results[ticker] = {
                    "market_cap": profile.get("mktCap", 0),
                    "sector": profile.get("sector", ""),
                    "industry": profile.get("industry", ""),
                }
            await asyncio.sleep(0.5)  # ~2 req/s to stay under limits

        logger.info("FMP: enriched %d/%d tickers", len(results), len(tickers[:max_calls]))
        return results

    async def get_stock_quote(self, ticker: str) -> dict[str, Any] | None:
        """Get a single stock's current quote. Used for spot-checks."""
        try:
            data = await self._get(f"quote/{ticker}")
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.exception("FMP quote fetch failed for %s", ticker)
        return None

    async def __aenter__(self) -> FMPProvider:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()
