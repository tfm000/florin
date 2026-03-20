"""
Abstract interface for market data providers.

Implementations: AlpacaProvider, PolygonProvider
All are interchangeable — swap by changing config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from core.models import BarData, StockInfo, StockQuote


class MarketDataProvider(ABC):
    """
    Interface for any market data source.
    
    Provides:
        - Real-time/near-real-time price snapshots
        - Streaming minute bars
        - Historical bar data
        - Instrument universe (all tradeable tickers)
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection (WebSocket, auth, etc.)."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connections."""
        ...

    @abstractmethod
    async def get_snapshot(self, tickers: list[str]) -> dict[str, StockQuote]:
        """
        Get current price snapshot for a list of tickers.
        Returns {ticker: StockQuote} dict.
        Missing tickers are omitted from the result.
        """
        ...

    @abstractmethod
    async def get_all_snapshots(self) -> dict[str, StockQuote]:
        """
        Get current price snapshot for ALL tickers (full market).
        Used for initial universe scanning.
        """
        ...

    @abstractmethod
    async def stream_bars(self, tickers: list[str]) -> AsyncIterator[BarData]:
        """
        Stream real-time minute bars for given tickers.
        Yields BarData objects as they arrive.
        Pass ["*"] for all tickers (if supported by provider).
        """
        ...

    @abstractmethod
    async def get_historical_bars(
        self,
        ticker: str,
        timeframe: str = "1Min",
        limit: int = 100,
    ) -> list[BarData]:
        """
        Get historical bar data for a single ticker.
        timeframe: "1Min", "5Min", "15Min", "1Hour", "1Day"
        """
        ...

    @abstractmethod
    async def get_instruments(self) -> list[StockInfo]:
        """
        Get list of all tradeable instruments with metadata.
        Used for building the penny stock universe.
        """
        ...

    async def __aenter__(self) -> MarketDataProvider:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()
