"""
Shared screener execution engine.

Provides the core stock screening logic used by both:
  - The /api/screener REST endpoint (user-initiated screens)
  - The ScreenerAlertService (background periodic screens)

Uses yfinance's EquityQuery + screen() API for equities, and raw Yahoo
Finance POST for ETFs, indices, and crypto (since yfinance hardcodes
quoteType=EQUITY in its screen() function).
"""

from __future__ import annotations

import asyncio
import logging
from json import dumps
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for market data providers used by the screener engine."""

    async def get_history(
        self,
        ticker: str,
        period: str = "1y",
    ) -> list[dict] | None: ...


logger = logging.getLogger(__name__)

# Asset types that use EquityQuery via yfinance's screen()
_EQUITY_TYPES = {"", "EQUITY"}
# Asset types that require a direct POST with a custom quoteType
_DIRECT_POST_TYPES = {"ETF", "INDEX", "CRYPTOCURRENCY"}
# Default sort fields per asset type (Yahoo rejects intradaymarketcap for ETF/INDEX)
_SORT_FIELD_DEFAULTS = {
    "ETF": "fundnetassets",
    "MUTUALFUND": "fundnetassets",
    "INDEX": "intradayprice",
    "CRYPTOCURRENCY": "intradayprice",
}


class ScreenerResult(BaseModel):
    """Single result from a stock screen."""

    ticker: str
    name: str = ""
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    asset_type: str = ""
    currency: str = ""
    financial_currency: str = ""
    is_adr: bool = False
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
    cur = q.get("currency", "USD")
    fin_cur = q.get("financialCurrency", "")
    # ADR: trades in USD but reports financials in a foreign currency
    is_adr = bool(fin_cur and fin_cur != cur)
    return ScreenerResult(
        ticker=q.get("symbol", ""),
        name=q.get("shortName") or q.get("longName", ""),
        exchange=q.get("exchange", ""),
        sector=q.get("sector", ""),
        industry=q.get("industry", ""),
        asset_type=q.get("quoteType", ""),
        currency=cur,
        financial_currency=fin_cur,
        is_adr=is_adr,
        market_cap=q.get("marketCap"),
        price=q.get("regularMarketPrice"),
        volume=q.get("regularMarketVolume"),
        avg_volume=q.get("averageDailyVolume3Month"),
        pe_ratio=q.get("trailingPE"),
        dividend_yield=q.get("dividendYield"),
        change_pct=q.get("regularMarketChangePercent"),
    )


def _build_equity_operands(
    regions: list[str],
    exchanges: list[str],
    price_min: float,
    price_max: float,
    market_cap_min: float,
    market_cap_max: float,
    pe_min: float,
    pe_max: float,
    dividend_yield_min: float,
    sector: str,
) -> list:
    """Build EquityQuery operand list from filter params."""
    from yfinance import EquityQuery

    operands = []

    # Region filter — skip if exchanges are explicitly selected (exchange implies region)
    if not exchanges:
        if len(regions) == 1:
            operands.append(EquityQuery("eq", ["region", regions[0]]))
        elif len(regions) > 1:
            operands.append(EquityQuery("or", [EquityQuery("eq", ["region", r]) for r in regions]))
        else:
            operands.append(EquityQuery("eq", ["region", "us"]))

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

    # Exchange filter (multi-select)
    if exchanges:
        if len(exchanges) == 1:
            operands.append(EquityQuery("eq", ["exchange", exchanges[0]]))
        else:
            operands.append(
                EquityQuery("or", [EquityQuery("eq", ["exchange", e]) for e in exchanges])
            )

    # EquityQuery AND requires at least 2 operands
    if len(operands) < 2:
        operands.append(EquityQuery("gt", ["intradayprice", 0]))

    return operands


async def run_screen(
    *,
    price_min: float = 0,
    price_max: float = 0,
    market_cap_min: float = 0,
    market_cap_max: float = 0,
    pe_min: float = 0,
    pe_max: float = 0,
    dividend_yield_min: float = 0,
    region: str = "",
    sector: str = "",
    exchange: str = "",
    asset_type: str = "",
    sort_by: str = "intradaymarketcap",
    sort_asc: bool = False,
    offset: int = 0,
    limit: int = 100,
    yf: Any = None,
) -> tuple[list[ScreenerResult], int]:
    """
    Execute a stock screen query via yfinance.

    Runs the blocking yfinance/Yahoo screen call in a thread to avoid
    blocking the event loop.

    Args:
        price_min: Minimum price filter (0 = no minimum).
        price_max: Maximum price filter (0 = no limit).
        market_cap_min: Minimum market cap (0 = no minimum).
        market_cap_max: Maximum market cap (0 = no limit).
        pe_min: Minimum trailing P/E (0 = no minimum).
        pe_max: Maximum trailing P/E (0 = no limit).
        dividend_yield_min: Minimum dividend yield % (0 = no minimum).
        region: Comma-separated region codes (default: 'us').
        sector: Filter by sector name (empty = all).
        exchange: Comma-separated exchange codes (empty = all for the region).
        asset_type: EQUITY, ETF, MUTUALFUND, INDEX, CRYPTOCURRENCY (empty = EQUITY).
        sort_by: yfinance sort field name.
        sort_asc: Sort ascending if True.
        offset: Number of results to skip (for pagination).
        limit: Maximum results to return.
        yf: MarketDataProvider instance (unused by screen, kept for API compat).

    Returns:
        Tuple of (results list, total matching count from Yahoo).
    """
    regions = [r.strip() for r in region.split(",") if r.strip()] if region else []
    exchanges = [e.strip() for e in exchange.split(",") if e.strip()] if exchange else []
    at = (asset_type or "").upper()

    # Resolve sort field — Yahoo rejects intradaymarketcap for non-equity types
    effective_sort = sort_by
    if at in _SORT_FIELD_DEFAULTS and sort_by == "intradaymarketcap":
        effective_sort = _SORT_FIELD_DEFAULTS[at]

    def _screen() -> tuple[list[ScreenerResult], int]:
        try:
            if at == "MUTUALFUND":
                return _screen_funds(regions, sector, effective_sort, sort_asc, offset, limit)
            elif at in _DIRECT_POST_TYPES:
                return _screen_direct(
                    at,
                    regions,
                    exchanges,
                    price_min,
                    price_max,
                    market_cap_min,
                    market_cap_max,
                    pe_min,
                    pe_max,
                    dividend_yield_min,
                    sector,
                    effective_sort,
                    sort_asc,
                    offset,
                    limit,
                )
            else:
                return _screen_equity(
                    regions,
                    exchanges,
                    price_min,
                    price_max,
                    market_cap_min,
                    market_cap_max,
                    pe_min,
                    pe_max,
                    dividend_yield_min,
                    sector,
                    at,
                    effective_sort,
                    sort_asc,
                    offset,
                    limit,
                )
        except Exception:
            logger.exception("Screener query failed")
            return [], 0

    return await asyncio.to_thread(_screen)


def _screen_equity(
    regions,
    exchanges,
    price_min,
    price_max,
    market_cap_min,
    market_cap_max,
    pe_min,
    pe_max,
    dividend_yield_min,
    sector,
    asset_type,
    sort_by,
    sort_asc,
    offset,
    limit,
) -> tuple[list[ScreenerResult], int]:
    """Screen equities via yfinance's EquityQuery + screen()."""
    from yfinance import EquityQuery, screen

    operands = _build_equity_operands(
        regions,
        exchanges,
        price_min,
        price_max,
        market_cap_min,
        market_cap_max,
        pe_min,
        pe_max,
        dividend_yield_min,
        sector,
    )
    query = EquityQuery("and", operands)
    resp = screen(query, size=limit, offset=offset, sortField=sort_by, sortAsc=sort_asc)

    if not resp:
        return [], 0
    quotes = resp.get("quotes", [])
    total = resp.get("total", len(quotes))
    return [_quote_to_result(q) for q in quotes], total


