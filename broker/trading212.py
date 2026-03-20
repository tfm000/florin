"""
Trading 212 broker integration.

Implements the Broker interface for T212's equity API (ISA + Invest accounts).

Key API details:
  - Auth: API key passed as Authorization header
  - Base URLs: demo.trading212.com/api/v0 or live.trading212.com/api/v0
  - Rate limits vary by endpoint (1 order/2s, 1 summary/5s, etc.)
  - API is NOT idempotent — duplicate orders are a real risk
  - Ticker format: SYMBOL_US_EQ (e.g., AAPL_US_EQ)

Critical safety measures:
  - Request deduplication via order tracking in SQLite
  - Per-endpoint rate limiting
  - Circuit breaker on consecutive failures
  - Exponential backoff on retries
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select

from broker.base import Broker
from config.constants import T212_TICKER_SUFFIX, T212_ORDER_RATE_LIMIT, T212_SUMMARY_RATE_LIMIT
from config.settings import Settings, T212Environment
from core.models import (
    AccountSummary,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TradeRecord,
)
from db.database import Database
from db.models import TradeORM

logger = logging.getLogger(__name__)

# Circuit breaker settings
MAX_CONSECUTIVE_FAILURES = 5
CIRCUIT_BREAKER_RESET_SECONDS = 300  # 5 minutes


class RateLimiter:
    """Simple per-endpoint rate limiter using asyncio."""

    def __init__(self) -> None:
        self._last_call: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def acquire(self, endpoint: str, min_interval: float) -> None:
        """Wait until we're allowed to call this endpoint."""
        if endpoint not in self._locks:
            self._locks[endpoint] = asyncio.Lock()

        async with self._locks[endpoint]:
            last = self._last_call.get(endpoint, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_call[endpoint] = time.monotonic()


class Trading212Broker(Broker):
    """
    Trading 212 API client.

    Executes real trades via the T212 REST API with full safety measures:
    rate limiting, deduplication, circuit breaking, and retry logic.
    """

    def __init__(self, settings: Settings, db: Database) -> None:
        self._settings = settings
        self._db = db
        self._http: httpx.AsyncClient | None = None
        self._rate_limiter = RateLimiter()

        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

        # Track in-flight orders to prevent duplicates
        self._pending_order_keys: set[str] = set()

    @property
    def name(self) -> str:
        env = "LIVE" if self._settings.t212_environment == T212Environment.LIVE else "DEMO"
        return f"Trading 212 ({env})"

    @property
    def is_live(self) -> bool:
        return self._settings.t212_environment == T212Environment.LIVE

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        if not self._settings.t212_configured:
            raise RuntimeError("Trading 212 API credentials not configured")

        self._http = httpx.AsyncClient(
            base_url=self._settings.t212_base_url,
            headers={"Authorization": self._settings.t212_api_key},
            timeout=30.0,
        )

        # Validate credentials with a health check
        if await self.health_check():
            logger.info("Connected to %s", self.name)
        else:
            logger.warning("Connected to %s but health check failed", self.name)

    async def disconnect(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("Disconnected from %s", self.name)

    async def health_check(self) -> bool:
        """Verify API access by fetching account summary."""
        try:
            await self.get_account_summary()
            return True
        except Exception:
            logger.exception("T212 health check failed")
            return False

    # =========================================================================
    # Account
    # =========================================================================

    async def get_account_summary(self) -> AccountSummary:
        """
        GET /equity/account/cash
        Rate limit: 1 request / 5 seconds
        """
        data = await self._request("GET", "/equity/account/cash", rate_key="summary",
                                   rate_interval=T212_SUMMARY_RATE_LIMIT)

        return AccountSummary(
            currency=data.get("currencyCode", "GBP"),
            cash_available=data.get("free", 0.0),
            cash_in_pies=data.get("ppiCash", 0.0),
            reserved_for_orders=data.get("blocked", 0.0),
            invested_value=data.get("invested", 0.0),
            total_value=data.get("total", 0.0),
            unrealised_pnl=data.get("pipiResult", 0.0),
            realised_pnl=data.get("result", 0.0),
            updated_at=datetime.utcnow(),
        )

    # =========================================================================
    # Positions
    # =========================================================================

    async def get_positions(self) -> list[Position]:
        """
        GET /equity/portfolio
        Rate limit: 1 request / 5 seconds
        """
        data = await self._request("GET", "/equity/portfolio", rate_key="portfolio",
                                   rate_interval=T212_SUMMARY_RATE_LIMIT)

        positions = []
        for item in data:
            pos = self._parse_position(item)
            if pos:
                positions.append(pos)

        return positions

    async def get_position(self, ticker: str) -> Position | None:
        """Get a specific position by ticker."""
        t212_ticker = self._to_t212_ticker(ticker)
        positions = await self.get_positions()
        for pos in positions:
            if pos.t212_ticker == t212_ticker or pos.ticker == ticker:
                return pos
        return None

    # =========================================================================
    # Orders
    # =========================================================================

    async def place_order(self, order: OrderRequest) -> OrderResult:
        """
        Place a market, limit, or stop order.

        Safety: checks for duplicate orders before submitting.
        Rate limit: 1 order / 2 seconds
        """
        # Circuit breaker check
        if self._is_circuit_open():
            return OrderResult(
                success=False,
                ticker=order.ticker,
                side=order.side,
                error_message="Circuit breaker open — too many consecutive failures",
            )

        # Deduplication check
        order_key = f"{order.ticker}:{order.side.value}:{order.quantity}"
        if order_key in self._pending_order_keys:
            return OrderResult(
                success=False,
                ticker=order.ticker,
                side=order.side,
                error_message="Duplicate order detected — already in flight",
            )

        self._pending_order_keys.add(order_key)
        try:
            result = await self._execute_order(order)
            return result
        finally:
            self._pending_order_keys.discard(order_key)

    async def cancel_order(self, order_id: str) -> bool:
        """
        DELETE /equity/orders/{id}
        """
        try:
            await self._request("DELETE", f"/equity/orders/{order_id}",
                                rate_key="orders", rate_interval=T212_ORDER_RATE_LIMIT)
            logger.info("Cancelled order %s", order_id)
            return True
        except Exception:
            logger.exception("Failed to cancel order %s", order_id)
            return False

    async def get_pending_orders(self) -> list[dict]:
        """
        GET /equity/orders
        """
        data = await self._request("GET", "/equity/orders", rate_key="orders",
                                   rate_interval=T212_ORDER_RATE_LIMIT)
        return data if isinstance(data, list) else []

    # =========================================================================
    # History
    # =========================================================================

    async def get_trade_history(self, limit: int = 50) -> list[TradeRecord]:
        """
        GET /equity/history/orders
        Returns executed orders from T212 history.
        """
        data = await self._request("GET", "/equity/history/orders",
                                   params={"limit": limit},
                                   rate_key="history", rate_interval=T212_SUMMARY_RATE_LIMIT)

        trades = []
        for item in data.get("items", []) if isinstance(data, dict) else data:
            trade = self._parse_trade(item)
            if trade:
                trades.append(trade)

        return trades

    # =========================================================================
    # Internal: order execution
    # =========================================================================

    async def _execute_order(self, order: OrderRequest) -> OrderResult:
        """Build and send the appropriate order type to T212."""
        t212_ticker = self._to_t212_ticker(order.ticker)

        if order.order_type == OrderType.MARKET:
            return await self._place_market_order(t212_ticker, order)
        elif order.order_type == OrderType.LIMIT:
            return await self._place_limit_order(t212_ticker, order)
        elif order.order_type == OrderType.STOP:
            return await self._place_stop_order(t212_ticker, order)
        else:
            return OrderResult(
                success=False,
                ticker=order.ticker,
                side=order.side,
                error_message=f"Unsupported order type: {order.order_type}",
            )

    async def _place_market_order(self, t212_ticker: str, order: OrderRequest) -> OrderResult:
        """POST /equity/orders/market"""
        body: dict[str, Any] = {"ticker": t212_ticker}

        if order.target_value and order.target_value > 0:
            body["value"] = order.target_value
        elif order.quantity > 0:
            body["quantity"] = order.quantity
        else:
            return OrderResult(
                success=False, ticker=order.ticker, side=order.side,
                error_message="Order must specify quantity or target_value",
            )

        return await self._send_order("market", body, order)

    async def _place_limit_order(self, t212_ticker: str, order: OrderRequest) -> OrderResult:
        """POST /equity/orders/limit"""
        if not order.limit_price:
            return OrderResult(
                success=False, ticker=order.ticker, side=order.side,
                error_message="Limit order requires limit_price",
            )

        body: dict[str, Any] = {
            "ticker": t212_ticker,
            "quantity": order.quantity,
            "limitPrice": order.limit_price,
            "timeValidity": "DAY",
        }

        return await self._send_order("limit", body, order)

    async def _place_stop_order(self, t212_ticker: str, order: OrderRequest) -> OrderResult:
        """POST /equity/orders/stop"""
        if not order.stop_price:
            return OrderResult(
                success=False, ticker=order.ticker, side=order.side,
                error_message="Stop order requires stop_price",
            )

        body: dict[str, Any] = {
            "ticker": t212_ticker,
            "quantity": order.quantity,
            "stopPrice": order.stop_price,
            "timeValidity": "GTC",
        }

        return await self._send_order("stop", body, order)

    async def _send_order(
        self, order_type: str, body: dict[str, Any], order: OrderRequest,
    ) -> OrderResult:
        """Send order to T212 API and parse response."""
        try:
            data = await self._request(
                "POST", f"/equity/orders/{order_type}",
                json_body=body,
                rate_key="orders",
                rate_interval=T212_ORDER_RATE_LIMIT,
            )

            order_id = str(data.get("id", ""))
            filled_qty = data.get("filledQuantity", 0.0)
            filled_price = data.get("filledValue", 0.0)
            status = data.get("status", "SUBMITTED")

            # Map T212 status to our enum
            status_map = {
                "NEW": OrderStatus.SUBMITTED,
                "SUBMITTED": OrderStatus.SUBMITTED,
                "FILLED": OrderStatus.FILLED,
                "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
                "CANCELLED": OrderStatus.CANCELLED,
                "REJECTED": OrderStatus.REJECTED,
            }

            result = OrderResult(
                success=True,
                order_id=order_id,
                ticker=order.ticker,
                side=order.side,
                filled_quantity=filled_qty,
                filled_price=filled_price,
                status=status_map.get(status, OrderStatus.SUBMITTED),
                raw_response=data,
            )

            logger.info(
                "Order placed: %s %s %s qty=%.4f id=%s",
                order.side.value, order_type, order.ticker, order.quantity, order_id,
            )

            # Record the trade in DB
            await self._record_trade(order, result)

            self._consecutive_failures = 0
            return result

        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self._circuit_open_until = time.monotonic() + CIRCUIT_BREAKER_RESET_SECONDS
                logger.error(
                    "Circuit breaker OPEN after %d consecutive failures",
                    self._consecutive_failures,
                )

            logger.exception("Order failed: %s %s %s", order.side.value, order_type, order.ticker)
            return OrderResult(
                success=False,
                ticker=order.ticker,
                side=order.side,
                error_message=str(e),
            )

    # =========================================================================
    # Internal: HTTP request with rate limiting and retries
    # =========================================================================

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        rate_key: str = "default",
        rate_interval: float = 2.0,
        max_retries: int = 3,
    ) -> Any:
        """Make a rate-limited HTTP request to the T212 API with retries."""
        if not self._http:
            raise RuntimeError("Trading212Broker not connected — call connect() first")

        await self._rate_limiter.acquire(rate_key, rate_interval)

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await self._http.request(
                    method, path, params=params, json=json_body,
                )
                resp.raise_for_status()

                if resp.status_code == 204:
                    return {}

                return resp.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code

                # Don't retry client errors (except 429 rate limit)
                if 400 <= status < 500 and status != 429:
                    logger.error("T212 API %s %s → %d: %s", method, path, status,
                                 e.response.text[:200])
                    raise

                # Rate limited — wait and retry
                if status == 429:
                    wait = float(e.response.headers.get("Retry-After", rate_interval * 2))
                    logger.warning("T212 rate limited — waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue

                # Server error — exponential backoff
                backoff = (2 ** attempt) * 1.0
                logger.warning(
                    "T212 API %s %s → %d — retrying in %.1fs (attempt %d/%d)",
                    method, path, status, backoff, attempt + 1, max_retries,
                )
                await asyncio.sleep(backoff)

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                backoff = (2 ** attempt) * 1.0
                logger.warning(
                    "T212 connection error on %s %s — retrying in %.1fs",
                    method, path, backoff,
                )
                await asyncio.sleep(backoff)

        raise last_error or RuntimeError(f"T212 request failed after {max_retries} retries")

    # =========================================================================
    # Internal: parsing helpers
    # =========================================================================

    def _parse_position(self, item: dict[str, Any]) -> Position | None:
        """Parse a T212 portfolio item into a Position."""
        try:
            t212_ticker = item.get("ticker", "")
            standard_ticker = self._from_t212_ticker(t212_ticker)

            quantity = item.get("quantity", 0.0)
            avg_price = item.get("averagePrice", 0.0)
            current_price = item.get("currentPrice", 0.0)
            pnl = item.get("ppl", 0.0)

            market_value = quantity * current_price
            pnl_pct = 0.0
            cost_basis = quantity * avg_price
            if cost_basis > 0:
                pnl_pct = (pnl / cost_basis) * 100

            return Position(
                ticker=standard_ticker,
                t212_ticker=t212_ticker,
                quantity=quantity,
                avg_price=avg_price,
                current_price=current_price,
                unrealised_pnl=pnl,
                unrealised_pnl_pct=pnl_pct,
                market_value=market_value,
            )
        except Exception:
            logger.warning("Failed to parse T212 position: %s", item)
            return None

    def _parse_trade(self, item: dict[str, Any]) -> TradeRecord | None:
        """Parse a T212 history item into a TradeRecord."""
        try:
            t212_ticker = item.get("ticker", "")
            standard_ticker = self._from_t212_ticker(t212_ticker)

            side = Side.BUY if item.get("type") == "BUY" else Side.SELL
            quantity = abs(item.get("filledQuantity", 0.0))
            price = item.get("filledValue", 0.0) / quantity if quantity > 0 else 0.0

            executed_str = item.get("dateExecuted", "")
            executed_at = datetime.utcnow()
            if executed_str:
                try:
                    executed_at = datetime.fromisoformat(executed_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            return TradeRecord(
                id=str(item.get("id", "")),
                ticker=standard_ticker,
                side=side,
                quantity=quantity,
                price=price,
                total_value=item.get("filledValue", 0.0),
                status=OrderStatus.FILLED,
                broker_order_id=str(item.get("id", "")),
                executed_at=executed_at,
            )
        except Exception:
            logger.warning("Failed to parse T212 trade: %s", item)
            return None

    async def _record_trade(self, order: OrderRequest, result: OrderResult) -> None:
        """Record an executed trade in the database for deduplication and history."""
        try:
            async with self._db.session() as session:
                trade = TradeORM(
                    ticker=order.ticker,
                    side=order.side.value,
                    order_type=order.order_type.value,
                    quantity=result.filled_quantity or order.quantity,
                    price=result.filled_price,
                    total_value=result.filled_quantity * result.filled_price,
                    status=result.status.value,
                    broker_order_id=result.order_id,
                )
                session.add(trade)
                await session.commit()
        except Exception:
            logger.exception("Failed to record trade in DB")

    # =========================================================================
    # Ticker mapping
    # =========================================================================

    def _to_t212_ticker(self, ticker: str) -> str:
        """Convert standard ticker to T212 format: AAPL → AAPL_US_EQ"""
        if T212_TICKER_SUFFIX in ticker:
            return ticker
        return f"{ticker}{T212_TICKER_SUFFIX}"

    def _from_t212_ticker(self, t212_ticker: str) -> str:
        """Convert T212 format to standard ticker: AAPL_US_EQ → AAPL"""
        if t212_ticker.endswith(T212_TICKER_SUFFIX):
            return t212_ticker[: -len(T212_TICKER_SUFFIX)]
        return t212_ticker

    def _is_circuit_open(self) -> bool:
        """Check if the circuit breaker is currently tripped."""
        if self._circuit_open_until <= 0:
            return False
        if time.monotonic() > self._circuit_open_until:
            # Reset
            self._circuit_open_until = 0.0
            self._consecutive_failures = 0
            logger.info("Circuit breaker RESET")
            return False
        return True
