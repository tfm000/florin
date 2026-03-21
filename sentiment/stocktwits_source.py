"""
StockTwits sentiment source.

Fetches the message stream for a ticker from the StockTwits API.
Messages come pre-labelled as Bullish/Bearish — valuable gold-standard labels.

API: GET https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json
No auth required for basic access. Rate limit: 200 requests/hour.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from config.constants import STOCKTWITS_API_BASE
from core.models import StockTwitsMessage
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

MAX_MESSAGES = 30


class StockTwitsSource(SentimentSource):
    """
    Fetches StockTwits message stream for a given ticker.

    Returns bullish/bearish counts and individual messages with
    their pre-labelled sentiment (if the user tagged their post).
    """

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "StockTwits"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{STOCKTWITS_API_BASE}/streams/trending.json")
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch StockTwits stream for a ticker.

        Returns dict with keys: "messages", "bullish_count", "bearish_count"
        """
        try:
            messages = await self._fetch_stream(ticker)

            bullish = sum(1 for m in messages if m.sentiment == "Bullish")
            bearish = sum(1 for m in messages if m.sentiment == "Bearish")

            return {
                "messages": messages,
                "bullish_count": bullish,
                "bearish_count": bearish,
            }

        except Exception:
            logger.exception("StockTwits fetch failed for %s", ticker)
            return {"messages": [], "bullish_count": 0, "bearish_count": 0}

    async def _fetch_stream(self, ticker: str) -> list[StockTwitsMessage]:
        """Fetch the message stream for a single ticker."""
        url = f"{STOCKTWITS_API_BASE}/streams/symbol/{ticker}.json"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)

            if resp.status_code == 404:
                logger.debug("StockTwits: no stream for %s", ticker)
                return []

            if resp.status_code == 429:
                logger.warning("StockTwits rate limited")
                return []

            if resp.status_code == 403:
                logger.warning("StockTwits API blocked (403 Forbidden) — API may require auth now")
                return []

            resp.raise_for_status()
            data = resp.json()

        messages: list[StockTwitsMessage] = []
        for msg in data.get("messages", [])[:MAX_MESSAGES]:
            parsed = self._parse_message(msg)
            if parsed:
                messages.append(parsed)

        return messages

    def _parse_message(self, msg: dict[str, Any]) -> StockTwitsMessage | None:
        """Parse a single StockTwits message."""
        try:
            sentiment = None
            entities = msg.get("entities", {})
            if entities and entities.get("sentiment"):
                sentiment = entities["sentiment"].get("basic")

            created_str = msg.get("created_at", "")
            created_at = datetime.now(UTC)
            if created_str:
                try:
                    created_at = datetime.fromisoformat(
                        created_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            return StockTwitsMessage(
                text=msg.get("body", ""),
                sentiment=sentiment,
                likes=msg.get("likes", {}).get("total", 0) if isinstance(msg.get("likes"), dict) else 0,
                created_at=created_at,
            )
        except Exception:
            return None
