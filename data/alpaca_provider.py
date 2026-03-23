"""
Alpaca Markets data provider (free tier).

Provides real-time market data via:
  - WebSocket streaming minute bars (IEX exchange feed)
  - REST snapshots for bulk price checks

Free tier limitations:
  - IEX feed only (~2-5% of total volume per stock)
  - 200 REST requests/minute
  - WebSocket: max 16KB message size (batch subscriptions ~500 tickers per message)

Architecture:
  - WebSocket runs in a background task, updating an in-memory price cache
  - REST snapshots used for initial load and fallback for sparse tickers
  - Price cache is the source of truth for the scanner
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, AsyncIterator

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from config.settings import Settings
from core.models import BarData, StockInfo, StockQuote
from data.base import MarketDataProvider

logger = logging.getLogger(__name__)

# Alpaca WebSocket message batch size (stay under 16KB limit)
WS_TICKER_BATCH_SIZE = 500

# REST snapshot batch size
REST_SNAPSHOT_BATCH_SIZE = 200  # Keep URL under Alpaca's length limit


class AlpacaProvider(MarketDataProvider):
    """
    Real-time market data via Alpaca free tier.

    Streams minute bars over WebSocket and maintains an in-memory
    price cache that the scanner reads from.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.alpaca_api_key
        self._api_secret = settings.alpaca_api_secret
        self._ws_url = settings.alpaca_data_ws_url
        self._rest_url = settings.alpaca_data_rest_url

        # In-memory price cache: ticker -> StockQuote
        self._cache: dict[str, StockQuote] = {}
        self._cache_lock = asyncio.Lock()

        # WebSocket state
        self._ws: ClientConnection | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._ws_authenticated = False
        self._subscribed_tickers: set[str] = set()

        # REST client
        self._http: httpx.AsyncClient | None = None

        # Bar callback for streaming
        self._bar_queue: asyncio.Queue[BarData] = asyncio.Queue(maxsize=10000)

        self._connected = False

    @property
    def cache(self) -> dict[str, StockQuote]:
        """Read-only access to the price cache."""
        return self._cache

    async def _rate_limit_delay(self, resp: httpx.Response) -> None:
        """
        Adaptive rate limiting using Alpaca's response headers.

        Reads X-RateLimit-Remaining and X-RateLimit-Reset to determine
        the optimal delay. Falls back to a fixed 0.35s if headers are missing.
        """
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")

        if remaining is not None and reset is not None:
            try:
                remaining_int = int(remaining)
                import time as _time
                reset_ts = int(reset)
                now_ts = int(_time.time())
                window_remaining = max(reset_ts - now_ts, 1)

                if remaining_int <= 5:
                    # Nearly exhausted — wait for the window to reset
                    delay = window_remaining
                    logger.warning(
                        "Alpaca rate limit nearly exhausted (%d remaining), waiting %ds",
                        remaining_int, delay,
                    )
                elif remaining_int <= 20:
                    # Getting low — spread remaining requests across the window
                    delay = window_remaining / max(remaining_int, 1)
                else:
                    # Plenty of headroom — minimal delay
                    delay = 0.1

                await asyncio.sleep(delay)
                return
            except (ValueError, TypeError):
                pass

        # Fallback: fixed delay (~3 req/sec, well within 200 req/min)
        await asyncio.sleep(0.35)

    async def connect(self) -> None:
        """Initialise HTTP client. WebSocket connects separately via start_streaming."""
        self._http = httpx.AsyncClient(
            base_url=self._rest_url,
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._api_secret,
            },
            timeout=30.0,
        )
        self._connected = True
        logger.info("Alpaca REST client connected")

    async def disconnect(self) -> None:
        """Shut down WebSocket and HTTP client."""
        self._connected = False

        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._http:
            await self._http.aclose()
            self._http = None

        logger.info("Alpaca provider disconnected")

    # =========================================================================
    # REST endpoints
    # =========================================================================

    async def get_snapshot(self, tickers: list[str]) -> dict[str, StockQuote]:
        """
        Get current price snapshot for specific tickers via REST.

        Uses the /v2/stocks/snapshots endpoint which accepts multiple tickers.
        Adaptive rate limiting via Alpaca's X-RateLimit-* response headers.
        """
        if not self._http:
            raise RuntimeError("Alpaca provider not connected")

        # Filter out warrants, preferred shares, and other non-standard
        # tickers that Alpaca rejects (e.g. MOBBW, CIG-C, DJTWW).
        tickers = [t for t in tickers if t.isalpha()]

        result: dict[str, StockQuote] = {}
        total_batches = (len(tickers) + REST_SNAPSHOT_BATCH_SIZE - 1) // REST_SNAPSHOT_BATCH_SIZE

        for batch_num, i in enumerate(range(0, len(tickers), REST_SNAPSHOT_BATCH_SIZE)):
            batch = tickers[i : i + REST_SNAPSHOT_BATCH_SIZE]
            symbols = ",".join(batch)

            try:
                resp = await self._http.get(
                    "/v2/stocks/snapshots",
                    params={"symbols": symbols, "feed": self._settings.alpaca_feed.value},
                )
                resp.raise_for_status()
                data = resp.json()

                for ticker, snap in data.items():
                    quote = self._snapshot_to_quote(ticker, snap)
                    if quote:
                        result[ticker] = quote
                        async with self._cache_lock:
                            self._cache[ticker] = quote

                # Adaptive delay based on remaining rate limit
                if batch_num < total_batches - 1:
                    await self._rate_limit_delay(resp)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 60))
                    logger.warning("Alpaca rate limited — waiting %ds", retry_after)
                    await asyncio.sleep(retry_after)
                else:
                    logger.error("Alpaca snapshot request failed: %s", e)
            except Exception:
                logger.exception("Unexpected error fetching Alpaca snapshots")

        return result

    async def get_all_snapshots(self) -> dict[str, StockQuote]:
        """
        Get snapshots for all cached tickers.

        For initial universe loading — fetches all subscribed tickers.
        """
        if not self._subscribed_tickers:
            logger.warning("No tickers subscribed — returning empty snapshots")
            return {}

        return await self.get_snapshot(list(self._subscribed_tickers))

    async def get_historical_bars(
        self,
        ticker: str,
        timeframe: str = "1Min",
        limit: int = 100,
    ) -> list[BarData]:
        """Fetch historical bars for a single ticker."""
        if not self._http:
            raise RuntimeError("Alpaca provider not connected")

        try:
            resp = await self._http.get(
                f"/v2/stocks/{ticker}/bars",
                params={
                    "timeframe": timeframe,
                    "limit": limit,
                    "feed": self._settings.alpaca_feed.value,
                    "sort": "desc",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            bars = []
            for bar in data.get("bars", []):
                bars.append(BarData(
                    ticker=ticker,
                    timestamp=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
                    open=bar["o"],
                    high=bar["h"],
                    low=bar["l"],
                    close=bar["c"],
                    volume=bar["v"],
                ))
            return bars

        except Exception:
            logger.exception("Failed to fetch historical bars for %s", ticker)
            return []

    async def get_intraday_bars(
        self,
        tickers: list[str],
        timeframe: str = "5Min",
        start: str = "",
        end: str = "",
    ) -> dict[str, list[dict]]:
        """Fetch intraday bars for multiple tickers.

        Args:
            tickers: List of ticker symbols.
            timeframe: Alpaca timeframe string (1Min, 5Min, 15Min, 30Min, 1Hour).
            start: ISO datetime string for range start (defaults to today's open).
            end: ISO datetime string for range end (defaults to now).

        Returns:
            Dict of ticker -> list of {timestamp, open, high, low, close, volume} dicts.
        """
        if not self._http:
            raise RuntimeError("Alpaca provider not connected")

        if not start:
            from core.market_hours import US_EASTERN, MARKET_OPEN
            from datetime import datetime as dt, date
            today_open = dt.combine(date.today(), MARKET_OPEN, tzinfo=US_EASTERN)
            start = today_open.isoformat()

        result: dict[str, list[dict]] = {}
        try:
            # Alpaca multi-bar endpoint
            resp = await self._http.get(
                "/v2/stocks/bars",
                params={
                    "symbols": ",".join(tickers),
                    "timeframe": timeframe,
                    "start": start,
                    **({"end": end} if end else {}),
                    "feed": self._settings.alpaca_feed.value,
                    "limit": 10000,
                    "sort": "asc",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            for ticker, bars in data.get("bars", {}).items():
                result[ticker] = [
                    {
                        "timestamp": bar["t"],
                        "open": bar["o"],
                        "high": bar["h"],
                        "low": bar["l"],
                        "close": bar["c"],
                        "volume": bar["v"],
                    }
                    for bar in bars
                ]

        except Exception:
            logger.exception("Failed to fetch intraday bars")

        return result

    async def get_intraday_quotes(
        self,
        ticker: str,
        start: str = "",
        end: str = "",
        limit: int = 10000,
    ) -> list[dict]:
        """Fetch intraday bid/ask quotes for a single ticker.

        Returns list of {timestamp, bid, ask, bid_size, ask_size} dicts.
        """
        if not self._http:
            raise RuntimeError("Alpaca provider not connected")

        if not start:
            from core.market_hours import US_EASTERN, MARKET_OPEN
            from datetime import datetime as dt, date
            today_open = dt.combine(date.today(), MARKET_OPEN, tzinfo=US_EASTERN)
            start = today_open.isoformat()

        try:
            resp = await self._http.get(
                f"/v2/stocks/{ticker}/quotes",
                params={
                    "start": start,
                    **({"end": end} if end else {}),
                    "feed": self._settings.alpaca_feed.value,
                    "limit": limit,
                    "sort": "asc",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            return [
                {
                    "timestamp": q["t"],
                    "bid": q.get("bp", 0),
                    "ask": q.get("ap", 0),
                    "bid_size": q.get("bs", 0),
                    "ask_size": q.get("as", 0),
                }
                for q in data.get("quotes", [])
                if q.get("bp", 0) > 0 or q.get("ap", 0) > 0
            ]

        except Exception:
            logger.exception("Failed to fetch intraday quotes for %s", ticker)
            return []

    async def get_instruments(self) -> list[StockInfo]:
        """
        Not applicable for Alpaca — use get_tradeable_assets() for universe discovery.
        Returns empty list.
        """
        return []

    async def get_tradeable_assets(self) -> list[dict[str, str]]:
        """
        Fetch all tradeable US equity assets from Alpaca.

        Calls /v2/assets on the trading API (paper-api.alpaca.markets).
        Returns list of {symbol, name, exchange} for NASDAQ/NYSE active equities.
        """
        async with httpx.AsyncClient(
            base_url="https://paper-api.alpaca.markets",
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._api_secret,
            },
            timeout=30.0,
        ) as client:
            resp = await client.get(
                "/v2/assets",
                params={
                    "status": "active",
                    "asset_class": "us_equity",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        target_exchanges = {"NASDAQ", "NYSE", "NYSE ARCA", "NYSE MKT", "AMEX", "BATS"}
        assets = []
        for item in data:
            if not item.get("tradable", False):
                continue
            exchange = item.get("exchange", "")
            if exchange not in target_exchanges:
                continue
            assets.append({
                "symbol": item["symbol"],
                "name": item.get("name", ""),
                "exchange": exchange,
            })

        logger.info("Alpaca: fetched %d tradeable US equity assets", len(assets))
        return assets

    async def get_penny_stock_universe(
        self,
        price_min: float = 0.01,
        price_max: float = 5.0,
    ) -> list[StockInfo]:
        """
        Discover penny stocks using Alpaca assets + snapshot pricing.

        1. Fetch all tradeable assets via /v2/assets
        2. Batch-fetch snapshots to get current prices
        3. Filter to price range
        """
        assets = await self.get_tradeable_assets()
        if not assets:
            return []

        # Build ticker list and metadata lookup
        all_tickers = [a["symbol"] for a in assets]
        meta = {a["symbol"]: a for a in assets}

        # Fetch snapshots in batches with adaptive rate limiting
        penny_stocks: list[StockInfo] = []
        total_batches = (len(all_tickers) + REST_SNAPSHOT_BATCH_SIZE - 1) // REST_SNAPSHOT_BATCH_SIZE

        # Filter out warrants, preferred shares, and other non-standard
        # tickers that Alpaca rejects (e.g. MOBBW, CIG-C, DJTWW).
        # Alpaca only accepts plain equity symbols: uppercase letters only.
        all_tickers = [t for t in all_tickers if t.isalpha()]

        for batch_num, i in enumerate(range(0, len(all_tickers), REST_SNAPSHOT_BATCH_SIZE)):
            batch = all_tickers[i : i + REST_SNAPSHOT_BATCH_SIZE]
            symbols = ",".join(batch)

            try:
                if not self._http:
                    raise RuntimeError("Alpaca provider not connected")
                resp = await self._http.get(
                    "/v2/stocks/snapshots",
                    params={"symbols": symbols, "feed": self._settings.alpaca_feed.value},
                )
                resp.raise_for_status()
                data = resp.json()

                for ticker, snap in data.items():
                    quote = self._snapshot_to_quote(ticker, snap)
                    if not quote:
                        continue
                    if price_min <= quote.price <= price_max:
                        info = meta.get(ticker, {})
                        penny_stocks.append(StockInfo(
                            ticker=ticker,
                            name=info.get("name", ""),
                            exchange=info.get("exchange", ""),
                            last_price=quote.price,
                            avg_volume=quote.volume,
                            in_universe=True,
                        ))
                        async with self._cache_lock:
                            self._cache[ticker] = quote

                # Adaptive delay based on remaining rate limit
                if batch_num < total_batches - 1:
                    await self._rate_limit_delay(resp)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 60))
                    logger.warning("Alpaca rate limited — waiting %ds", retry_after)
                    await asyncio.sleep(retry_after)
                else:
                    logger.error("Alpaca snapshot batch failed: %s", e)
            except Exception:
                logger.exception("Unexpected error in penny stock discovery batch")

        logger.info(
            "Alpaca: discovered %d penny stocks ($%.2f–$%.2f) from %d assets",
            len(penny_stocks), price_min, price_max, len(all_tickers),
        )
        return penny_stocks

    # =========================================================================
    # WebSocket streaming
    # =========================================================================

    async def start_streaming(self, tickers: list[str]) -> None:
        """
        Start WebSocket connection and subscribe to minute bars.

        Runs in a background task. Call stop_streaming() to shut down.
        """
        self._subscribed_tickers = set(tickers)
        self._ws_task = asyncio.create_task(self._ws_loop())
        logger.info("Alpaca WebSocket streaming started for %d tickers", len(tickers))

    async def stop_streaming(self) -> None:
        """Stop the WebSocket background task."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    async def stream_bars(self, tickers: list[str]) -> AsyncIterator[BarData]:
        """
        Yield bars from the internal queue.

        Bars are pushed into the queue by the WebSocket background task.
        """
        while self._connected:
            try:
                bar = await asyncio.wait_for(self._bar_queue.get(), timeout=5.0)
                yield bar
            except asyncio.TimeoutError:
                continue

    async def update_subscriptions(self, tickers: list[str]) -> None:
        """Update which tickers the WebSocket is subscribed to."""
        new_tickers = set(tickers)
        to_add = new_tickers - self._subscribed_tickers
        to_remove = self._subscribed_tickers - new_tickers

        if self._ws and self._ws_authenticated:
            if to_remove:
                await self._ws_unsubscribe(list(to_remove))
            if to_add:
                await self._ws_subscribe(list(to_add))

        self._subscribed_tickers = new_tickers

    # =========================================================================
    # WebSocket internals
    # =========================================================================

    async def _ws_loop(self) -> None:
        """Main WebSocket loop with auto-reconnect."""
        backoff = 1.0
        max_backoff = 60.0

        while self._connected:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    backoff = 1.0  # Reset on successful connect

                    # Authenticate
                    await self._ws_authenticate(ws)

                    # Subscribe to bars
                    if self._subscribed_tickers:
                        await self._ws_subscribe(list(self._subscribed_tickers))

                    # Process messages
                    async for raw_msg in ws:
                        if not self._connected:
                            break
                        await self._handle_ws_message(raw_msg)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WebSocket error — reconnecting in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        self._ws = None
        self._ws_authenticated = False

    async def _ws_authenticate(self, ws: ClientConnection) -> None:
        """Authenticate with the Alpaca WebSocket."""
        # Read the welcome message
        welcome = await ws.recv()
        logger.debug("WS welcome: %s", welcome)

        # Send auth
        auth_msg = json.dumps({
            "action": "auth",
            "key": self._api_key,
            "secret": self._api_secret,
        })
        await ws.send(auth_msg)

        # Read auth response
        auth_resp = await ws.recv()
        data = json.loads(auth_resp)

        if isinstance(data, list):
            for msg in data:
                if msg.get("T") == "success" and msg.get("msg") == "authenticated":
                    self._ws_authenticated = True
                    logger.info("Alpaca WebSocket authenticated")
                    return
                if msg.get("T") == "error":
                    raise ConnectionError(f"Alpaca WS auth failed: {msg.get('msg')}")

        raise ConnectionError(f"Unexpected auth response: {data}")

    async def _ws_subscribe(self, tickers: list[str]) -> None:
        """Subscribe to minute bars for given tickers (batched)."""
        if not self._ws:
            return

        for i in range(0, len(tickers), WS_TICKER_BATCH_SIZE):
            batch = tickers[i : i + WS_TICKER_BATCH_SIZE]
            msg = json.dumps({
                "action": "subscribe",
                "bars": batch,
            })
            await self._ws.send(msg)
            logger.debug("Subscribed to bars for %d tickers", len(batch))

    async def _ws_unsubscribe(self, tickers: list[str]) -> None:
        """Unsubscribe from bars for given tickers."""
        if not self._ws:
            return

        for i in range(0, len(tickers), WS_TICKER_BATCH_SIZE):
            batch = tickers[i : i + WS_TICKER_BATCH_SIZE]
            msg = json.dumps({
                "action": "unsubscribe",
                "bars": batch,
            })
            await self._ws.send(msg)

    async def _handle_ws_message(self, raw: str | bytes) -> None:
        """Parse incoming WebSocket messages and update cache."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from WebSocket: %s", raw[:100])
            return

        if not isinstance(data, list):
            return

        for msg in data:
            msg_type = msg.get("T")

            if msg_type == "b":
                # Minute bar
                await self._process_bar(msg)
            elif msg_type == "success":
                logger.debug("WS success: %s", msg.get("msg"))
            elif msg_type == "subscription":
                bars_count = len(msg.get("bars", []))
                logger.debug("WS subscription update: %d bar subs", bars_count)
            elif msg_type == "error":
                logger.error("WS error: code=%s msg=%s", msg.get("code"), msg.get("msg"))

    async def _process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single minute bar from WebSocket."""
        ticker = bar.get("S", "")
        if not ticker:
            return

        try:
            bar_data = BarData(
                ticker=ticker,
                timestamp=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
                open=bar["o"],
                high=bar["h"],
                low=bar["l"],
                close=bar["c"],
                volume=bar["v"],
            )
        except (KeyError, ValueError) as e:
            logger.warning("Failed to parse bar for %s: %s", ticker, e)
            return

        # Update price cache
        async with self._cache_lock:
            existing = self._cache.get(ticker)
            self._cache[ticker] = StockQuote(
                ticker=ticker,
                price=bar_data.close,
                open_price=existing.open_price if existing else bar_data.open,
                high=max(existing.high, bar_data.high) if existing else bar_data.high,
                low=min(existing.low, bar_data.low) if existing and existing.low > 0 else bar_data.low,
                prev_close=existing.prev_close if existing else 0.0,
                volume=(existing.volume if existing else 0) + bar_data.volume,
                timestamp=bar_data.timestamp,
            )

        # Push to bar queue for stream_bars()
        try:
            self._bar_queue.put_nowait(bar_data)
        except asyncio.QueueFull:
            logger.debug("Bar queue full — dropping bar for %s", bar_data.ticker)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _snapshot_to_quote(self, ticker: str, snap: dict[str, Any]) -> StockQuote | None:
        """Convert Alpaca snapshot JSON to StockQuote."""
        try:
            latest_trade = snap.get("latestTrade", {})
            minute_bar = snap.get("minuteBar", {})
            daily_bar = snap.get("dailyBar", {})
            prev_daily = snap.get("prevDailyBar", {})

            price = latest_trade.get("p", 0.0)
            if price <= 0:
                return None

            prev_close = prev_daily.get("c", 0.0)
            change_pct = 0.0
            if prev_close > 0:
                change_pct = ((price - prev_close) / prev_close) * 100

            return StockQuote(
                ticker=ticker,
                price=price,
                open_price=daily_bar.get("o", 0.0),
                high=daily_bar.get("h", 0.0),
                low=daily_bar.get("l", 0.0),
                prev_close=prev_close,
                volume=daily_bar.get("v", 0),
                change_pct=change_pct,
                timestamp=datetime.now(UTC),
            )
        except Exception:
            logger.warning("Failed to parse snapshot for %s", ticker)
            return None
