"""
Yahoo Finance data provider via yfinance.

Powers research, enrichment, and penny stock screening.
All yfinance calls are synchronous — wrapped in asyncio.to_thread().
Results are cached with TTL to reduce API load.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

import yfinance as yf

from core.models import StockInfo

logger = logging.getLogger(__name__)

# TTL cache implementation
_cache: dict[str, tuple[float, Any]] = {}

INFO_TTL = 300  # 5 minutes
HISTORY_TTL = 3600  # 1 hour
SEARCH_TTL = 300  # 5 minutes


def _get_cached(key: str, ttl: float) -> Any | None:
    """Return cached value if still valid, else None."""
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < ttl:
            return val
        del _cache[key]
    return None


def _set_cached(key: str, val: Any) -> None:
    _cache[key] = (time.time(), val)


class YFinanceProvider:
    """Asset data via Yahoo Finance."""

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
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "short_interest": info.get("shortPercentOfFloat"),
                    "exchange": info.get("exchange", ""),
                    "shares_outstanding": info.get("sharesOutstanding"),
                    "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "previous_close": info.get("previousClose"),
                    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    "dividend_yield": info.get("dividendYield"),
                    "beta": info.get("beta"),
                    "currency": info.get("currency", "USD"),
                    "quote_type": info.get("quoteType", ""),
                }
            except Exception:
                logger.exception("yfinance get_info failed for %s", ticker)
                return {"ticker": ticker}

        result = await asyncio.to_thread(_get)
        _set_cached(f"info:{ticker}", result)
        return result

    async def get_history(
        self, ticker: str, period: str = "1y", interval: str = "1d",
    ) -> list[dict]:
        """Historical OHLCV data."""
        cache_key = f"history:{ticker}:{period}:{interval}"
        cached = _get_cached(cache_key, HISTORY_TTL)
        if cached is not None:
            return cached

        def _get() -> list[dict]:
            try:
                t = yf.Ticker(ticker)
                df = t.history(period=period, interval=interval)
                if df is None or df.empty:
                    return []
                records = []
                for idx, row in df.iterrows():
                    records.append({
                        "date": str(idx),
                        "open": float(row.get("Open", 0)),
                        "high": float(row.get("High", 0)),
                        "low": float(row.get("Low", 0)),
                        "close": float(row.get("Close", 0)),
                        "volume": int(row.get("Volume", 0)),
                    })
                return records
            except Exception:
                logger.exception("yfinance history failed for %s", ticker)
                return []

        result = await asyncio.to_thread(_get)
        _set_cached(cache_key, result)
        return result

    async def get_performance_metrics(self, ticker: str) -> dict:
        """Sharpe, max drawdown, period returns from history."""
        history = await self.get_history(ticker, period="3y", interval="1d")
        if not history:
            return {}

        closes = [h["close"] for h in history if h["close"] > 0]
        if len(closes) < 2:
            return {}

        # Daily returns
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

        # Sharpe ratio (annualised, risk-free = 0 for simplicity)
        import statistics
        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.0001
        sharpe = (mean_ret / std_ret) * (252 ** 0.5) if std_ret > 0 else 0.0

        # Max drawdown
        peak = closes[0]
        max_dd = 0.0
        for c in closes:
            if c > peak:
                peak = c
            dd = (peak - c) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Period returns
        def _period_return(n_days: int) -> float | None:
            if len(closes) < n_days:
                return None
            return ((closes[-1] - closes[-n_days]) / closes[-n_days]) * 100

        return {
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "return_1m": _period_return(21),
            "return_6m": _period_return(126),
            "return_1y": _period_return(252),
            "return_3y": _period_return(756),
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
                    articles.append({
                        "title": content.get("title") or item.get("title", ""),
                        "publisher": content.get("provider", {}).get("displayName", "")
                            or item.get("publisher", ""),
                        "url": content.get("canonicalUrl", {}).get("url", "")
                            or item.get("link", ""),
                        "published_at": content.get("pubDate") or item.get("providerPublishTime", ""),
                        "summary": content.get("summary", "") or "",
                    })
                return articles
            except Exception:
                logger.exception("yfinance news failed for %s", ticker)
                return []

        result = await asyncio.to_thread(_get)
        _set_cached(f"news:{ticker}", result)
        return result

    async def enrich_batch(
        self, tickers: list[str], max_calls: int = 50,
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

    async def filter_penny_stocks(
        self,
        price_min: float,
        price_max: float,
        market_cap_min: float = 0,
        market_cap_max: float = 0,
    ) -> list[StockInfo]:
        """
        Screen for penny stocks using yfinance screener module.
        No return-based filtering — just price/market_cap.
        """
        def _screen() -> list[StockInfo]:
            try:
                screener = yf.Screener()
                # Use predefined screener as a starting point
                screener.set_default_body({
                    "query": {
                        "operator": "AND",
                        "operands": [
                            {"operator": "gte", "operands": ["intradayprice", price_min]},
                            {"operator": "lte", "operands": ["intradayprice", price_max]},
                            {"operator": "EQ", "operands": ["region", "us"]},
                        ],
                    },
                    "size": 250,
                    "offset": 0,
                    "sortField": "intradaymarketcap",
                    "sortType": "ASC",
                })
                resp = screener.response
                quotes = resp.get("quotes", []) if resp else []

                stocks = []
                for q in quotes:
                    mcap = q.get("marketCap")
                    if market_cap_min and mcap and mcap < market_cap_min:
                        continue
                    if market_cap_max and mcap and mcap > market_cap_max:
                        continue

                    stocks.append(StockInfo(
                        ticker=q.get("symbol", ""),
                        name=q.get("shortName") or q.get("longName", ""),
                        exchange=q.get("exchange", ""),
                        sector=q.get("sector", ""),
                        industry=q.get("industry", ""),
                        market_cap=mcap,
                        avg_volume=q.get("averageDailyVolume3Month", 0) or 0,
                        last_price=q.get("regularMarketPrice", 0.0) or 0.0,
                        shares_outstanding=q.get("sharesOutstanding"),
                        in_universe=True,
                    ))
                return stocks
            except Exception:
                logger.exception("yfinance penny stock screening failed")
                return []

        return await asyncio.to_thread(_screen)

    async def get_yield_curve(self, region: str = "US") -> dict:
        """Treasury yields for curve construction."""
        ticker_map = {
            "US": {
                "3M": "^IRX",
                "2Y": "2YY=F",
                "5Y": "^FVX",
                "10Y": "^TNX",
                "30Y": "^TYX",
            },
            "UK": {
                "2Y": "GB2Y=X",
                "10Y": "GB10Y=X",
                "30Y": "GB30Y=X",
            },
            "Japan": {
                "2Y": "JP2Y=X",
                "10Y": "JP10Y=X",
                "30Y": "JP30Y=X",
            },
            "Europe": {
                "2Y": "EU2Y=X",
                "10Y": "EU10Y=X",
                "30Y": "EU30Y=X",
            },
        }

        tickers = ticker_map.get(region, ticker_map["US"])

        def _get() -> dict:
            curve = {}
            for label, symbol in tickers.items():
                try:
                    t = yf.Ticker(symbol)
                    info = t.info or {}
                    price = info.get("regularMarketPrice") or info.get("previousClose")
                    if price is not None:
                        curve[label] = round(float(price), 3)
                except Exception:
                    logger.debug("Failed to get yield for %s (%s)", label, symbol)
            return {"region": region, "curve": curve}

        return await asyncio.to_thread(_get)

    async def get_g10_rates(self) -> list[dict]:
        """G10 central bank policy rates (semi-static)."""
        # These are updated on central bank decisions, not real-time
        return [
            {"country": "United States", "central_bank": "Federal Reserve", "rate": 4.50, "currency": "USD"},
            {"country": "Eurozone", "central_bank": "ECB", "rate": 2.65, "currency": "EUR"},
            {"country": "United Kingdom", "central_bank": "Bank of England", "rate": 4.50, "currency": "GBP"},
            {"country": "Japan", "central_bank": "Bank of Japan", "rate": 0.50, "currency": "JPY"},
            {"country": "Canada", "central_bank": "Bank of Canada", "rate": 2.75, "currency": "CAD"},
            {"country": "Australia", "central_bank": "RBA", "rate": 4.10, "currency": "AUD"},
            {"country": "New Zealand", "central_bank": "RBNZ", "rate": 3.75, "currency": "NZD"},
            {"country": "Switzerland", "central_bank": "SNB", "rate": 0.25, "currency": "CHF"},
            {"country": "Sweden", "central_bank": "Riksbank", "rate": 2.25, "currency": "SEK"},
            {"country": "Norway", "central_bank": "Norges Bank", "rate": 4.50, "currency": "NOK"},
        ]

    async def get_macro_summary(self) -> dict:
        """Macro economic indicators for LLM context (VIX, DXY, key indices, oil, gold)."""
        symbols = {
            "VIX": "^VIX",
            "DXY": "DX-Y.NYB",
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "Dow Jones": "^DJI",
            "Russell 2000": "^RUT",
            "Crude Oil": "CL=F",
            "Gold": "GC=F",
            "10Y Yield": "^TNX",
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
                            "price": round(float(price), 2),
                            "change_pct": round(float(change or 0), 2),
                        }
                except Exception:
                    logger.debug("Failed to get macro data for %s", label)
            return summary

        return await asyncio.to_thread(_get)
