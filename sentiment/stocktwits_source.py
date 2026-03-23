"""
StockTwits sentiment source.

Fetches the message stream for a ticker from the StockTwits API.
Messages come pre-labelled as Bullish/Bearish — valuable gold-standard labels.

API: GET https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json
Rate limit: 200 requests/hour.

Note: The StockTwits API may require authentication or return 403/401
if access policies change. This source handles all error states
gracefully and will never crash the sentiment aggregator.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from config.constants import STOCKTWITS_API_BASE
from core.models import StockTwitsMessage
from core.rate_limiter import AsyncRateLimiter
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

MAX_MESSAGES = 30


class StockTwitsSource(SentimentSource):
    """
    Fetches StockTwits message stream for a given ticker.

    Returns bullish/bearish counts and individual messages with
    their pre-labelled sentiment (if the user tagged their post).

    Supports optional access_token for authenticated requests.
    If the API returns 403 or 401, logs a clear warning and returns
    empty data without crashing.
    """

    def __init__(self, access_token: str = "") -> None:
        self._limiter = AsyncRateLimiter(200, 3600, name="StockTwits")
        self._access_token = access_token
        self._api_unavailable = False  # Sticky flag to avoid spamming logs

    @property
    def name(self) -> str:
        return "StockTwits"

    async def health_check(self) -> bool:
        """Check if the StockTwits API is reachable.

        Returns:
            True if the trending endpoint responds with 200.
        """
        if self._api_unavailable:
            return False
        try:
            params = self._auth_params()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{STOCKTWITS_API_BASE}/streams/trending.json",
                    params=params,
                )
                if resp.status_code in (401, 403):
                    self._mark_unavailable(resp.status_code)
                    return False
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch StockTwits stream for a ticker.

        Args:
            ticker: Stock symbol (e.g., "AAPL").
            company_name: Unused; present for interface conformance.

        Returns:
            Dict with keys: "messages", "bullish_count", "bearish_count".
            Returns zeroed data on any error.
        """
        empty_result: dict[str, Any] = {
            "messages": [], "bullish_count": 0, "bearish_count": 0,
        }

        if self._api_unavailable:
            logger.debug(
                "StockTwits: skipping fetch for %s — API marked unavailable", ticker,
            )
            return empty_result

        try:
            messages = await self._fetch_stream(ticker)

            bullish = sum(1 for m in messages if m.sentiment == "Bullish")
            bearish = sum(1 for m in messages if m.sentiment == "Bearish")

            return {
                "messages": messages,
                "bullish_count": bullish,
                "bearish_count": bearish,
            }

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "StockTwits fetch failed for %s: HTTP %d — %s",
                ticker, exc.response.status_code, exc.response.text[:200],
            )
            return empty_result
        except httpx.TimeoutException:
            logger.warning("StockTwits: request timed out for %s", ticker)
            return empty_result
        except httpx.HTTPError as exc:
            logger.warning("StockTwits: HTTP error for %s: %s", ticker, exc)
            return empty_result
        except Exception:
            logger.exception("StockTwits fetch failed unexpectedly for %s", ticker)
            return empty_result

    async def _fetch_stream(self, ticker: str) -> list[StockTwitsMessage]:
        """Fetch the message stream for a single ticker.

        Args:
            ticker: Stock symbol.

        Returns:
            List of parsed StockTwitsMessage objects.
        """
        url = f"{STOCKTWITS_API_BASE}/streams/symbol/{ticker}.json"
        params = self._auth_params()

        await self._limiter.acquire()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)

            if resp.status_code == 404:
                logger.debug("StockTwits: no stream for %s", ticker)
                return []

            if resp.status_code == 429:
                logger.warning("StockTwits: rate limited (429) for %s", ticker)
                return []

            if resp.status_code in (401, 403):
                self._mark_unavailable(resp.status_code)
                return []

            if resp.status_code != 200:
                logger.warning(
                    "StockTwits: unexpected HTTP %d for %s — body: %s",
                    resp.status_code, ticker, resp.text[:300],
                )
                return []

            # Validate response body
            try:
                data = resp.json()
            except Exception:
                logger.warning(
                    "StockTwits: invalid JSON response for %s", ticker,
                )
                return []

            if not isinstance(data, dict):
                logger.warning(
                    "StockTwits: response is not a JSON object for %s", ticker,
                )
                return []

        raw_messages = data.get("messages")
        if not isinstance(raw_messages, list):
            logger.debug("StockTwits: no messages array in response for %s", ticker)
            return []

        messages: list[StockTwitsMessage] = []
        for msg in raw_messages[:MAX_MESSAGES]:
            parsed = self._parse_message(msg)
            if parsed:
                messages.append(parsed)

        return messages

    def _parse_message(self, msg: dict[str, Any]) -> StockTwitsMessage | None:
        """Parse a single StockTwits message.

        Args:
            msg: Raw message dict from the StockTwits API.

        Returns:
            Parsed StockTwitsMessage, or None if parsing fails.
        """
        try:
            sentiment = None
            entities = msg.get("entities", {})
            if isinstance(entities, dict) and entities.get("sentiment"):
                sentiment_data = entities["sentiment"]
                if isinstance(sentiment_data, dict):
                    sentiment = sentiment_data.get("basic")

            created_str = msg.get("created_at", "")
            created_at = datetime.now(UTC)
            if created_str:
                try:
                    created_at = datetime.fromisoformat(
                        created_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            likes_raw = msg.get("likes")
            likes = 0
            if isinstance(likes_raw, dict):
                likes = likes_raw.get("total", 0)
            elif isinstance(likes_raw, int):
                likes = likes_raw

            return StockTwitsMessage(
                text=msg.get("body", ""),
                sentiment=sentiment,
                likes=likes,
                created_at=created_at,
            )
        except Exception:
            logger.debug("StockTwits: failed to parse message: %s", msg)
            return None

    def _auth_params(self) -> dict[str, str]:
        """Build query parameters, including access token if configured.

        Returns:
            Dict of query parameters for StockTwits API requests.
        """
        params: dict[str, str] = {}
        if self._access_token:
            params["access_token"] = self._access_token
        return params

    def _mark_unavailable(self, status_code: int) -> None:
        """Mark the API as unavailable after auth failures.

        Sets a sticky flag so subsequent requests skip the API call
        and logs a clear warning about the issue.

        Args:
            status_code: The HTTP status code that triggered unavailability.
        """
        if not self._api_unavailable:
            self._api_unavailable = True
            if status_code == 401:
                logger.warning(
                    "StockTwits API returned 401 Unauthorized — "
                    "access token may be required or invalid. "
                    "Set 'stocktwits_access_token' in settings if you have one. "
                    "StockTwits source will be disabled for this session."
                )
            elif status_code == 403:
                logger.warning(
                    "StockTwits API returned 403 Forbidden — "
                    "the API may have been deprecated or requires authentication. "
                    "StockTwits source will be disabled for this session."
                )
            else:
                logger.warning(
                    "StockTwits API returned %d — marking as unavailable "
                    "for this session.", status_code,
                )
