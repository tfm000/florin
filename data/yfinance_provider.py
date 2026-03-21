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

INFO_TTL = 300  # 5 minutes (asset info, IV spreads)
MACRO_TTL = 60  # 1 minute (indices, commodities, crypto, FX)
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
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        start: str = "",
        end: str = "",
    ) -> list[dict]:
        """Historical OHLCV data using adjusted prices (accounts for splits and dividends).

        Use start/end for custom date ranges, or period for presets.
        """
        cache_key = f"history:{ticker}:{start or period}:{end}:{interval}"
        cached = _get_cached(cache_key, HISTORY_TTL)
        if cached is not None:
            return cached

        def _get() -> list[dict]:
            try:
                t = yf.Ticker(ticker)
                if start and end:
                    df = t.history(start=start, end=end, interval=interval, auto_adjust=True)
                else:
                    df = t.history(period=period, interval=interval, auto_adjust=True)
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
        Screen for penny stocks using yfinance screener.
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
                    EquityQuery("or", [
                        EquityQuery("eq", ["exchange", "NMS"]),   # NASDAQ Global Select
                        EquityQuery("eq", ["exchange", "NGM"]),   # NASDAQ Global Market
                        EquityQuery("eq", ["exchange", "NCM"]),   # NASDAQ Capital Market
                        EquityQuery("eq", ["exchange", "NYQ"]),   # NYSE
                        EquityQuery("eq", ["exchange", "ASE"]),   # NYSE American (AMEX)
                    ]),
                    EquityQuery("gt", ["intradaymarketcap", max(market_cap_min, 1)]),
                ]
                if market_cap_max:
                    operands.append(EquityQuery("lt", ["intradaymarketcap", market_cap_max]))

                query = EquityQuery("and", operands)
                PAGE_SIZE = 250

                # First request to get total count
                resp = screen(query, size=PAGE_SIZE, offset=0,
                              sortField="intradaymarketcap", sortAsc=True)
                total = resp.get("total", 0) if resp else 0
                all_quotes = resp.get("quotes", []) if resp else []

                # Paginate through ALL results — yfinance is free with no rate limit.
                # This ensures we don't miss any penny stock opportunities.
                # Typically ~1700 results = 7 pages = ~2 seconds.
                offset = PAGE_SIZE
                while offset < total:
                    resp = screen(query, size=PAGE_SIZE, offset=offset,
                                  sortField="intradaymarketcap", sortAsc=True)
                    quotes = resp.get("quotes", []) if resp else []
                    if not quotes:
                        break
                    all_quotes.extend(quotes)
                    offset += PAGE_SIZE

                # Deduplicate by symbol
                seen = set()
                stocks = []
                for q in all_quotes:
                    symbol = q.get("symbol", "")
                    if not symbol or symbol in seen:
                        continue
                    seen.add(symbol)
                    stocks.append(StockInfo(
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
                    ))

                logger.info(
                    "yfinance screener: %d/%d penny stocks on NASDAQ/NYSE/AMEX",
                    len(stocks), total,
                )
                return stocks
            except Exception:
                logger.exception("yfinance penny stock screening failed")
                return []

        return await asyncio.to_thread(_screen)

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
            import pandas as pd

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
                    tenors_out[label] = [
                        tenor_data[label].get(d) for d in sorted_dates
                    ]

            return {"dates": sorted_dates, "tenors": tenors_out}

        return await asyncio.to_thread(_get)

    async def get_put_call_iv_spread(
        self, ticker: str = "SPY", expiry: str | None = None,
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
                    return {"spot": spot, "ticker": ticker, "available_expiries": [],
                            "skew": [], "term_structure": []}

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
                            valid = (
                                (ch.puts["impliedVolatility"] > SENTINEL_IV).sum()
                                + (ch.calls["impliedVolatility"] > SENTINEL_IV).sum()
                            )
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
                SENTINEL_IV = 0.00002  # yfinance sentinel for undefined IV
                strike_min = spot * 0.75
                strike_max = spot * 1.25

                # Get all strikes in range (unfiltered) for a continuous x-axis
                calls_range = calls[
                    (calls["strike"] >= strike_min) & (calls["strike"] <= strike_max)
                ]
                puts_range = puts[
                    (puts["strike"] >= strike_min) & (puts["strike"] <= strike_max)
                ]

                # IV maps exclude sentinel values (deep ITM where IV is undefined)
                call_iv_all = {
                    s: iv for s, iv in zip(calls_range["strike"], calls_range["impliedVolatility"])
                    if iv > SENTINEL_IV
                }
                put_iv_all = {
                    s: iv for s, iv in zip(puts_range["strike"], puts_range["impliedVolatility"])
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
                        # Filter out sentinel IV (0.00001) before finding ATM
                        valid_calls = ch.calls[ch.calls["impliedVolatility"] > SENTINEL_IV]
                        valid_puts = ch.puts[ch.puts["impliedVolatility"] > SENTINEL_IV]
                        if valid_calls.empty or valid_puts.empty:
                            continue
                        atm_call = valid_calls.iloc[(valid_calls["strike"] - spot).abs().argsort()[:1]]
                        atm_put = valid_puts.iloc[(valid_puts["strike"] - spot).abs().argsort()[:1]]
                        c_iv = float(atm_call["impliedVolatility"].iloc[0])
                        p_iv = float(atm_put["impliedVolatility"].iloc[0])
                        term_structure.append({
                            "expiry": exp_date,
                            "call_iv": round(c_iv * 100, 2),
                            "put_iv": round(p_iv * 100, 2),
                            "spread": round((p_iv - c_iv) * 100, 2),
                        })
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
                return {"ticker": ticker, "spot": 0, "available_expiries": [],
                        "skew": [], "term_structure": []}

        cache_key = f"iv_spread:{ticker}:{expiry or 'auto'}"
        cached = _get_cached(cache_key, INFO_TTL)
        if cached is not None:
            return cached

        result = await asyncio.to_thread(_get)
        _set_cached(cache_key, result)
        return result

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

        cached = _get_cached("macro_summary", MACRO_TTL)
        if cached is not None:
            return cached

        result = await asyncio.to_thread(_get)
        _set_cached("macro_summary", result)
        return result
