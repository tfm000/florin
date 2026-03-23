"""
Shared screener execution engine.

Provides the core stock screening logic used by both:
  - The /api/screener REST endpoint (user-initiated screens)
  - The ScreenerAlertService (background periodic screens)

Uses yfinance's EquityQuery + screen() API for server-side filtering,
with optional momentum post-filtering via historical price data.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for market data providers used by the screener engine."""

    async def get_history(
        self, ticker: str, period: str = "1y",
    ) -> list[dict] | None: ...

logger = logging.getLogger(__name__)


class ScreenerResult(BaseModel):
    """Single result from a stock screen."""
    ticker: str
    name: str = ""
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float | None = None
    price: float | None = None
    volume: int | None = None
    avg_volume: int | None = None
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    change_pct: float | None = None


class ScreenerResponse(BaseModel):
    """Wrapper response for screener results."""
    total: int
    results: list[ScreenerResult]


def _quote_to_result(q: dict) -> ScreenerResult:
    """Convert a yfinance screen quote dict to a ScreenerResult."""
    return ScreenerResult(
        ticker=q.get("symbol", ""),
        name=q.get("shortName") or q.get("longName", ""),
        exchange=q.get("exchange", ""),
        sector=q.get("sector", ""),
        industry=q.get("industry", ""),
        market_cap=q.get("marketCap"),
        price=q.get("regularMarketPrice"),
        volume=q.get("regularMarketVolume"),
        avg_volume=q.get("averageDailyVolume3Month"),
        pe_ratio=q.get("trailingPE"),
        dividend_yield=q.get("dividendYield"),
        change_pct=q.get("regularMarketChangePercent"),
    )


async def run_screen(
    *,
    price_min: float = 0,
    price_max: float = 0,
    market_cap_min: float = 0,
    market_cap_max: float = 0,
    pe_min: float = 0,
    pe_max: float = 0,
    dividend_yield_min: float = 0,
    region: str = "us",
    sector: str = "",
    exchange: str = "",
    asset_type: str = "",
    sort_by: str = "intradaymarketcap",
    sort_asc: bool = False,
    limit: int = 100,
    yf: Any = None,
) -> list[ScreenerResult]:
    """
    Execute a stock screen query via yfinance.

    Runs the blocking yfinance screen() call in a thread to avoid
    blocking the event loop.

    Args:
        price_min: Minimum price filter (0 = no minimum).
        price_max: Maximum price filter (0 = no limit).
        market_cap_min: Minimum market cap (0 = no minimum).
        market_cap_max: Maximum market cap (0 = no limit).
        pe_min: Minimum trailing P/E (0 = no minimum).
        pe_max: Maximum trailing P/E (0 = no limit).
        dividend_yield_min: Minimum dividend yield % (0 = no minimum).
        region: Region code for market (default: 'us'). Supports: us, gb, de, jp, ca, hk, etc.
        sector: Filter by sector name (empty = all).
        exchange: Comma-separated exchange codes (empty = all for the region).
        asset_type: Filter by quoteType: EQUITY, ETF, INDEX, etc. (empty = all).
        sort_by: yfinance sort field name.
        sort_asc: Sort ascending if True.
        limit: Maximum results to return.
        yf: YFinanceProvider instance (unused by screen, but kept for API compat).

    Returns:
        List of ScreenerResult matching the criteria.
    """

    def _screen() -> list[ScreenerResult]:
        try:
            from yfinance import EquityQuery, screen

            # Mutual funds use a separate FundQuery — handle separately
            if asset_type == "MUTUALFUND":
                return _screen_funds()

            operands = [
                EquityQuery("eq", ["region", region or "us"]),
            ]

            if price_min > 0:
                operands.append(EquityQuery("gt", ["intradayprice", price_min]))
            if price_max > 0:
                operands.append(EquityQuery("lt", ["intradayprice", price_max]))
            if market_cap_min > 0:
                operands.append(EquityQuery("gt", ["intradaymarketcap", market_cap_min]))
            if market_cap_max > 0:
                operands.append(EquityQuery("lt", ["intradaymarketcap", market_cap_max]))
            if pe_min > 0:
                operands.append(EquityQuery("gt", ["trailingpe", pe_min]))
            if pe_max > 0:
                operands.append(EquityQuery("lt", ["trailingpe", pe_max]))
            if dividend_yield_min > 0:
                operands.append(EquityQuery("gt", ["dividendyield", dividend_yield_min / 100]))
            if sector:
                operands.append(EquityQuery("eq", ["sector", sector]))

            # Exchange filter
            if exchange:
                exchanges = [e.strip() for e in exchange.split(",")]
                if len(exchanges) == 1:
                    operands.append(EquityQuery("eq", ["exchange", exchanges[0]]))
                else:
                    operands.append(EquityQuery("or", [
                        EquityQuery("eq", ["exchange", e]) for e in exchanges
                    ]))

            if len(operands) < 2:
                operands.append(EquityQuery("gt", ["intradayprice", 0]))
            query = EquityQuery("and", operands)
            resp = screen(query, size=limit, offset=0,
                          sortField=sort_by, sortAsc=sort_asc)

            quotes = resp.get("quotes", []) if resp else []

            results = []
            for q in quotes:
                # Apply asset type filter (post-screen, yfinance doesn't support quoteType in EquityQuery)
                if asset_type:
                    qt = q.get("quoteType", "EQUITY")
                    if qt.upper() != asset_type.upper():
                        continue

                results.append(_quote_to_result(q))

            return results

        except Exception:
            logger.exception("Screener query failed")
            return []

    def _screen_funds() -> list[ScreenerResult]:
        """Screen mutual funds via yfinance's FundQuery."""
        try:
            from yfinance import FundQuery, screen

            operands = [
                FundQuery("eq", ["exchange", region or "us"]),
                FundQuery("gt", ["initialinvestment", 0]),  # FundQuery AND requires 2+ operands
            ]

            if sector:
                operands.append(FundQuery("eq", ["sector", sector]))

            query = FundQuery("and", operands)
            resp = screen(query, size=limit, offset=0,
                          sortField=sort_by, sortAsc=sort_asc)

            quotes = resp.get("quotes", []) if resp else []
            return [_quote_to_result(q) for q in quotes]

        except Exception:
            logger.exception("Fund screener query failed")
            return []

    return await asyncio.to_thread(_screen)


