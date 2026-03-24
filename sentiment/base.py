"""
Abstract interface for sentiment data sources.

Implementations: RedditSource, StockTwitsSource, SECEdgarSource, NewsSource, WebSearchSource
All are independent and can fail without affecting others.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SentimentSource(ABC):
    """
    Interface for any source of sentiment or fundamental data.
    
    Each source is queried independently. Failures are handled
    gracefully by the aggregator — partial data is acceptable.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this source (e.g., 'Reddit', 'StockTwits')."""
        ...

    @abstractmethod
    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch sentiment data for a given ticker.
        
        Args:
            ticker: Stock symbol (e.g., "AAPL")
            company_name: Optional company name for broader search
            
        Returns:
            Dict of source-specific data. Keys depend on implementation.
            The aggregator knows how to merge these into SentimentData.
            
        Raises:
            Should NOT raise — return empty dict on failure and log the error.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this source is available and responding."""
        ...
