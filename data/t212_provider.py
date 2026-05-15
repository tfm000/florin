"""
Trading 212 instrument metadata provider.

T212 API does NOT provide market prices — only account/position/order data.
This module fetches the instrument list for ticker format mapping
(standard ticker → T212 format like AAPL_US_EQ).

Used by the universe manager to enrich stocks with T212 ticker mappings.
"""

from __future__ import annotations

import logging

import httpx

from config.constants import SUPPORTED_EXCHANGES
from config.settings import Settings
from core.models import StockInfo
from core.rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)


class T212InstrumentProvider:
    """
    Fetches tradeable instruments from the Trading 212 API.

    Endpoint: GET /api/v0/equity/metadata/instruments
    Rate limit: 1 request / 5 seconds

    This is used at startup to build a mapping of standard tickers
    to T212 internal format, and to verify which stocks are actually
    tradeable on T212.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http: httpx.AsyncClient | None = None
        self._limiter = AsyncRateLimiter(1, 5, name="T212")

    async def connect(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=self._settings.t212_base_url,
            headers={"Authorization": self._settings.t212_api_key},
            timeout=30.0,
        )

    async def disconnect(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def get_instruments(self) -> list[StockInfo]:
        """
        Fetch all tradeable instruments from T212.

        Returns StockInfo objects with t212_ticker populated.
        Only includes US equity instruments on supported exchanges.
        """
        if not self._http:
            raise RuntimeError("T212 provider not connected — call connect() first")

        if not self._settings.t212_configured:
            logger.warning("T212 API not configured — skipping instrument fetch")
            return []

        try:
            await self._limiter.acquire()
            resp = await self._http.get("/equity/metadata/instruments")
            resp.raise_for_status()
            data = resp.json()

            instruments = []
            for item in data:
                exchange = item.get("exchangeId", "")
                if exchange not in SUPPORTED_EXCHANGES:
                    continue

                # T212 ticker format: e.g., "AAPL_US_EQ"
                t212_ticker = item.get("ticker", "")
                # Extract standard ticker from T212 format
                # T212 format is usually SYMBOL_EXCHANGE_TYPE
                parts = t212_ticker.split("_")
                standard_ticker = parts[0] if parts else t212_ticker

                instruments.append(
                    StockInfo(
                        ticker=standard_ticker,
                        name=item.get("name", ""),
                        exchange=exchange,
                        t212_ticker=t212_ticker,
                        sector=item.get("sector", "") or "",
                        industry=item.get("industry", "") or "",
                    )
                )

            logger.info("T212: fetched %d US equity instruments", len(instruments))
            return instruments

        except httpx.HTTPStatusError as e:
            logger.error("T212 instrument fetch failed: %s", e)
        except Exception:
            logger.exception("Unexpected error fetching T212 instruments")

        return []

    async def get_t212_ticker_map(self) -> dict[str, str]:
        """
        Build a mapping of standard tickers to T212 format.

        Returns: {"AAPL": "AAPL_US_EQ", "TSLA": "TSLA_US_EQ", ...}
        """
        instruments = await self.get_instruments()
        return {s.ticker: s.t212_ticker for s in instruments if s.t212_ticker}

    async def __aenter__(self) -> T212InstrumentProvider:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()