def _screen_direct(
    quote_type,
    regions,
    exchanges,
    price_min,
    price_max,
    market_cap_min,
    market_cap_max,
    pe_min,
    pe_max,
    dividend_yield_min,
    sector,
    sort_by,
    sort_asc,
    offset,
    limit,
) -> tuple[list[ScreenerResult], int]:
    """Screen ETFs, indices, or crypto via direct Yahoo POST with custom quoteType."""
    from yfinance import EquityQuery
    from yfinance.const import _QUERY1_URL_
    from yfinance.data import YfData

    # Crypto doesn't use region — uses a simple price filter
    if quote_type == "CRYPTOCURRENCY":
        price_filter = price_min if price_min > 0 else 0.001
        operands = [EquityQuery("gt", ["intradayprice", price_filter])]
        if price_max > 0:
            operands.append(EquityQuery("lt", ["intradayprice", price_max]))
        if len(operands) < 2:
            operands.append(EquityQuery("gt", ["dayvolume", 0]))
        query = EquityQuery("and", operands)
    else:
        operands = _build_equity_operands(
            regions,
            exchanges,
            price_min,
            price_max,
            market_cap_min,
            market_cap_max,
            pe_min,
            pe_max,
            dividend_yield_min,
            sector,
        )
        query = EquityQuery("and", operands)

    body = {
        "offset": offset,
        "size": limit,
        "sortField": sort_by,
        "sortType": "ASC" if sort_asc else "DESC",
        "quoteType": quote_type,
        "query": query.to_dict(),
    }
    params = {
        "corsDomain": "finance.yahoo.com",
        "formatted": "false",
        "lang": "en-US",
        "region": "US",
    }

    data_client = YfData(session=None)
    url = f"{_QUERY1_URL_}/v1/finance/screener"
    resp = data_client.post(url, data=dumps(body, separators=(",", ":")), params=params)
    resp.raise_for_status()

    result = resp.json().get("finance", {}).get("result")
    if not result or not isinstance(result, list) or len(result) == 0:
        return [], 0

    data = result[0]
    quotes = data.get("quotes", [])
    total = data.get("total", len(quotes))
    return [_quote_to_result(q) for q in quotes], total