async def apply_momentum_filter(
    results: list[ScreenerResult],
    momentum_min: float | None,
    momentum_max: float | None,
    period: str,
    yf: MarketDataProvider,
) -> list[ScreenerResult]:
    """
    Post-filter screener results by return momentum over a given period.

    Fetches historical data for the first 100 results to limit latency,
    then filters to those within [momentum_min, momentum_max].

    Args:
        results: Pre-filtered screener results.
        momentum_min: Minimum return % (None = no minimum).
        momentum_max: Maximum return % (None = no limit).
        period: One of: 1d, 5d, 1w, 1mo, 3mo, 1y.
        yf: Market data provider for fetching history.

    Returns:
        Filtered list of results within momentum bounds.
    """
    # Map period labels to yfinance format
    period_map = {
        "1d": "5d", "5d": "1mo", "1w": "1mo",
        "1mo": "1mo", "3mo": "3mo", "1y": "1y",
    }
    yf_period = period_map.get(period, "1mo")

    # Day counts for return calculation
    day_counts = {
        "1d": 1, "5d": 5, "1w": 5,
        "1mo": 21, "3mo": 63, "1y": 252,
    }
    days = day_counts.get(period, 21)

    # Limit to first 100 to keep latency reasonable
    candidates = results[:100]
    if not candidates:
        return []

    # Fetch histories concurrently
    async def _get_return(item: ScreenerResult) -> tuple[ScreenerResult, float | None]:
        try:
            hist = await yf.get_history(item.ticker, period=yf_period)
            if not hist or len(hist) <= days:
                return item, None
            closes = [h["close"] for h in hist if h.get("close") and h["close"] > 0]
            if len(closes) <= days:
                return item, None
            ret = (closes[-1] / closes[-(days + 1)] - 1) * 100
            return item, ret
        except Exception:
            logger.debug("Momentum fetch failed for %s", item.ticker, exc_info=True)
            return item, None

    pairs = await asyncio.gather(*[_get_return(r) for r in candidates])

    filtered = []
    for item, ret in pairs:
        if ret is None:
            continue
        if momentum_min is not None and ret < momentum_min:
            continue
        if momentum_max is not None and ret > momentum_max:
            continue
        filtered.append(item)

    return filtered


def parse_filters_to_kwargs(filters: dict) -> dict:
    """
    Convert a saved screener's filters dict into keyword arguments
    suitable for run_screen().

    Args:
        filters: The filters_json dict from SavedScreenerORM.

    Returns:
        Dict of keyword arguments for run_screen().
    """
    return {
        "price_min": float(filters.get("price_min") or 0),
        "price_max": float(filters.get("price_max") or 0),
        "market_cap_min": float(filters.get("market_cap_min") or 0),
        "market_cap_max": float(filters.get("market_cap_max") or 0),
        "pe_min": float(filters.get("pe_min") or 0),
        "pe_max": float(filters.get("pe_max") or 0),
        "dividend_yield_min": float(filters.get("dividend_yield_min") or 0),
        "region": str(filters.get("region") or "us"),
        "sector": str(filters.get("sector") or ""),
        "exchange": str(filters.get("exchange") or ""),
        "asset_type": str(filters.get("asset_type") or ""),
    }
