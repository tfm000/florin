"""
Economic & Earnings Calendar API endpoints.

Earnings: from Finnhub (free tier, date-range queries) with yfinance fallback.
Economic: from EconomicCalendarService (CB meeting dates + AV indicators + BIS rates).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from dashboard.dependencies import get_settings_dep, get_yfinance_dep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["calendar"])


# ==========================================================================
# Response models
# ==========================================================================


class EarningsEvent(BaseModel):
    """A single earnings event (upcoming or past)."""

    ticker: str
    name: str = ""
    date: str
    eps_estimate: float | None = None
    reported_eps: float | None = None
    surprise_pct: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    hour: str = ""  # "bmo" (before market open), "amc" (after market close), ""
    quarter: int | None = None
    year: int | None = None
    is_future: bool = True
    in_watchlist: bool = False


class EconomicEvent(BaseModel):
    """A single economic calendar event (CB meeting, macro indicator, etc.)."""

    date: str
    event: str
    importance: str = "high"
    expected: str = ""
    actual: str = ""
    previous: str = ""
    country: str = "US"
    country_name: str = ""
    institution: str = ""
    category: str = ""
    description: str = ""
    frequency: str = ""
    unit: str = ""
    indicator_key: str = ""
    source: str = ""


class CalendarResponse(BaseModel):
    """Combined calendar response with earnings and economic events."""

    earnings: list[EarningsEvent]
    economic: list[EconomicEvent]


class HistoryPoint(BaseModel):
    """A single historical data point for sparkline charts."""

    date: str
    value: str


# ==========================================================================
# Finnhub earnings fetcher
# ==========================================================================

_FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"


async def _fetch_finnhub_earnings(
    api_key: str, start_date: str, end_date: str,
    watchlist_tickers: set[str] | None = None,
) -> list[EarningsEvent]:
    """Fetch earnings calendar from Finnhub free tier.

    Returns all stocks with earnings in the date range.
    Watchlist tickers are flagged with ``in_watchlist=True``.

    Args:
        api_key: Finnhub API key.
        start_date: YYYY-MM-DD start of range.
        end_date: YYYY-MM-DD end of range.
        watchlist_tickers: Set of ticker symbols in the user's watchlist.

    Returns:
        List of EarningsEvent sorted by date descending.
    """
    watchlist = watchlist_tickers or set()
    today = datetime.now().strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                _FINNHUB_EARNINGS_URL,
                params={"from": start_date, "to": end_date, "token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch Finnhub earnings calendar")
            return []

    raw_events = data.get("earningsCalendar", [])
    results: list[EarningsEvent] = []

    for e in raw_events:
        symbol = e.get("symbol", "")
        if not symbol:
            continue

        date = e.get("date", "")
        eps_est = e.get("epsEstimate")
        eps_act = e.get("epsActual")
        rev_est = e.get("revenueEstimate")
        rev_act = e.get("revenueActual")

        # Calculate surprise %
        surprise = None
        if eps_est is not None and eps_act is not None and eps_est != 0:
            surprise = round((eps_act - eps_est) / abs(eps_est) * 100, 2)

        results.append(EarningsEvent(
            ticker=symbol,
            date=date,
            eps_estimate=eps_est,
            reported_eps=eps_act,
            surprise_pct=surprise,
            revenue_estimate=rev_est,
            revenue_actual=rev_act,
            hour=e.get("hour", ""),
            quarter=e.get("quarter"),
            year=e.get("year"),
            is_future=date >= today,
            in_watchlist=symbol.upper() in watchlist,
        ))

    results.sort(key=lambda x: x.date, reverse=True)
    return results


# ==========================================================================
# yfinance earnings fallback (per-ticker, for when Finnhub key is absent)
# ==========================================================================

def _get_earnings_sync(sym: str) -> list[EarningsEvent]:
    """Fetch earnings dates with estimates and actuals from yfinance.

    Fallback when Finnhub API key is not configured. Per-ticker only.
    """
    import yfinance as _yf
    try:
        t = _yf.Ticker(sym)
        info = t.info or {}
        name = info.get("shortName", "")
        today = datetime.now().strftime("%Y-%m-%d")
        results: list[EarningsEvent] = []

        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                for idx, row in ed.iterrows():
                    date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                    eps_est = row.get("EPS Estimate")
                    reported = row.get("Reported EPS")
                    surprise = row.get("Surprise(%)")

                    results.append(EarningsEvent(
                        ticker=sym,
                        name=name,
                        date=date_str,
                        eps_estimate=float(eps_est) if eps_est is not None and str(eps_est) != "nan" else None,
                        reported_eps=float(reported) if reported is not None and str(reported) != "nan" else None,
                        surprise_pct=float(surprise) if surprise is not None and str(surprise) != "nan" else None,
                        is_future=date_str >= today,
                        in_watchlist=True,  # yfinance fallback only runs for watchlist tickers
                    ))
                return results
        except Exception:  # noqa: BLE001 — yfinance raises varied exceptions
            pass

        # Fallback to calendar for upcoming only
        cal = t.calendar
        if cal and isinstance(cal, dict):
            earn_date = cal.get("Earnings Date")
            if earn_date and len(earn_date) > 0:
                d = earn_date[0]
                date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
                results.append(EarningsEvent(
                    ticker=sym,
                    name=name,
                    date=date_str,
                    eps_estimate=cal.get("Earnings Average"),
                    is_future=True,
                    in_watchlist=True,
                ))

        return results
    except Exception:  # noqa: BLE001 — yfinance raises varied exceptions
        return []


# ==========================================================================
# API endpoints
# ==========================================================================


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    tickers: str = Query(default="", description="Comma-separated tickers for earnings watchlist highlighting"),
    start_date: str = Query(default="", description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(default="", description="End date (YYYY-MM-DD)"),
    settings=Depends(get_settings_dep),
    yf=Depends(get_yfinance_dep),
):
    """Get earnings dates and economic events.

    Earnings come from Finnhub (free tier) if ``finnhub_api_key`` is configured,
    otherwise falls back to yfinance per-ticker lookups for watchlist tickers.

    Economic events come from the EconomicCalendarService (DB-cached data from
    CB website parsers, BIS API, ECB API, BOC API, and Alpha Vantage).
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else []
    watchlist_set = set(ticker_list)

    # Default date range for earnings
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        # Default: 4 weeks ahead
        from datetime import timedelta
        end_date = (datetime.now() + timedelta(days=28)).strftime("%Y-%m-%d")

    # --- Earnings ---
    earnings: list[EarningsEvent] = []
    if settings.finnhub_api_key:
        earnings = await _fetch_finnhub_earnings(
            settings.finnhub_api_key, start_date, end_date, watchlist_set,
        )
    else:
        # Fallback: yfinance per-ticker (watchlist only)
        for sym in ticker_list[:20]:
            try:
                events = await asyncio.to_thread(_get_earnings_sync, sym)
                earnings.extend(events)
            except Exception:
                pass
        earnings.sort(key=lambda e: e.date, reverse=True)

    # --- Economic events ---
    from dashboard.deps import get_state_value
    econ_service = get_state_value("economic_calendar_service")

    economic: list[EconomicEvent] = []
    if econ_service:
        raw_events = await econ_service.get_events(start_date, end_date)
        economic = [EconomicEvent(**e) for e in raw_events]
    else:
        logger.warning("EconomicCalendarService not available — returning empty economic events")

    return CalendarResponse(earnings=earnings, economic=economic)


