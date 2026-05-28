"""
Yahoo Finance data provider via yfinance.

Powers research, enrichment, and stock screening.
All yfinance calls are synchronous — wrapped in asyncio.to_thread().
Results are cached with TTL to reduce API load.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import UTC
from typing import Any

import yfinance as yf

from core.models import StockInfo

logger = logging.getLogger(__name__)

# TTL cache implementation — market-aware.
# During market hours: use short TTLs for fresh data.
# When market is closed: cache until next market open (data won't change).
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_MAX_SIZE = 5000  # Evict oldest entries when cache exceeds this size

# TTLs used during market hours (seconds)
INFO_TTL = 3600  # 1 hour (asset info — sector/PE/beta change slowly)
MACRO_TTL = 60  # 1 minute (indices, commodities, crypto, FX)
HISTORY_TTL = 3600  # 1 hour (daily OHLCV doesn't change intraday)
SEARCH_TTL = 300  # 5 minutes
OPTION_CHAIN_TTL = 1800  # 30 minutes — option chains move with the
# underlying, so a stale chain is acceptable for ~half-hour windows
# but not full-hour ones. Used by ``get_option_chain_raw``.

# yfinance returns a tiny sentinel implied-volatility (~2e-5) for strikes where IV
# is undefined (e.g. deep ITM). Treat anything at or below this as "no IV".
SENTINEL_IV = 0.00002

# Page size for the yfinance equity screener pagination loop.
_SCREEN_PAGE_SIZE = 250


def _safe_int(v: Any, default: int = 0) -> int:
    """Coerce a yfinance cell to int, treating NaN and None as the default.

    yfinance can return ``float('nan')`` for missing ``volume`` /
    ``openInterest`` instead of ``None``. ``NaN`` is *truthy* in Python so
    a naive ``int(v or 0)`` lets the NaN through and crashes
    ``int(NaN)``. Centralise the guard here so every yfinance →
    JSON-shape coercion uses the same rule.
    """
    if v is None:
        return int(default)
    if isinstance(v, float) and math.isnan(v):
        return int(default)
    return int(v)


def _safe_float_or_none(v: Any) -> float | None:
    """Coerce a yfinance cell to float, mapping NaN/None to ``None``.

    Counterpart to :func:`_safe_int` for fields where "missing" is
    semantically distinct from zero (e.g. ``lastPrice``, ``bid``,
    ``ask``).
    """
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return float(v)


def _normalize_dividend_yield(raw: float | None) -> float | None:
    """Normalize dividend yield to decimal form (0.032 = 3.2%).

    yfinance usually returns decimals but some tickers return percentages.
    """
    if raw is None:
        return None
    if raw > 1.0:
        return raw / 100
    if raw < 0:
        return None
    return raw


def _normalize_pe(pe: float | None, eps: float | None) -> float | None:
    """Sanitize P/E ratio from yfinance using the underlying EPS.

    Returns None for values that are economically meaningless:
    - Negative PE (company has negative earnings — ratio is not interpretable).
    - Near-zero EPS (|EPS| < $0.05) — dividing price by ~0 produces noise, not signal.
    """
    if pe is None:
        return None
    if pe <= 0:
        return None
    if eps is not None and abs(eps) < 0.05:
        return None
    return pe


def _effective_ttl(ttl: float) -> float:
    """Return the TTL to use: short during market hours, until next open otherwise."""
    from core.market_hours import is_market_open, next_market_open

    if is_market_open():
        return ttl
    # Market closed — cache until next open
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    seconds_until_open = (next_market_open(now) - now).total_seconds()
    return max(seconds_until_open, ttl)


def _get_cached(key: str, ttl: float, market_aware: bool = True) -> Any | None:
    """Return cached value if still valid, else None.

    market_aware=True: extend TTL until next market open when market is closed.
    market_aware=False: always use the raw TTL (for 24/7 assets like crypto/FX/rates).
    """
    if key in _cache:
        ts, val = _cache[key]
        effective = _effective_ttl(ttl) if market_aware else ttl
        if time.time() - ts < effective:
            return val
        del _cache[key]
    return None


def _set_cached(key: str, val: Any) -> None:
    _cache[key] = (time.time(), val)
    # Evict oldest entries if cache exceeds max size
    if len(_cache) > _CACHE_MAX_SIZE:
        sorted_keys = sorted(_cache, key=lambda k: _cache[k][0])
        for k in sorted_keys[: len(_cache) - _CACHE_MAX_SIZE]:
            del _cache[k]


# Periods that can be served from cached 5y data (subset of 5 years)
_SLICEABLE_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "3y", "5y"}

# Map yfinance period strings to approximate day counts for date slicing
_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 31,
    "3mo": 93,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
    "3y": 1095,
    "5y": 1827,
}


def _period_cutoff(period: str) -> str | None:
    """Return the ISO date string N days ago for a given period, or None if unknown."""
    from datetime import date, timedelta

    days = _PERIOD_DAYS.get(period)
    if days is None:
        return None
    return (date.today() - timedelta(days=days)).isoformat()


def _slice_history(records: list[dict], start: str = "", end: str = "") -> list[dict]:
    """Filter history records to [start, end] by date prefix (YYYY-MM-DD)."""
    if not records:
        return records
    result = records
    if start:
        result = [r for r in result if r["date"][:10] >= start]
    if end:
        result = [r for r in result if r["date"][:10] <= end]
    return result


def _try_get_wide_cache(ticker: str, interval: str) -> list[dict] | None:
    """Try to find cached max or 5y data for a ticker. Returns records or None."""
    for wide_period in ("max", "5y"):
        key = f"history:{ticker}:{wide_period}::{interval}"
        cached = _get_cached(key, HISTORY_TTL)
        if cached is not None:
            return cached
    return None


class YFinanceProvider:
    """Asset data via Yahoo Finance."""

    # Semaphore for throttling concurrent per-ticker calls (e.g. get_info).
    _info_semaphore = asyncio.Semaphore(10)

    def __init__(self, policy_rate_fetcher=None):
        self._policy_rate_fetcher = policy_rate_fetcher

    async def get_histories_batch(
        self,
        tickers: list[str],
        period: str = "1y",
        interval: str = "1d",
        start: str = "",
        end: str = "",
        chunk_size: int = 500,
    ) -> dict[str, list[dict]]:
        """Batch-fetch price histories using yf.download() (single HTTP request per chunk).

        Fetches 5y of data and caches it, then slices to the requested period.
        Subsequent requests for any period <= 5y are served from cache without
        new API calls. If ``max`` is requested, it is fetched and cached separately
        and supersedes 5y for future lookups.

        Returns a dict mapping ticker -> list of OHLCV dicts, same format as get_history().
        Populates the per-ticker cache so subsequent get_history() calls benefit.

        Args:
            tickers: List of ticker symbols.
            period: yfinance period string (e.g. "1y", "6m", "max").
            interval: Bar interval (default "1d").
            start: ISO date string for custom range start.
            end: ISO date string for custom range end.
            chunk_size: Max tickers per yf.download() call (default 500).
        """
        if not tickers:
            return {}

        # Determine if we can use the 5y-fetch-and-slice strategy
        cutoff_5y = _period_cutoff("5y")
        can_slice = interval == "1d" and (
            (not start and not end and period in _SLICEABLE_PERIODS)
            or (start and end and cutoff_5y and start >= cutoff_5y)
        )

        # Compute the slice bounds
        if can_slice:
            if start and end:
                slice_start, slice_end = start, end
            else:
                slice_start = _period_cutoff(period) or ""
                slice_end = ""
            fetch_period = "5y"
        elif period == "max":
            fetch_period = "max"
            slice_start, slice_end = start, end
        else:
            # Non-daily interval or custom range outside 5y — fetch as-is
            fetch_period = period
            slice_start, slice_end = start, end

        result: dict[str, list[dict]] = {}

        # Process in chunks
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]

            uncached: list[str] = []
            for t in chunk:
                # Try wide cache (max → 5y) first, then exact match
                wide = _try_get_wide_cache(t, interval)
                if wide is not None:
                    result[t] = _slice_history(wide, slice_start, slice_end)
                    continue

                # Check exact cache key
                ck = f"history:{t}:{start or period}:{end}:{interval}"
                cached = _get_cached(ck, HISTORY_TTL)
                if cached is not None:
                    result[t] = cached
                    continue

                uncached.append(t)

            if not uncached:
                continue

            # Download the wide period (5y or max) for cache benefit
            if can_slice or period == "max":
                chunk_result = await asyncio.to_thread(
                    self._download_chunk,
                    uncached,
                    fetch_period,
                    interval,
                    "",
                    "",
                )
            else:
                chunk_result = await asyncio.to_thread(
                    self._download_chunk,
                    uncached,
                    period,
                    interval,
                    start,
                    end,
                )

            # Cache wide data and slice for result
            for t in uncached:
                records = chunk_result.get(t, [])
                if can_slice or period == "max":
                    # Cache the wide (5y or max) data
                    _set_cached(f"history:{t}:{fetch_period}::{interval}", records)
                    # Slice to requested range for the return value
                    result[t] = _slice_history(records, slice_start, slice_end)
                else:
                    ck = f"history:{t}:{start or period}:{end}:{interval}"
                    _set_cached(ck, records)
                    result[t] = records

        return result

    @staticmethod
    def _download_chunk(
        tickers: list[str],
        period: str,
        interval: str,
        start: str,
        end: str,
    ) -> dict[str, list[dict]]:
        """Synchronous yf.download() for a chunk of tickers.

        Handles both single-ticker (flat columns) and multi-ticker (MultiIndex) DataFrames.
        """
        import pandas as pd

        try:
            kwargs: dict[str, Any] = {
                "tickers": tickers,
                "interval": interval,
                "auto_adjust": True,
                "progress": False,
                "threads": True,
            }
            if start and end:
                kwargs["start"] = start
                kwargs["end"] = end
            else:
                kwargs["period"] = period

            df = yf.download(**kwargs)

            if df is None or df.empty:
                logger.warning("yf.download returned empty for %d tickers", len(tickers))
                return {t: [] for t in tickers}

            result: dict[str, list[dict]] = {}

            if isinstance(df.columns, pd.MultiIndex):
                # Multi-ticker: columns are (Price, Ticker)
                available_tickers = df.columns.get_level_values("Ticker").unique().tolist()
                for t in tickers:
                    if t not in available_tickers:
                        logger.debug("yf.download: no data for %s (delisted/invalid)", t)
                        result[t] = []
                        continue
                    sub = df.xs(t, level="Ticker", axis=1)
                    result[t] = YFinanceProvider._df_to_records(sub)
            else:
                # Single ticker: flat columns
                t = tickers[0]
                result[t] = YFinanceProvider._df_to_records(df)

            # Ensure all requested tickers have an entry
            for t in tickers:
                if t not in result:
                    result[t] = []

            return result

        except TypeError as e:
            if "tz-naive" in str(e) and len(tickers) > 1:
                # yfinance bug: mixed tz-aware/tz-naive DatetimeIndex in batch.
                # Fall back to individual downloads.
                logger.warning(
                    "Batch download hit tz mismatch for %d tickers, falling back "
                    "to individual downloads",
                    len(tickers),
                )
                result = {}
                for t in tickers:
                    try:
                        single_kwargs = {**kwargs, "tickers": [t]}
                        single_df = yf.download(**single_kwargs)
                        if single_df is not None and not single_df.empty:
                            # Single ticker returns flat columns
                            if isinstance(single_df.columns, pd.MultiIndex):
                                single_df = single_df.xs(t, level="Ticker", axis=1)
                            result[t] = YFinanceProvider._df_to_records(single_df)
                        else:
                            result[t] = []
                    except Exception:
                        result[t] = []
                return result
            logger.exception("yf.download failed for %d tickers", len(tickers))
            return {t: [] for t in tickers}
        except Exception:
            logger.exception("yf.download failed for %d tickers", len(tickers))
            return {t: [] for t in tickers}

    @staticmethod
    def _df_to_records(df) -> list[dict]:
        """Convert a single-ticker OHLCV DataFrame to list of dicts."""
        records = []
        for idx, row in df.iterrows():
            close = row.get("Close")
            if close is None or (isinstance(close, float) and math.isnan(close)):
                # Skip NaN rows (delisted periods)
                continue
            records.append(
                {
                    "date": str(idx),
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(close),
                    "volume": int(row.get("Volume", 0)),
                }
            )
        return records

    async def get_info_batch(
        self,
        tickers: list[str],
        max_concurrent: int = 10,
    ) -> dict[str, dict]:
        """Fetch info for multiple tickers with concurrency throttling.

        Uses a semaphore to limit concurrent yfinance calls.

        Args:
            tickers: Ticker symbols to enrich.
            max_concurrent: Max concurrent get_info() calls (default 10).

        Returns:
            Dict mapping ticker -> info dict.
        """
        if not tickers:
            return {}

        sem = asyncio.Semaphore(max_concurrent)

        async def _throttled_info(t: str) -> tuple[str, dict]:
            async with sem:
                info = await self.get_info(t)
                return t, info

        results = await asyncio.gather(*[_throttled_info(t) for t in tickers])
        return dict(results)

    async def search(self, query: str) -> list[dict]:
        """Search tickers by name/symbol."""
        cached = _get_cached(f"search:{query}", SEARCH_TTL)
        if cached is not None:
            return cached

        def _search() -> list[dict]:
            try:
                results = yf.Search(query)
                quotes = getattr(results, "quotes", []) or []
                return [
                    {
                        "ticker": q.get("symbol", ""),
                        "name": q.get("shortname") or q.get("longname", ""),
                        "exchange": q.get("exchange", ""),
                        "type": q.get("quoteType", ""),
                    }
                    for q in quotes
                    if q.get("symbol")
                ]
            except Exception:
                logger.exception("yfinance search failed for %s", query)
                return []

        result = await asyncio.to_thread(_search)
        _set_cached(f"search:{query}", result)
        return result

    async def get_info(self, ticker: str) -> dict:
        """Full asset info: name, sector, industry, market_cap, pe_ratio, etc."""
        if not ticker or ticker[0].isdigit():
            return {"ticker": ticker}

        cached = _get_cached(f"info:{ticker}", INFO_TTL)
        if cached is not None:
            return cached

        def _get() -> dict:
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
                return {
                    "ticker": ticker,
                    "name": info.get("shortName") or info.get("longName", ""),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": _normalize_pe(info.get("trailingPE"), info.get("trailingEps")),
                    "forward_pe": _normalize_pe(info.get("forwardPE"), info.get("forwardEps")),
                    "short_interest": info.get("shortPercentOfFloat"),
                    "shares_short": info.get("sharesShort"),
                    "short_ratio": info.get("shortRatio"),
                    "exchange": info.get("exchange", ""),
                    "shares_outstanding": info.get("sharesOutstanding"),
                    "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "previous_close": info.get("previousClose"),
                    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    "dividend_yield": _normalize_dividend_yield(info.get("dividendYield")),
                    "beta": info.get("beta"),
                    "currency": info.get("currency", "USD"),
                    "quote_type": info.get("quoteType", ""),
                    # Qualitative / descriptive
                    "long_business_summary": info.get("longBusinessSummary", ""),
                    "website": info.get("website", ""),
                    "full_time_employees": info.get("fullTimeEmployees"),
                    "country": info.get("country", ""),
                    "city": info.get("city", ""),
                    "state": info.get("state", ""),
                    # Key people
                    "company_officers": [
                        {
                            "name": o.get("name", ""),
                            "title": o.get("title", ""),
                            "age": o.get("age"),
                            "total_pay": o.get("totalPay"),
                        }
                        for o in (info.get("companyOfficers") or [])[:10]
                    ],
                    # Valuation ratios
                    "price_to_book": info.get("priceToBook"),
                    "peg_ratio": info.get("pegRatio"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "enterprise_to_revenue": info.get("enterpriseToRevenue"),
                    "enterprise_to_ebitda": info.get("enterpriseToEbitda"),
                    "price_to_sales": info.get("priceToSalesTrailing12Months"),
                    # EPS
                    "trailing_eps": info.get("trailingEps"),
                    "forward_eps": info.get("forwardEps"),
                    # Analyst consensus
                    "target_mean_price": info.get("targetMeanPrice"),
                    "target_high_price": info.get("targetHighPrice"),
                    "target_low_price": info.get("targetLowPrice"),
                    "analyst_count": info.get("numberOfAnalystOpinions"),
                    "recommendation": info.get("recommendationKey", ""),
                    # Balance sheet / liquidity
                    "current_ratio": info.get("currentRatio"),
                    "quick_ratio": info.get("quickRatio"),
                    "total_cash": info.get("totalCash"),
                    "total_debt": info.get("totalDebt"),
                    "operating_cashflow": info.get("operatingCashflow"),
                    # Extra financials
                    "revenue": info.get("totalRevenue"),
                    "net_income": info.get("netIncomeToCommon"),
                    "profit_margin": info.get("profitMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "return_on_equity": info.get("returnOnEquity"),
                    "return_on_assets": info.get("returnOnAssets"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "free_cash_flow": info.get("freeCashflow"),
                    "earnings_growth": info.get("earningsGrowth"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "gross_margins": info.get("grossMargins"),
                    "ebitda_margins": info.get("ebitdaMargins"),
                    "ebitda": info.get("ebitda"),
                    "gross_profits": info.get("grossProfits"),
                    # Trading / per-share
                    "average_volume": info.get("averageVolume"),
                    "book_value": info.get("bookValue"),
                    "revenue_per_share": info.get("revenuePerShare"),
                    # Bid-ask (current snapshot, delayed)
                    "bid": info.get("bid"),
                    "ask": info.get("ask"),
                    "bid_size": info.get("bidSize"),
                    "ask_size": info.get("askSize"),
                }
            except Exception:
                logger.exception("yfinance get_info failed for %s", ticker)
                return {"ticker": ticker}

        result = await asyncio.to_thread(_get)
        _set_cached(f"info:{ticker}", result)
        return result

    async def get_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        start: str = "",
        end: str = "",
        auto_adjust: bool = True,
    ) -> list[dict]:
        """Historical OHLCV data, optionally adjusted for splits and dividends.

        Args:
            ticker: Stock ticker symbol.
            period: Preset period (e.g. '1y', '5y', 'max').
            interval: Bar interval (e.g. '1d', '1h').
            start: Custom start date (ISO format).
            end: Custom end date (ISO format).
            auto_adjust: When True (default), all OHLCV values are adjusted for
                splits/dividends. When False, raw prices are returned alongside
                an ``adj_close`` field containing the adjusted closing price.

        Use start/end for custom date ranges, or period for presets.
        Checks for cached 5y/max data first to avoid redundant API calls.
        """
        if not ticker or ticker[0].isdigit():
            return []

        adj_tag = "adj" if auto_adjust else "raw"
        cache_key = f"history:{ticker}:{start or period}:{end}:{interval}:{adj_tag}"
        cached = _get_cached(cache_key, HISTORY_TTL)
        if cached is not None:
            return cached

        # Try to slice from wide cache (max or 5y) — avoids a new API call
        # when portfolio batch download already populated the cache.
        # Wide cache only contains adjusted data, so skip for raw requests.
        if interval == "1d" and auto_adjust:
            wide = _try_get_wide_cache(ticker, interval)
            if wide is not None:
                cutoff_5y = _period_cutoff("5y")
                can_slice = (
                    (not start and not end and period in _SLICEABLE_PERIODS)
                    or (start and end and cutoff_5y and start >= cutoff_5y)
                    or period == "max"
                )
                if can_slice:
                    if start and end:
                        sliced = _slice_history(wide, start, end)
                    elif period == "max":
                        sliced = wide
                    else:
                        cutoff = _period_cutoff(period) or ""
                        sliced = _slice_history(wide, cutoff, "")
                    _set_cached(cache_key, sliced)
                    return sliced

        def _get() -> list[dict]:
            try:
                t = yf.Ticker(ticker)
                if start and end:
                    df = t.history(start=start, end=end, interval=interval, auto_adjust=auto_adjust)
                else:
                    df = t.history(period=period, interval=interval, auto_adjust=auto_adjust)
                if df is None or df.empty:
                    return []
                records = []
                for idx, row in df.iterrows():
                    record = {
                        "date": str(idx),
                        "open": float(row.get("Open", 0)),
                        "high": float(row.get("High", 0)),
                        "low": float(row.get("Low", 0)),
                        "close": float(row.get("Close", 0)),
                        "volume": int(row.get("Volume", 0)),
                    }
                    if not auto_adjust:
                        record["adj_close"] = float(row.get("Adj Close", row.get("Close", 0)))
                    records.append(record)
                return records
            except Exception:
                logger.exception("yfinance history failed for %s", ticker)
                return []

        result = await asyncio.to_thread(_get)
        _set_cached(cache_key, result)
        return result

    async def get_performance_metrics(
        self,
        ticker: str,
        period: str = "3y",
    ) -> dict:
        """Sharpe, max drawdown, period returns from history."""
        history = await self.get_history(ticker, period=period, interval="1d")
        if not history:
            return {}

        import numpy as np

        from stats.core import (
            max_drawdown,
            period_return,
            sharpe_ratio,
            simple_returns,
        )

        closes = np.array([h["close"] for h in history if h["close"] > 0])
        if len(closes) < 2:
            return {}

        rets = simple_returns(closes)
        dd = max_drawdown(closes)

        return {
            "sharpe_ratio": round(sharpe_ratio(rets), 2),
            "max_drawdown_pct": round(dd.max_drawdown_pct, 2),
            "return_1m": period_return(closes, 21),
            "return_6m": period_return(closes, 126),
            "return_1y": period_return(closes, 252),
            "return_3y": period_return(closes, 756),
        }

    async def get_news(self, ticker: str) -> list[dict]:
        """Recent news via yf.Ticker(ticker).news."""
        cached = _get_cached(f"news:{ticker}", INFO_TTL)
        if cached is not None:
            return cached

        def _get() -> list[dict]:
            try:
                t = yf.Ticker(ticker)
                news = t.news or []
                articles = []
                for item in news:
                    content = item.get("content", {}) if isinstance(item, dict) else {}
                    articles.append(
                        {
                            "title": content.get("title") or item.get("title", ""),
                            "publisher": content.get("provider", {}).get("displayName", "")
                            or item.get("publisher", ""),
                            "url": content.get("canonicalUrl", {}).get("url", "")
                            or item.get("link", ""),
                            "published_at": content.get("pubDate")
                            or item.get("providerPublishTime", ""),
                            "summary": content.get("summary", "") or "",
                        }
                    )
                return articles
            except Exception:
                logger.exception("yfinance news failed for %s", ticker)
                return []

        result = await asyncio.to_thread(_get)
        _set_cached(f"news:{ticker}", result)
        return result

    async def enrich_batch(
        self,
        tickers: list[str],
        max_calls: int = 50,
    ) -> dict[str, dict[str, Any]]:
        """Batch enrichment: market_cap, sector, industry, shares_outstanding."""
        results: dict[str, dict[str, Any]] = {}
        for ticker in tickers[:max_calls]:
            info = await self.get_info(ticker)
            if info.get("market_cap") or info.get("sector"):
                results[ticker] = {
                    "market_cap": info.get("market_cap"),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "shares_outstanding": info.get("shares_outstanding"),
                }
            await asyncio.sleep(0.2)  # Rate limiting

        logger.info("yfinance: enriched %d/%d tickers", len(results), len(tickers[:max_calls]))
        return results

    async def filter_stocks(
        self,
        price_min: float,
        price_max: float,
        market_cap_min: float = 0,
        market_cap_max: float = 0,
    ) -> list[StockInfo]:
        """
        Screen for stocks using yfinance screener.
        No return-based filtering — just price/market_cap.
        Uses yf.EquityQuery + yf.screen() (yfinance >= 1.0).
        """

        def _screen() -> list[StockInfo]:
            try:
                from yfinance import EquityQuery, screen

                # All filtering done server-side in the yfinance query:
                # - Price range (intraday, not stale close)
                # - Exchange (NASDAQ NMS/NGM/NCM, NYSE NYQ, AMEX ASE only)
                # - Market cap from intraday data (not stale)
                # - Exclude zero/missing market cap (filters out warrants, units, SPACs)
                operands = [
                    EquityQuery("gt", ["intradayprice", price_min]),
                    EquityQuery("lt", ["intradayprice", price_max]),
                    EquityQuery("eq", ["region", "us"]),
                    EquityQuery(
                        "or",
                        [
                            EquityQuery("eq", ["exchange", "NMS"]),  # NASDAQ Global Select
                            EquityQuery("eq", ["exchange", "NGM"]),  # NASDAQ Global Market
                            EquityQuery("eq", ["exchange", "NCM"]),  # NASDAQ Capital Market
                            EquityQuery("eq", ["exchange", "NYQ"]),  # NYSE
                            EquityQuery("eq", ["exchange", "ASE"]),  # NYSE American (AMEX)
                        ],
                    ),
                    EquityQuery("gt", ["intradaymarketcap", max(market_cap_min, 1)]),
                ]
                if market_cap_max:
                    operands.append(EquityQuery("lt", ["intradaymarketcap", market_cap_max]))

                query = EquityQuery("and", operands)

                # First request to get total count
                resp = screen(
                    query,
                    size=_SCREEN_PAGE_SIZE,
                    offset=0,
                    sortField="intradaymarketcap",
                    sortAsc=True,
                )
                total = resp.get("total", 0) if resp else 0
                all_quotes = resp.get("quotes", []) if resp else []

                # Paginate through ALL results — yfinance is free with no rate limit.
                # This ensures we don't miss any matching stocks.
                # Typically ~1700 results = 7 pages = ~2 seconds.
                offset = _SCREEN_PAGE_SIZE
                while offset < total:
                    resp = screen(
                        query,
                        size=_SCREEN_PAGE_SIZE,
                        offset=offset,
                        sortField="intradaymarketcap",
                        sortAsc=True,
                    )
                    quotes = resp.get("quotes", []) if resp else []
                    if not quotes:
                        break
                    all_quotes.extend(quotes)
                    offset += _SCREEN_PAGE_SIZE

                # Deduplicate by symbol
                seen = set()
                stocks = []
                for q in all_quotes:
                    symbol = q.get("symbol", "")
                    if not symbol or symbol in seen:
                        continue
                    seen.add(symbol)
                    stocks.append(
                        StockInfo(
                            ticker=symbol,
                            name=q.get("shortName") or q.get("longName", ""),
                            exchange=q.get("exchange", ""),
                            sector=q.get("sector", ""),
                            industry=q.get("industry", ""),
                            market_cap=q.get("marketCap"),
                            avg_volume=q.get("averageDailyVolume3Month", 0) or 0,
                            last_price=q.get("regularMarketPrice", 0.0) or 0.0,
                            shares_outstanding=q.get("sharesOutstanding"),
                            in_universe=True,
                        )
                    )

                logger.info(
                    "yfinance screener: %d/%d stocks on NASDAQ/NYSE/AMEX",
                    len(stocks),
                    total,
                )
                return stocks
            except Exception:
                logger.exception("yfinance stock screening failed")
                return []

        return await asyncio.to_thread(_screen)

    async def get_holders(self, ticker: str) -> dict:
        """Top institutional and mutual fund holders for a ticker."""
        cache_key = f"holders:{ticker}"
        cached = _get_cached(cache_key, INFO_TTL)
        if cached is not None:
            return cached

        def _get() -> dict:
            result: dict = {"major": None, "institutional": [], "mutual_fund": []}
            try:
                t = yf.Ticker(ticker)

                # Major holders breakdown
                mh = t.major_holders
                if mh is not None and not mh.empty:
                    # Index-based access: keys are row labels, "Value" is the column
                    def _mh_val(key, default=0):
                        try:
                            return float(mh.loc[key, "Value"])
                        except (KeyError, TypeError):
                            return default

                    result["major"] = {
                        "insiders_pct": round(_mh_val("insidersPercentHeld") * 100, 2),
                        "institutions_pct": round(_mh_val("institutionsPercentHeld") * 100, 2),
                        "institutions_float_pct": round(
                            _mh_val("institutionsFloatPercentHeld") * 100, 2
                        ),
                        "institutions_count": int(_mh_val("institutionsCount")),
                    }

                # Top institutional holders
                ih = t.institutional_holders
                if ih is not None and not ih.empty:
                    for _, row in ih.head(15).iterrows():
                        result["institutional"].append(
                            {
                                "holder": str(row.get("Holder", "")),
                                "shares": int(row.get("Shares", 0)),
                                "value": float(row.get("Value", 0)),
                                "pct_held": round(float(row.get("pctHeld", 0)) * 100, 4),
                                "pct_change": round(float(row.get("pctChange", 0)) * 100, 2),
                                "date_reported": str(row.get("Date Reported", ""))[:10],
                            }
                        )

                # Top mutual fund holders
                mfh = t.mutualfund_holders
                if mfh is not None and not mfh.empty:
                    for _, row in mfh.head(10).iterrows():
                        result["mutual_fund"].append(
                            {
                                "holder": str(row.get("Holder", "")),
                                "shares": int(row.get("Shares", 0)),
                                "value": float(row.get("Value", 0)),
                                "pct_held": round(float(row.get("pctHeld", 0)) * 100, 4),
                                "pct_change": round(float(row.get("pctChange", 0)) * 100, 2),
                                "date_reported": str(row.get("Date Reported", ""))[:10],
                            }
                        )

            except Exception:
                logger.exception("Failed to get holders for %s", ticker)
            return result

        result = await asyncio.to_thread(_get)
        _set_cached(cache_key, result)
        return result

    async def get_yield_curve(self, region: str = "US") -> dict:
        """Treasury yields for curve construction.

        Note: only US treasury yields are available via yfinance.
        Non-US bond yield tickers have been delisted from Yahoo Finance.
        """
        ticker_map = {
            "US": {
                "3M": "^IRX",
                "2Y": "2YY=F",
                "5Y": "^FVX",
                "10Y": "^TNX",
                "30Y": "^TYX",
            },
        }

        tickers = ticker_map.get(region, ticker_map["US"])

        def _get() -> dict:
            curve = {}
            for label, symbol in tickers.items():
                try:
                    t = yf.Ticker(symbol)
                    # Try info first, then fall back to recent history close
                    info = t.info or {}
                    price = info.get("regularMarketPrice") or info.get("previousClose")
                    if price is None:
                        # Fallback: get last close from recent history
                        hist = t.history(period="5d", auto_adjust=True)
                        if hist is not None and not hist.empty:
                            price = float(hist["Close"].iloc[-1])
                    if price is not None:
                        curve[label] = round(float(price), 3)
                except Exception:
                    logger.debug("Failed to get yield for %s (%s)", label, symbol)
            return {"region": region, "curve": curve}

        return await asyncio.to_thread(_get)

    async def get_yield_curve_history(self, period: str = "1y") -> dict:
        """
        Historical yield curves — returns daily yields for each tenor over a period.

        Returns: {"dates": ["2024-01-02", ...], "tenors": {"3M": [val, ...], "2Y": [val, ...], ...}}
        """
        tickers = {
            "3M": "^IRX",
            "2Y": "2YY=F",
            "5Y": "^FVX",
            "10Y": "^TNX",
            "30Y": "^TYX",
        }

        def _get() -> dict:

            tenor_data: dict[str, dict[str, float]] = {}  # tenor -> {date_str: yield}
            all_dates: set[str] = set()

            for label, symbol in tickers.items():
                try:
                    t = yf.Ticker(symbol)
                    hist = t.history(period=period, auto_adjust=True)
                    if hist is not None and not hist.empty:
                        date_yields = {}
                        for idx, row in hist.iterrows():
                            date_str = idx.strftime("%Y-%m-%d")
                            date_yields[date_str] = round(float(row["Close"]), 3)
                            all_dates.add(date_str)
                        tenor_data[label] = date_yields
                except Exception:
                    logger.debug("Failed to get yield history for %s (%s)", label, symbol)

            # Build aligned output: sorted dates with values per tenor
            sorted_dates = sorted(all_dates)
            tenors_out = {}
            for label in ["3M", "2Y", "5Y", "10Y", "30Y"]:
                if label in tenor_data:
                    tenors_out[label] = [tenor_data[label].get(d) for d in sorted_dates]

            return {"dates": sorted_dates, "tenors": tenors_out}

        return await asyncio.to_thread(_get)

    async def get_put_call_iv_spread(
        self,
        ticker: str = "SPY",
        expiry: str | None = None,
    ) -> dict:
        """
        Put-call implied volatility spread for an equity (default SPY).

        Args:
            expiry: specific expiry date (YYYY-MM-DD), or None to auto-select most liquid.

        Returns:
        - skew: IV across strikes (raw put/call IV + OTM composite vol)
        - term_structure: ATM put-call IV spread across multiple expiries
        - available_expiries: all expiry dates for date comparison
        """

        def _get() -> dict:
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
                spot = info.get("regularMarketPrice") or info.get("previousClose") or 0
                expirations = t.options
                if not expirations or spot <= 0:
                    return {
                        "spot": spot,
                        "ticker": ticker,
                        "available_expiries": [],
                        "skew": [],
                        "term_structure": [],
                    }

                available_expiries = list(expirations[:20])

                # --- Select expiry ---
                if expiry and expiry in expirations:
                    best_exp = expiry
                else:
                    # Auto-select: pick the expiry with the most liquid data
                    best_exp = expirations[0]
                    best_count = 0
                    for candidate in expirations[:5]:
                        try:
                            ch = t.option_chain(candidate)
                            valid = (ch.puts["impliedVolatility"] > SENTINEL_IV).sum() + (
                                ch.calls["impliedVolatility"] > SENTINEL_IV
                            ).sum()
                            if valid > best_count:
                                best_count = valid
                                best_exp = candidate
                        except Exception:
                            continue
                exp = best_exp
                chain = t.option_chain(exp)
                calls = chain.calls
                puts = chain.puts

                # Returns three views:
                # - put_iv / call_iv: OTM-only IVs for combined view
                # - raw_put_iv / raw_call_iv: full IV across all strikes
                # - vol: composite OTM surface (puts below spot, calls above)
                #
                # OTM rule: puts are OTM when strike < spot, calls when strike > spot.
                # At the single nearest ATM strike, average both.
                strike_min = spot * 0.75
                strike_max = spot * 1.25

                # Get all strikes in range (unfiltered) for a continuous x-axis
                calls_range = calls[
                    (calls["strike"] >= strike_min) & (calls["strike"] <= strike_max)
                ]
                puts_range = puts[(puts["strike"] >= strike_min) & (puts["strike"] <= strike_max)]

                # IV maps exclude sentinel values (deep ITM where IV is undefined)
                call_iv_all = {
                    s: iv
                    for s, iv in zip(
                        calls_range["strike"], calls_range["impliedVolatility"], strict=True
                    )
                    if iv > SENTINEL_IV
                }
                put_iv_all = {
                    s: iv
                    for s, iv in zip(
                        puts_range["strike"], puts_range["impliedVolatility"], strict=True
                    )
                    if iv > SENTINEL_IV
                }

                # All strikes from both chains for continuous x-axis
                all_strikes = sorted(
                    set(calls_range["strike"].tolist()) | set(puts_range["strike"].tolist())
                )

                # Find the single ATM strike (closest to spot)
                atm_strike = min(all_strikes, key=lambda k: abs(k - spot)) if all_strikes else spot

                skew = []
                for strike in all_strikes:
                    c_iv = call_iv_all.get(strike)
                    p_iv = put_iv_all.get(strike)
                    moneyness = round(((strike / spot) - 1) * 100, 2) if spot > 0 else 0
                    entry = {"strike": strike, "moneyness": moneyness}

                    # Raw IVs — full surface for put and call views
                    if p_iv is not None:
                        entry["raw_put_iv"] = round(p_iv * 100, 2)
                    if c_iv is not None:
                        entry["raw_call_iv"] = round(c_iv * 100, 2)

                    # OTM-only assignment for combined view:
                    # strike < spot → OTM put
                    # strike > spot → OTM call
                    # strike == ATM → both (for smooth crossover)
                    if strike == atm_strike:
                        if p_iv is not None:
                            entry["put_iv"] = round(p_iv * 100, 2)
                        if c_iv is not None:
                            entry["call_iv"] = round(c_iv * 100, 2)
                        if p_iv and c_iv:
                            entry["vol"] = round(((p_iv + c_iv) / 2) * 100, 2)
                        elif p_iv:
                            entry["vol"] = round(p_iv * 100, 2)
                        elif c_iv:
                            entry["vol"] = round(c_iv * 100, 2)
                    elif strike < spot:
                        # OTM put side
                        if p_iv is not None:
                            entry["put_iv"] = round(p_iv * 100, 2)
                            entry["vol"] = round(p_iv * 100, 2)
                    else:
                        # OTM call side
                        if c_iv is not None:
                            entry["call_iv"] = round(c_iv * 100, 2)
                            entry["vol"] = round(c_iv * 100, 2)

                    if len(entry) > 1:  # more than just 'strike'
                        skew.append(entry)

                # --- Term structure: ATM spread across expiries ---
                term_structure = []
                for exp_date in expirations[:12]:
                    try:
                        ch = t.option_chain(exp_date)
                        # Filter out sentinel IV (see SENTINEL_IV) before finding ATM
                        valid_calls = ch.calls[ch.calls["impliedVolatility"] > SENTINEL_IV]
                        valid_puts = ch.puts[ch.puts["impliedVolatility"] > SENTINEL_IV]
                        if valid_calls.empty or valid_puts.empty:
                            continue
                        atm_call = valid_calls.iloc[
                            (valid_calls["strike"] - spot).abs().argsort()[:1]
                        ]
                        atm_put = valid_puts.iloc[(valid_puts["strike"] - spot).abs().argsort()[:1]]
                        c_iv = float(atm_call["impliedVolatility"].iloc[0])
                        p_iv = float(atm_put["impliedVolatility"].iloc[0])
                        term_structure.append(
                            {
                                "expiry": exp_date,
                                "call_iv": round(c_iv * 100, 2),
                                "put_iv": round(p_iv * 100, 2),
                                "spread": round((p_iv - c_iv) * 100, 2),
                            }
                        )
                    except Exception:
                        continue

                return {
                    "ticker": ticker,
                    "spot": round(spot, 2),
                    "skew_expiry": exp,
                    "available_expiries": available_expiries,
                    "skew": skew,
                    "term_structure": term_structure,
                }
            except Exception:
                logger.exception("Failed to get put-call IV spread for %s", ticker)
                return {
                    "ticker": ticker,
                    "spot": 0,
                    "available_expiries": [],
                    "skew": [],
                    "term_structure": [],
                }

        cache_key = f"iv_spread:{ticker}:{expiry or 'auto'}"
        cached = _get_cached(cache_key, INFO_TTL)
        if cached is not None:
            return cached

        result = await asyncio.to_thread(_get)
        _set_cached(cache_key, result)
        return result

    async def get_option_chain_raw(
        self,
        ticker: str,
        expiry: str | None = None,
    ) -> dict:
        """Raw option chain for one expiry — full quote fields, OTM + ITM.

        Unlike :meth:`get_put_call_iv_spread` (which is lossy — drops bid/ask
        and rounds IVs to 2 dp), this method preserves every quote field the
        downstream IV-surface pipeline needs. Used by the SSVI / SABR +
        Gaussian-process pipeline in ``stats/options/pipeline.py``.

        Args:
            ticker:  equity / ETF / index ticker.
            expiry:  specific expiry as ``YYYY-MM-DD``; if ``None`` the
                     method auto-selects the most liquid expiry from the
                     first 5 available (matching ``get_put_call_iv_spread``).

        Returns:
            Dict with::

                {
                    'ticker': str,
                    'spot': float,
                    'expiry': str,                # the resolved expiry
                    'expiry_ts': float,           # unix seconds, 16:00 ET
                    'available_expiries': [str],  # full list, up to 20
                    'calls': [
                        {strike, bid, ask, mid, last, volume, oi,
                         iv_yahoo, contract_symbol},
                        ...
                    ],
                    'puts': [...],
                    'n_dropped_at_parse': int,    # rows rejected by semantic
                                                  # validation (NaN strike,
                                                  # crossed quote, etc.)
                }

            Missing fields default to ``None`` (last, iv_yahoo) or 0
            (volume / oi) via :func:`_safe_float_or_none` and
            :func:`_safe_int`. ``mid = (bid + ask) / 2`` is attached;
            ``spread = ask − bid`` is computed by the pipeline via
            ``_ensure_mid_spread``.
        """

        def _get() -> dict:
            empty: dict = {
                "ticker": ticker,
                "spot": 0.0,
                "expiry": "",
                "expiry_ts": 0.0,
                "available_expiries": [],
                "calls": [],
                "puts": [],
                "n_dropped_at_parse": 0,
                "stale_fraction": 0.0,
            }
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
                spot = float(info.get("regularMarketPrice") or info.get("previousClose") or 0)
                expirations = list(t.options or [])
                if not expirations or spot <= 0:
                    return empty

                available = expirations[:20]

                # Resolve expiry — explicit if provided & valid, else
                # auto-select the most liquid of the first 5 (same heuristic
                # as get_put_call_iv_spread for consistency).
                if expiry and expiry in expirations:
                    best_exp = expiry
                else:
                    # Auto-select the most *quotable* expiry from the
                    # first 5. We count rows with ``bid > 0`` rather than
                    # ``impliedVolatility > SENTINEL_IV`` because Yahoo
                    # publishes an IV on settled-but-unquoted strikes
                    # (e.g. an expiry-day chain after close), which the
                    # old heuristic happily selected — but every quote
                    # had bid = 0 and the downstream cleaning filter
                    # dropped 100 % of rows. The bid-count heuristic
                    # picks the first expiry with genuine live quotes.
                    #
                    # Skip zero/one-DTE expiries: ``T`` is so small that
                    # the parity regression amplifies any bid-ask noise
                    # into absurd annualised rates (e.g. r = −96 yields
                    # ``r/T·100 % ≈ −9633 %`` on a 6-hour-to-expiry
                    # chain). Forces auto to land on the first ≥ 2-DTE
                    # weekly.
                    from datetime import date as _date

                    today = _date.today()

                    def _dte(exp_str: str) -> int:
                        try:
                            return (_date.fromisoformat(exp_str) - today).days
                        except (ValueError, TypeError):
                            return 0

                    candidate_pool = [c for c in expirations[:5] if _dte(c) >= 2]
                    if not candidate_pool:
                        candidate_pool = list(expirations[:5])

                    best_exp = candidate_pool[0]
                    best_count = 0
                    for candidate in candidate_pool:
                        try:
                            ch = t.option_chain(candidate)
                            valid = int((ch.puts["bid"] > 0).sum() + (ch.calls["bid"] > 0).sum())
                            if valid > best_count:
                                best_count = valid
                                best_exp = candidate
                        except (KeyError, AttributeError, ValueError):
                            # Missing column or malformed chain — try the next expiry.
                            continue

                chain = t.option_chain(best_exp)

                # Per-call drop counter for semantic-validation rejects.
                drop_count = [0]

                def _serialize(row, is_call: bool) -> dict | None:
                    """Map one chain row to the JSON shape. Returns ``None``
                    for rows that fail semantic validation; the caller
                    drops them and increments ``drop_count``.

                    Validation rules (CLAUDE.md §3):
                      strike must be a finite positive float;
                      bid / ask non-negative;
                      bid ≤ ask when both are positive (no crossed quote).

                    Off-hours fallback. When ``bid = ask = 0`` (yfinance
                    returns a settled chain with no live two-sided
                    quotes) and ``lastPrice > 0`` is available, we
                    substitute the last-traded price for the mid and
                    synthesise a small half-spread so the downstream GP
                    heteroscedastic noise stays well-conditioned. Rows
                    that fall back to last-price carry ``is_stale =
                    True`` so the slice + service + UI can surface a
                    degraded-data banner. Strikes with no live quote
                    *and* no usable lastPrice are dropped.
                    """
                    strike = _safe_float_or_none(row.strike)
                    if strike is None or strike <= 0:
                        return None

                    bid = _safe_float_or_none(row.bid) or 0.0
                    ask = _safe_float_or_none(row.ask) or 0.0
                    last = _safe_float_or_none(row.lastPrice)
                    is_stale = False

                    if bid <= 0.0 and ask <= 0.0:
                        if last is None or last <= 0.0:
                            return None  # no live quote AND no last-traded price
                        is_stale = True
                        mid = last
                        # Half-spread floor at 1 ¢, scaled to last (2 %)
                        # so the GP noise variance ~ (spread/2 / vega)²
                        # remains finite and positive.
                        half_spread = max(0.01, 0.02 * last)
                        bid = max(0.0, last - half_spread)
                        ask = last + half_spread
                    elif bid < 0 or ask < 0:
                        return None
                    elif ask > 0 and bid > ask:
                        return None  # crossed quote
                    else:
                        mid = 0.5 * (bid + ask)

                    iv_raw = _safe_float_or_none(row.impliedVolatility)
                    iv = iv_raw if iv_raw is not None and iv_raw > SENTINEL_IV else None

                    return {
                        "strike": strike,
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "last": last,
                        "volume": _safe_int(row.volume),
                        "oi": _safe_int(row.openInterest),
                        "iv_yahoo": iv,
                        "is_call": is_call,
                        "contract_symbol": str(row.contractSymbol),
                        "is_stale": is_stale,
                    }

                def _serialize_filter(rows, is_call: bool) -> list[dict]:
                    out: list[dict] = []
                    for row in rows:
                        rec = _serialize(row, is_call)
                        if rec is None:
                            drop_count[0] += 1
                        else:
                            out.append(rec)
                    return out

                calls = _serialize_filter(chain.calls.itertuples(index=False), True)
                puts = _serialize_filter(chain.puts.itertuples(index=False), False)
                n_dropped = drop_count[0]
                if n_dropped:
                    logger.info(
                        "yfinance chain for %s expiry %s: dropped %d row(s) "
                        "at parse (NaN strike / crossed quote / negative price)",
                        ticker,
                        best_exp,
                        n_dropped,
                    )

                # Stale-quote diagnostic: fraction of surviving rows
                # that fell back to lastPrice. UI uses this to render
                # the degraded-data banner.
                total = len(calls) + len(puts)
                if total > 0:
                    n_stale = sum(1 for r in (*calls, *puts) if r["is_stale"])
                    stale_fraction = n_stale / total
                else:
                    stale_fraction = 0.0
                if stale_fraction >= 0.5:
                    logger.info(
                        "yfinance chain for %s expiry %s: %d/%d rows stale "
                        "(using lastPrice as mid — US market likely closed)",
                        ticker,
                        best_exp,
                        n_stale if total > 0 else 0,
                        total,
                    )

                # 4 pm ET expiry timestamp (yfinance uses settlement). Stored
                # in unix-seconds form to keep the JSON payload small.
                from datetime import datetime

                expiry_dt = datetime.fromisoformat(best_exp).replace(
                    hour=20, minute=0, second=0, tzinfo=UTC
                )  # 16:00 ET ≈ 20:00 UTC (DST-imprecise; close enough for T)
                expiry_ts = expiry_dt.timestamp()

                return {
                    "ticker": ticker,
                    "spot": round(spot, 4),
                    "expiry": best_exp,
                    "expiry_ts": expiry_ts,
                    "available_expiries": available,
                    "calls": calls,
                    "puts": puts,
                    "n_dropped_at_parse": n_dropped,
                    "stale_fraction": stale_fraction,
                }
            except (KeyError, AttributeError, ValueError, OSError) as e:
                # yfinance can fail in many shapes (missing columns, JSON
                # decode errors via the underlying ``requests`` stack,
                # network glitches). Catch the expected boundary types and
                # log; do *not* swallow programming errors (``TypeError`` /
                # ``AssertionError``) silently.
                logger.exception("Failed to get raw option chain for %s: %s", ticker, e)
                return empty

        cache_key = f"option_chain_raw:{ticker}:{expiry or 'auto'}"
        cached = _get_cached(cache_key, OPTION_CHAIN_TTL)
        if cached is not None:
            return cached
        # If the caller didn't pin an expiry but a previous *explicit*
        # call for the auto-resolved date is already cached, prefer
        # that snapshot rather than fetching a fresh (possibly drifted)
        # one. We don't know the resolved expiry without running the
        # auto-select heuristic, so we do a cheap probe: ask yfinance
        # for the expiries list (yfinance memoises it internally) and
        # consult the cache under each candidate. The first hit is
        # the snapshot a previous explicit lookup populated, and
        # serving it here keeps "auto" and "explicit-same-expiry" in
        # sync.
        if not expiry:
            try:
                candidates = list(yf.Ticker(ticker).options or [])[:5]
                for cand in candidates:
                    cached_cand = _get_cached(f"option_chain_raw:{ticker}:{cand}", OPTION_CHAIN_TTL)
                    if cached_cand is not None:
                        _set_cached(cache_key, cached_cand)
                        return cached_cand
            except (AttributeError, ValueError, OSError):
                # yfinance hiccup — fall through to a normal fetch.
                pass
        result = await asyncio.to_thread(_get)
        _set_cached(cache_key, result)
        # When auto-selecting, also cache under the resolved expiry's
        # key so a later explicit lookup for the same date hits the
        # same snapshot rather than triggering a fresh yfinance
        # fetch (which would return a slightly different live-bid
        # snapshot and produce a different SSVI/GP/RND fit).
        if not expiry and result.get("expiry"):
            _set_cached(f"option_chain_raw:{ticker}:{result['expiry']}", result)
        return result

    async def get_g10_rates(self) -> list[dict]:
        """G10 central bank policy rates.

        Delegates to PolicyRateFetcher if available (fetches from BIS API).
        Falls back to hardcoded values if no fetcher is configured.
        """
        if self._policy_rate_fetcher is not None:
            return await self._policy_rate_fetcher.get_rates()

        # Fallback: hardcoded values (only used if fetcher not configured)
        return [
            {
                "country": "United States",
                "central_bank": "Federal Reserve",
                "rate": 4.50,
                "currency": "USD",
            },
            {"country": "Eurozone", "central_bank": "ECB", "rate": 2.65, "currency": "EUR"},
            {
                "country": "United Kingdom",
                "central_bank": "Bank of England",
                "rate": 4.50,
                "currency": "GBP",
            },
            {"country": "Japan", "central_bank": "Bank of Japan", "rate": 0.50, "currency": "JPY"},
            {
                "country": "Canada",
                "central_bank": "Bank of Canada",
                "rate": 2.75,
                "currency": "CAD",
            },
            {"country": "Australia", "central_bank": "RBA", "rate": 4.10, "currency": "AUD"},
            {"country": "New Zealand", "central_bank": "RBNZ", "rate": 3.75, "currency": "NZD"},
            {"country": "Switzerland", "central_bank": "SNB", "rate": 0.25, "currency": "CHF"},
            {"country": "Sweden", "central_bank": "Riksbank", "rate": 2.25, "currency": "SEK"},
            {"country": "Norway", "central_bank": "Norges Bank", "rate": 4.50, "currency": "NOK"},
        ]

    async def get_macro_summary(self) -> dict:
        """Macro economic indicators including crypto and FX."""
        symbols = {
            # Indices & Volatility
            "VIX": "^VIX",
            "DXY": "DX-Y.NYB",
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "Dow Jones": "^DJI",
            "Russell 2000": "^RUT",
            # Commodities
            "Crude Oil": "CL=F",
            "Gold": "GC=F",
            "Silver": "SI=F",
            "Nat Gas": "NG=F",
            # Fixed Income
            "10Y Yield": "^TNX",
            # Crypto
            "Bitcoin": "BTC-USD",
            "Ethereum": "ETH-USD",
            "Solana": "SOL-USD",
            # G10 FX
            "EUR/USD": "EURUSD=X",
            "GBP/USD": "GBPUSD=X",
            "USD/JPY": "USDJPY=X",
            "USD/CHF": "USDCHF=X",
            "AUD/USD": "AUDUSD=X",
            "USD/CAD": "USDCAD=X",
        }

        def _get() -> dict:
            summary = {}
            for label, symbol in symbols.items():
                try:
                    t = yf.Ticker(symbol)
                    info = t.info or {}
                    price = info.get("regularMarketPrice") or info.get("previousClose")
                    change = info.get("regularMarketChangePercent", 0)
                    if price is not None:
                        summary[label] = {
                            "ticker": symbol,
                            "price": round(float(price), 2),
                            "change_pct": round(float(change or 0), 2),
                        }
                except Exception:
                    logger.debug("Failed to get macro data for %s", label)
            return summary

        cached = _get_cached("macro_summary", MACRO_TTL, market_aware=False)
        if cached is not None:
            return cached

        result = await asyncio.to_thread(_get)
        _set_cached("macro_summary", result)
        return result
