"""
Polygon.io market data provider (paid fallback).

Uses the Snapshot All Tickers endpoint which returns every US stock
with today's change percentage in a single API call — ideal for scanning.

This is a fallback if Alpaca's IEX feed proves insufficient for
penny stock coverage.

Requires a Polygon.io subscription ($29/mo for Stocks Starter plan).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import AsyncIterator

import httpx

from config.settings import Settings
from core.models import BarData, StockInfo, StockQuote
from data.base import MarketDataProvider

logger = logging.getLogger(__name__)

POLYGON_BASE_URL = "https://api.polygon.io"


class PolygonProvider(MarketDataProvider):
    """
    Market data via Polygon.io REST API.

    Primary use case: the Snapshot All Tickers endpoint returns
    every ticker with today's % change in a single call, making
    it excellent for broad market scanning.
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.polygon_api_key
        self._http: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=POLYGON_BASE_URL,
            timeout=30.0,
        )
        logger.info("Polygon provider connected")

    async def disconnect(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("Polygon provider disconnected")

    async def get_snapshot(self, tickers: list[str]) -> dict[str, StockQuote]:
        """Get snapshots for specific tickers."""
        if not self._http:
            raise RuntimeError("Polygon provider not connected")

        result: dict[str, StockQuote] = {}

        for ticker in tickers:
            try:
                resp = await self._http.get(
                    f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                    params={"apiKey": self._api_key},
                )
                resp.raise_for_status()
                data = resp.json()

                snap = data.get("ticker", {})
                quote = self._snap_to_quote(snap)
                if quote:
                    result[ticker] = quote

            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    logger.error("Polygon snapshot failed for %s: %s", ticker, e)
            except Exception:
                logger.exception("Error fetching Polygon snapshot for %s", ticker)

        return result

    async def get_all_snapshots(self) -> dict[str, StockQuote]:
        """
        Get snapshot for ALL US stocks in a single API call.

        This is Polygon's killer feature — returns every ticker with
        today's change percentage. Perfect for momentum scanning.
        """
        if not self._http:
            raise RuntimeError("Polygon provider not connected")

        result: dict[str, StockQuote] = {}

        try:
            resp = await self._http.get(
                "/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"apiKey": self._api_key},
                timeout=60.0,  # Large response
            )
            resp.raise_for_status()
            data = resp.json()

            for snap in data.get("tickers", []):
                quote = self._snap_to_quote(snap)
                if quote:
                    result[quote.ticker] = quote

            logger.info("Polygon: fetched snapshots for %d tickers", len(result))

        except httpx.HTTPStatusError as e:
            logger.error("Polygon all-tickers snapshot failed: %s", e)
        except Exception:
            logger.exception("Error fetching Polygon all-tickers snapshot")

        return result

    async def stream_bars(self, tickers: list[str]) -> AsyncIterator[BarData]:
        """
        Polygon WebSocket streaming is not implemented — use Alpaca for streaming.

        This provider is REST-only, designed for periodic polling via get_all_snapshots().
        """
        raise NotImplementedError(
            "PolygonProvider does not support streaming — use AlpacaProvider instead"
        )
        yield  # Make this a generator for type checking

    async def get_historical_bars(
        self,
        ticker: str,
        timeframe: str = "1Min",
        limit: int = 100,
    ) -> list[BarData]:
        """Fetch historical bars from Polygon."""
        if not self._http:
            raise RuntimeError("Polygon provider not connected")

        # Map timeframe to Polygon format
        tf_map = {
            "1Min": ("minute", 1),
            "5Min": ("minute", 5),
            "15Min": ("minute", 15),
            "1Hour": ("hour", 1),
            "1Day": ("day", 1),
        }
        tf_type, multiplier = tf_map.get(timeframe, ("minute", 1))

        try:
            resp = await self._http.get(
                f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{tf_type}"
                f"/2024-01-01/{datetime.utcnow().strftime('%Y-%m-%d')}",
                params={
                    "apiKey": self._api_key,
                    "adjusted": "true",
                    "sort": "desc",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            bars = []
            for result in data.get("results", []):
                bars.append(BarData(
                    ticker=ticker,
                    timestamp=datetime.fromtimestamp(result["t"] / 1000),
                    open=result["o"],
                    high=result["h"],
                    low=result["l"],
                    close=result["c"],
                    volume=result["v"],
                ))
            return bars

        except Exception:
            logger.exception("Failed to fetch Polygon historical bars for %s", ticker)
            return []

    async def get_instruments(self) -> list[StockInfo]:
        """Not used — FMPProvider handles universe discovery."""
        return []

    def _snap_to_quote(self, snap: dict) -> StockQuote | None:
        """Convert Polygon snapshot to StockQuote."""
        try:
            ticker = snap.get("ticker", "")
            if not ticker:
                return None

            day = snap.get("day", {})
            prev_day = snap.get("prevDay", {})

            price = day.get("c", 0.0) or snap.get("lastTrade", {}).get("p", 0.0)
            if price <= 0:
                return None

            prev_close = prev_day.get("c", 0.0)
            change_pct = snap.get("todaysChangePerc", 0.0)

            return StockQuote(
                ticker=ticker,
                price=price,
                open_price=day.get("o", 0.0),
                high=day.get("h", 0.0),
                low=day.get("l", 0.0),
                prev_close=prev_close,
                volume=day.get("v", 0),
                change_pct=change_pct,
                timestamp=datetime.utcnow(),
            )
        except Exception:
            return None