def _screen_funds(
    regions, sector, sort_by, sort_asc, offset, limit
) -> tuple[list[ScreenerResult], int]:
    """Screen mutual funds via yfinance's FundQuery."""
    from yfinance import FundQuery, screen

    # FundQuery uses region codes for its exchange field
    region_code = regions[0] if regions else "us"

    operands = [
        FundQuery("eq", ["exchange", region_code]),
        FundQuery("gt", ["initialinvestment", 0]),
    ]

    if sector:
        operands.append(FundQuery("eq", ["sector", sector]))

    query = FundQuery("and", operands)
    resp = screen(query, size=limit, offset=offset, sortField=sort_by, sortAsc=sort_asc)

    if not resp:
        return [], 0
    quotes = resp.get("quotes", [])
    total = resp.get("total", len(quotes))
    return [_quote_to_result(q) for q in quotes], total


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
        "1d": "5d",
        "5d": "1mo",
        "1w": "1mo",
        "1mo": "1mo",
        "3mo": "3mo",
        "1y": "1y",
    }
    yf_period = period_map.get(period, "1mo")

    # Day counts for return calculation
    day_counts = {
        "1d": 1,
        "5d": 5,
        "1w": 5,
        "1mo": 21,
        "3mo": 63,
        "1y": 252,
    }
    days = day_counts.get(period, 21)

    # Limit to first 100 to keep latency reasonable
    candidates = results[:100]
    if not candidates:
        return []

    # Fetch histories concurrently
    from stats.core import simple_pct_change

    async def _get_return(item: ScreenerResult) -> tuple[ScreenerResult, float | None]:
        try:
            hist = await yf.get_history(item.ticker, period=yf_period)
            if not hist or len(hist) <= days:
                return item, None
            closes = [h["close"] for h in hist if h.get("close") and h["close"] > 0]
            if len(closes) <= days:
                return item, None
            ret = simple_pct_change(closes[-1], closes[-(days + 1)])
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
        "region": str(filters.get("region") or ""),
        "sector": str(filters.get("sector") or ""),
        "exchange": str(filters.get("exchange") or ""),
        "asset_type": str(filters.get("asset_type") or ""),
    }