@router.get("/calendar/indicators/{indicator_key}/history", response_model=list[HistoryPoint])
async def get_indicator_history(
    indicator_key: str,
    months: int = Query(default=36, ge=1, le=240, description="Number of months of history (default 36 = 3 years)"),
    start_date: str = Query(default="", description="Custom start date (YYYY-MM-DD). Overrides months if set."),
    end_date: str = Query(default="", description="Custom end date (YYYY-MM-DD). Defaults to today."),
):
    """Get historical readings for a specific economic indicator.

    Supports two modes:
    - **Preset range:** ``months=36`` returns the last 36 months.
    - **Custom range:** ``start_date=2020-01-01&end_date=2023-12-31`` returns
      that specific period. When ``start_date`` is set, ``months`` is ignored.

    Returns data points sorted oldest-first for charting.

    Args:
        indicator_key: Indicator identifier (e.g. "us_cpi", "ecb_rate", "fed_rate").
        months: How many months of history to return (default 36 = 3 years).
        start_date: Custom start date. If set, overrides ``months``.
        end_date: Custom end date. Defaults to today if omitted.
    """
    from dashboard.deps import get_state_value
    econ_service = get_state_value("economic_calendar_service")

    if not econ_service:
        return []

    # Custom date range overrides months
    if start_date:
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        # Calculate months from date range
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            months = max(1, (end_dt.year - start_dt.year) * 12 + end_dt.month - start_dt.month + 1)
        except ValueError:
            pass  # Fall through to default months

    history = await econ_service.get_indicator_history(indicator_key, months)

    # If custom date range, filter to exact range
    if start_date:
        history = [h for h in history if h["date"] >= start_date and h["date"] <= (end_date or "9999-12-31")]

    return [HistoryPoint(**h) for h in history]
