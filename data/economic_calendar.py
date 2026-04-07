"""
Economic Calendar Service.

Aggregates economic event data from multiple free sources:

**Structured APIs (no scraping):**
- BIS CBPOL API — G10 central bank policy rates (via existing PolicyRateFetcher)
- ECB Data Portal API — Eurozone main refinancing rate
- Bank of Canada Valet API — Canadian policy rate
- Federal Reserve RSS feed — past FOMC statement dates
- Alpha Vantage — US macro indicator values (CPI, NFP, GDP, etc.)

**HTML parsing (for upcoming CB meeting dates only):**
- Federal Reserve FOMC calendar page
- ECB Governing Council calendar page
- Bank of England MPC dates page
- Bank of Japan MPM schedule page

All data is cached in the ``economic_events`` DB table.
Refresh strategy:
- CB meeting dates: once daily
- AV indicators: every 6 hours (respecting 25 req/day free-tier limit)
- BIS rates: already refreshed daily by PolicyRateFetcher
"""

from __future__ import annotations

import calendar as _calendar_mod
import csv
import io
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy import select

from config.constants import ALPHAVANTAGE_API_BASE
from core.rate_limiter import AsyncRateLimiter
from data.policy_rates import G10_COUNTRIES
from db.models import EconomicEventORM

if TYPE_CHECKING:
    from data.policy_rates import PolicyRateFetcher
    from db.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alpha Vantage indicator mappings
# ---------------------------------------------------------------------------

AV_INDICATORS: dict[str, dict[str, str]] = {
    "us_cpi": {
        "function": "CPI",
        "event": "CPI Release",
        "unit": "index 1982-84=100",
        "institution": "Bureau of Labor Statistics",
        "category": "Inflation",
        "importance": "high",
        "frequency": "Monthly",
        "description": "Consumer Price Index for All Urban Consumers, "
        "measuring average change in prices paid for a basket of goods and services.",
    },
    "us_fed_funds": {
        "function": "FEDERAL_FUNDS_RATE",
        "event": "Federal Funds Rate",
        "unit": "%",
        "institution": "Federal Reserve",
        "category": "Monetary Policy",
        "importance": "high",
        "frequency": "Monthly",
        "description": "The interest rate at which depository institutions "
        "lend reserve balances to other institutions overnight.",
    },
    "us_nfp": {
        "function": "NONFARM_PAYROLL",
        "event": "Non-Farm Payrolls",
        "unit": "K persons",
        "institution": "Bureau of Labor Statistics",
        "category": "Employment",
        "importance": "high",
        "frequency": "Monthly",
        "description": "Total number of paid US workers excluding farm employees, "
        "government employees, private household employees, and nonprofit workers.",
    },
    "us_unemployment": {
        "function": "UNEMPLOYMENT",
        "event": "Unemployment Rate",
        "unit": "%",
        "institution": "Bureau of Labor Statistics",
        "category": "Employment",
        "importance": "high",
        "frequency": "Monthly",
        "description": "Percentage of the total labour force that is unemployed "
        "but actively seeking employment and willing to work.",
    },
    "us_gdp": {
        "function": "REAL_GDP",
        "event": "Real GDP",
        "unit": "billions USD",
        "institution": "Bureau of Economic Analysis",
        "category": "Growth",
        "importance": "high",
        "frequency": "Quarterly",
        "description": "Inflation-adjusted value of all goods and services "
        "produced by the US economy.",
    },
    "us_retail_sales": {
        "function": "RETAIL_SALES",
        "event": "Retail Sales",
        "unit": "millions USD",
        "institution": "Census Bureau",
        "category": "Consumer",
        "importance": "medium",
        "frequency": "Monthly",
        "description": "Total receipts at stores that sell merchandise "
        "and related services to final consumers.",
    },
    "us_inflation": {
        "function": "INFLATION",
        "event": "Inflation Rate (YoY)",
        "unit": "%",
        "institution": "Bureau of Labor Statistics",
        "category": "Inflation",
        "importance": "high",
        "frequency": "Annual",
        "description": "Year-over-year percentage change in the Consumer Price Index.",
    },
    "us_treasury_10y": {
        "function": "TREASURY_YIELD",
        "event": "10-Year Treasury Yield",
        "unit": "%",
        "institution": "US Treasury",
        "category": "Fixed Income",
        "importance": "medium",
        "frequency": "Monthly",
        "description": "Yield on the benchmark 10-year US Treasury note.",
    },
    "us_durable_goods": {
        "function": "DURABLES",
        "event": "Durable Goods Orders",
        "unit": "millions USD",
        "institution": "Census Bureau",
        "category": "Manufacturing",
        "importance": "medium",
        "frequency": "Monthly",
        "description": "New orders placed with domestic manufacturers "
        "for delivery of hard goods expected to last 3+ years.",
    },
}

# ---------------------------------------------------------------------------
# Central bank meeting page URLs
# ---------------------------------------------------------------------------

_FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
_ECB_CALENDAR_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
_ECB_RATE_URL = (
    "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.MRR_FR.LEV"
    "?lastNObservations=30&format=jsondata"
)
_BOE_MPC_URL = "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates"
_BOJ_SCHEDULE_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
_BOC_RATE_URL = "https://www.bankofcanada.ca/valet/observations/V39079/json?recent=60"

# AV base
# Reuse the project-wide AV base URL constant
_AV_BASE = ALPHAVANTAGE_API_BASE

# BIS rate history (monthly observations per country)
_BIS_RATE_HISTORY_URL = (
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.{code}?format=csv"
    "&startPeriod={start}"
)

# Refresh intervals
_CB_REFRESH_INTERVAL = 86400  # 24 hours
_AV_REFRESH_INTERVAL = 86400  # 24 hours — macro data doesn't change intraday;
# also conserves the shared AV free-tier quota (25 req/day) which is split with
# the sentiment AlphaVantageSource (sentiment/alphavantage_source.py).


# Map indicator_key → BIS country code for rate history lookups
_INDICATOR_TO_BIS: dict[str, str] = {
    "us_rate": "US", "fed_rate": "US",
    "xm_rate": "XM", "ecb_rate": "XM",
    "gb_rate": "GB", "jp_rate": "JP",
    "ca_rate": "CA", "boc_rate": "CA",
    "au_rate": "AU", "nz_rate": "NZ",
    "ch_rate": "CH", "se_rate": "SE",
    "no_rate": "NO",
}


def _indicator_key_to_bis_code(indicator_key: str) -> str:
    """Convert an indicator key to a BIS country code for rate history.

    Returns empty string if no mapping exists.
    """
    return _INDICATOR_TO_BIS.get(indicator_key, "")


def _format_av_value(value: str, unit: str) -> str:
    """Format a raw Alpha Vantage numeric value with appropriate unit display.

    Args:
        value: Raw string value from AV (e.g. "326.785", "3.64").
        unit: Unit string from indicator config (e.g. "%", "index 1982-84=100").

    Returns:
        Formatted string (e.g. "3.64%", "326.785", "$21,974B").
    """
    try:
        val = float(value)
    except ValueError:
        return value

    if unit == "%":
        return f"{val:.2f}%"
    if "index" in unit.lower():
        return f"{val:.3f}"
    if "billions" in unit.lower():
        return f"${val:,.1f}B"
    if "millions" in unit.lower():
        return f"${val:,.0f}M"
    if "persons" in unit.lower():
        return f"{val:,.0f}K"
    return f"{val:,.2f}"


def _build_av_params(function: str, api_key: str) -> dict[str, str]:
    """Build query parameters for an Alpha Vantage indicator request.

    Args:
        function: AV function name (e.g. "CPI", "REAL_GDP").
        api_key: Alpha Vantage API key.

    Returns:
        Dict of query params including interval where applicable.
    """
    params: dict[str, str] = {"function": function, "apikey": api_key}
    if function == "REAL_GDP":
        params["interval"] = "quarterly"
    elif function != "INFLATION":
        # Most indicators are monthly; INFLATION has no interval (annual)
        params["interval"] = "monthly"
    return params


class EconomicCalendarService:
    """Aggregates economic calendar data from multiple free sources.

    Caches all data in the ``economic_events`` DB table. The :meth:`refresh`
    method is called periodically by the main scheduler.

    Args:
        db: Database instance for persistence.
        alphavantage_api_key: Alpha Vantage API key for US macro indicators.
        policy_rate_fetcher: Existing BIS rate fetcher for G10 CB rates.
    """

    def __init__(
        self,
        db: Database,
        alphavantage_api_key: str = "",
        policy_rate_fetcher: PolicyRateFetcher | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            db: Database instance for caching events.
            alphavantage_api_key: AV key for US macro indicators. Empty = disabled.
            policy_rate_fetcher: Existing BIS rate fetcher. None = skip BIS data.
        """
        self._db: Database = db
        self._av_key: str = alphavantage_api_key
        self._rf_fetcher: PolicyRateFetcher | None = policy_rate_fetcher
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": "FlorinTerminal/1.0 (+https://github.com/florin-terminal)",
            },
        )
        # AV free tier: 25 requests/day, max 1 request/second.
        # Reuse the project's existing AsyncRateLimiter for pacing.
        self._av_limiter: AsyncRateLimiter = AsyncRateLimiter(
            max_requests=60, window_seconds=60, name="AV-EconCalendar",
        )
        self._last_cb_refresh: float = 0.0
        self._last_av_refresh: float = 0.0

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def get_events(
        self, start_date: str = "", end_date: str = "",
    ) -> list[dict]:
        """Read cached economic events from DB, filtered by date range.

        Args:
            start_date: YYYY-MM-DD lower bound (inclusive). Defaults to 1 year ago.
            end_date: YYYY-MM-DD upper bound (inclusive). Defaults to 1 year ahead.

        Returns:
            List of event dicts matching the EconomicEvent Pydantic model shape.
        """
        if not start_date:
            start_date = datetime.now().strftime("%Y-01-01")
        if not end_date:
            end_date = (datetime.now() + timedelta(days=730)).strftime("%Y-%m-%d")

        async with self._db.session() as session:
            stmt = (
                select(EconomicEventORM)
                .where(EconomicEventORM.date >= start_date)
                .where(EconomicEventORM.date <= end_date)
                .order_by(EconomicEventORM.date)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "date": r.date,
                "event": r.event,
                "importance": r.importance,
                "expected": r.expected,
                "actual": r.actual,
                "previous": r.previous,
                "country": r.country,
                "country_name": r.country_name,
                "institution": r.institution,
                "category": r.category,
                "description": r.description,
                "frequency": r.frequency,
                "unit": r.unit,
                "indicator_key": r.indicator_key,
                "source": r.source,
            }
            for r in rows
        ]

    async def get_indicator_history(
        self, indicator_key: str, limit: int = 24,
    ) -> list[dict]:
        """Return historical readings for a specific indicator.

        **DB-first strategy:** Always reads from the ``economic_events`` table
        first (populated by the scheduled refresh). Only falls back to a live
        API call if the DB has no data for this indicator yet.

        For CB rate indicators, the BIS CBPOL API provides monthly timeseries
        with end-of-month dates suitable for charting.

        Args:
            indicator_key: e.g. "us_cpi", "ecb_rate", "fed_rate"
            limit: Maximum number of data points to return.

        Returns:
            List of ``{"date": str, "value": str}`` sorted by date ascending.
        """
        # 1. Try DB cache first (fast, no API call, always preferred)
        db_history = await self._read_history_from_db(indicator_key, limit)
        if db_history:
            return db_history

        # 2. DB empty — try a live API fetch as fallback
        # For CB rates, BIS provides monthly timeseries
        bis_code = _indicator_key_to_bis_code(indicator_key)
        if bis_code:
            return await self._fetch_bis_rate_history(bis_code, limit)

        # For AV indicators, live fetch (rate-limited)
        if indicator_key in AV_INDICATORS and self._av_key:
            cfg = AV_INDICATORS[indicator_key]
            return await self._fetch_av_history(cfg["function"], limit)

        return []

    async def _read_history_from_db(
        self, indicator_key: str, limit: int,
    ) -> list[dict]:
        """Read historical readings for an indicator from the DB cache.

        Returns:
            List of ``{"date": str, "value": str}`` sorted oldest first.
            Empty list if no data found.
        """
        async with self._db.session() as session:
            stmt = (
                select(EconomicEventORM)
                .where(EconomicEventORM.indicator_key == indicator_key)
                .where(EconomicEventORM.actual != "")
                .order_by(EconomicEventORM.date.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            return []
        return [{"date": r.date, "value": r.actual} for r in reversed(rows)]

    async def refresh(self) -> None:
        """Orchestrate data refresh from all sources.

        Called periodically by the main scheduler. Respects rate limits:
        - CB meeting dates: refreshed every 24 hours
        - AV indicators: refreshed every 6 hours
        """
        now = time.time()

        # Refresh CB meeting dates (daily)
        if now - self._last_cb_refresh > _CB_REFRESH_INTERVAL:
            logger.info("Refreshing central bank meeting dates")
            await self._refresh_cb_data()
            self._last_cb_refresh = now

        # Refresh AV indicators (every 6 hours)
        if self._av_key and now - self._last_av_refresh > _AV_REFRESH_INTERVAL:
            logger.info("Refreshing Alpha Vantage economic indicators")
            await self._refresh_av_indicators()
            self._last_av_refresh = now

    # -----------------------------------------------------------------------
    # CB data refresh — orchestrator
    # -----------------------------------------------------------------------

    async def _refresh_cb_data(self) -> None:
        """Fetch and persist CB meeting dates + rate values.

        Each source is fetched independently — a failure in one does NOT
        prevent others from being collected. This is intentional: stale
        ECB data should not prevent fresh FOMC data from being stored.
        """
        all_events: list[EconomicEventORM] = []

        # API-based sources
        for fetcher, name in [
            (self._fetch_fed_decisions, "Fed RSS"),
            (self._fetch_ecb_rate_history, "ECB API"),
            (self._fetch_boc_rate_history, "BOC API"),
        ]:
            try:
                events = await fetcher()
                all_events.extend(events)
                logger.info("Fetched %d events from %s", len(events), name)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                logger.error("Failed to fetch from %s: %s", name, exc)

        # BIS rate data → rate decision events
        if self._rf_fetcher:
            try:
                events = await self._build_bis_rate_events()
                all_events.extend(events)
                logger.info("Built %d rate events from BIS data", len(events))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.error("Failed to build BIS rate events: %s", exc)

        # HTML-parsed upcoming meeting dates
        for parser, name in [
            (self._parse_fomc_upcoming, "FOMC calendar"),
            (self._parse_ecb_upcoming, "ECB calendar"),
            (self._parse_boe_upcoming, "BOE MPC"),
            (self._parse_boj_upcoming, "BOJ MPM"),
        ]:
            try:
                events = await parser()
                all_events.extend(events)
                logger.info("Parsed %d dates from %s", len(events), name)
            except (httpx.HTTPError, ValueError, IndexError, TypeError) as exc:
                logger.error("Failed to parse %s: %s", name, exc)

        # Persist
        await self._upsert_events(all_events)

    # -----------------------------------------------------------------------
    # API-based fetchers
    # -----------------------------------------------------------------------

    async def _fetch_fed_decisions(self) -> list[EconomicEventORM]:
        """Get past FOMC decisions from the Fed monetary policy RSS feed.

        Feed URL: https://www.federalreserve.gov/feeds/press_monetary.xml
        Items with 'FOMC statement' in the title are rate decisions.
        """
        try:
            resp = await self._client.get(_FED_RSS_URL)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch Fed RSS feed")
            return []

        events: list[EconomicEventORM] = []
        items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)

        for item in items:
            title_m = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
            date_m = re.search(r"<pubDate>(.*?)</pubDate>", item, re.DOTALL)
            if not title_m or not date_m:
                continue

            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title_m.group(1)).strip()
            if "FOMC statement" not in title:
                continue

            raw_date = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", date_m.group(1)).strip()
            try:
                dt = datetime.strptime(raw_date, "%a, %d %b %Y %H:%M:%S %Z")
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

            events.append(EconomicEventORM(
                event_key=f"fomc_decision_{date_str}",
                date=date_str,
                event="FOMC Rate Decision",
                country="US",
                country_name="United States",
                institution="Federal Reserve",
                category="Monetary Policy",
                importance="high",
                description="Federal Open Market Committee interest rate decision and policy statement.",
                frequency="8x/year",
                source="fed_rss",
                indicator_key="fed_rate",
                fetched_at=datetime.now(UTC),
            ))

        return events

    async def _fetch_ecb_rate_history(self) -> list[EconomicEventORM]:
        """Fetch ECB main refinancing rate history from ECB Data Portal API.

        Returns rate observations as economic events. Real dates from the API.
        """
        try:
            resp = await self._client.get(_ECB_RATE_URL)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch ECB rate data")
            return []

        events: list[EconomicEventORM] = []
        try:
            datasets = data.get("dataSets", [{}])
            if not datasets:
                return []

            series = datasets[0].get("series", {})
            if not series:
                return []

            # Get observations from first series
            obs = list(series.values())[0].get("observations", {})

            # Get time periods from structure
            dims = data.get("structure", {}).get("dimensions", {}).get("observation", [])
            time_dim = next((d for d in dims if d.get("id") == "TIME_PERIOD"), None)
            if not time_dim:
                return []

            dates = time_dim.get("values", [])

            prev_rate = ""
            for idx_str, values in sorted(obs.items(), key=lambda x: int(x[0])):
                idx = int(idx_str)
                if idx >= len(dates):
                    continue

                date_str = dates[idx].get("id", "")
                rate_val = values[0] if values else None
                if rate_val is None or date_str == "":
                    continue

                rate_str = f"{rate_val:.2f}%"
                events.append(EconomicEventORM(
                    event_key=f"ecb_rate_{date_str}",
                    date=date_str,
                    event="ECB Main Refinancing Rate",
                    country="EU",
                    country_name="Eurozone",
                    institution="European Central Bank",
                    category="Monetary Policy",
                    importance="high",
                    actual=rate_str,
                    previous=prev_rate,
                    unit="%",
                    description="ECB main refinancing operations rate (minimum bid rate).",
                    frequency="6-week cycle",
                    source="ecb_api",
                    indicator_key="ecb_rate",
                    fetched_at=datetime.now(UTC),
                ))
                prev_rate = rate_str

        except (KeyError, IndexError, TypeError, ValueError):
            logger.exception("Failed to parse ECB rate data")

        return events

    async def _fetch_boc_rate_history(self) -> list[EconomicEventORM]:
        """Fetch Bank of Canada policy rate from Valet API.

        Returns daily rate observations. We detect rate changes to create events.
        """
        try:
            resp = await self._client.get(_BOC_RATE_URL)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch BOC rate data")
            return []

        events: list[EconomicEventORM] = []
        observations = data.get("observations", [])

        prev_rate = ""
        for obs in observations:
            date_str = obs.get("d", "")
            rate_val = obs.get("V39079", {}).get("v", "")
            if not date_str or not rate_val:
                continue

            rate_str = f"{float(rate_val):.2f}%"

            # Only create event on rate changes (or first observation)
            if rate_str != prev_rate:
                events.append(EconomicEventORM(
                    event_key=f"boc_rate_{date_str}",
                    date=date_str,
                    event="BOC Policy Rate Decision",
                    country="CA",
                    country_name="Canada",
                    institution="Bank of Canada",
                    category="Monetary Policy",
                    importance="high",
                    actual=rate_str,
                    previous=prev_rate,
                    unit="%",
                    description="Bank of Canada overnight rate target.",
                    frequency="8x/year",
                    source="boc_api",
                    indicator_key="boc_rate",
                    fetched_at=datetime.now(UTC),
                ))
            prev_rate = rate_str

        return events

    async def _build_bis_rate_events(self) -> list[EconomicEventORM]:
        """Build rate decision events from BIS data for all G10 central banks.

        Uses the existing PolicyRateFetcher to get current rates,
        then creates one event per country with the current rate.
        """
        if not self._rf_fetcher:
            return []

        rates = await self._rf_fetcher.get_rates()
        events: list[EconomicEventORM] = []

        for r in rates:
            code = r.get("country_code", "")
            eff_date = r.get("effective_date", "")
            if not code or not eff_date:
                continue

            meta = G10_COUNTRIES.get(code, {})
            rate_str = f"{r['rate']:.2f}%"

            events.append(EconomicEventORM(
                event_key=f"bis_{code.lower()}_rate_{eff_date}",
                date=eff_date,
                event=f"{meta.get('central_bank', code)} Policy Rate",
                country=code if code != "XM" else "EU",
                country_name=meta.get("country", ""),
                institution=meta.get("central_bank", ""),
                category="Monetary Policy",
                importance="high",
                actual=rate_str,
                unit="%",
                description=f"Policy rate for {meta.get('country', code)}.",
                frequency="Varies",
                source="bis",
                indicator_key=f"{code.lower()}_rate",
                fetched_at=datetime.now(UTC),
            ))

        return events

    # -----------------------------------------------------------------------
    # HTML parsers for upcoming CB meeting dates
    # -----------------------------------------------------------------------

    async def _parse_fomc_upcoming(self) -> list[EconomicEventORM]:
        """Parse FOMC meeting dates from the Fed calendar page.

        Verified: HTTP 200, not bot-blocked. The page groups meetings by year
        (e.g. "2026 FOMC Meetings") with each meeting listed as:
          Month\\n  DD-DD  (e.g. "January\\n27-28" or "March\\n18")
        We extract year from section headers, then parse month + day ranges.
        """
        try:
            resp = await self._client.get(_FED_CALENDAR_URL)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch FOMC calendar page")
            return []

        events: list[EconomicEventORM] = []
        today = datetime.now().strftime("%Y-%m-%d")
        seen: set[str] = set()
        html = resp.text

        # The Fed page groups meetings by year with headers like "2026 FOMC Meetings".
        # Within each year section, meetings are listed as:
        #   Month              (standalone line, e.g. "January")
        #   DD-DD              (day range on next line, e.g. "27-28" or "18")
        # We split by year header, then parse line-by-line within each section.
        year_sections = re.split(r"(\d{4})\s+FOMC\s+Meetings", html)

        _month_re = re.compile(
            r"^(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)$"
        )
        _day_re = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?\*?$")

        for i in range(1, len(year_sections) - 1, 2):
            try:
                year = int(year_sections[i])
            except ValueError:
                continue

            section = year_sections[i + 1]
            clean = re.sub(r"<[^>]+>", "\n", section)
            lines = [ln.strip() for ln in clean.split("\n") if ln.strip()]

            j = 0
            while j < len(lines):
                m_match = _month_re.match(lines[j])
                if m_match and j + 1 < len(lines):
                    d_match = _day_re.match(lines[j + 1])
                    if d_match:
                        month_str = m_match.group(1)
                        # Use last day of range (the decision day)
                        day = d_match.group(2) or d_match.group(1)
                        try:
                            dt = datetime.strptime(
                                f"{month_str} {day} {year}", "%B %d %Y",
                            )
                            date_str = dt.strftime("%Y-%m-%d")
                        except ValueError:
                            j += 2
                            continue

                        if date_str >= today and date_str not in seen:
                            seen.add(date_str)
                            events.append(EconomicEventORM(
                                event_key=f"fomc_meeting_{date_str}",
                                date=date_str,
                                event="FOMC Meeting",
                                country="US",
                                country_name="United States",
                                institution="Federal Reserve",
                                category="Monetary Policy",
                                importance="high",
                                actual="",
                                description="Federal Open Market Committee policy meeting.",
                                frequency="8x/year",
                                source="fed_calendar",
                                indicator_key="fed_rate",
                                fetched_at=datetime.now(UTC),
                            ))
                        j += 2
                        continue
                j += 1

        return events

    async def _parse_ecb_upcoming(self) -> list[EconomicEventORM]:
        """Parse ECB Governing Council meeting dates from their calendar page.

        Verified: HTTP 200, not bot-blocked. Dates appear as
        "19 March 2026", "1 January 2026", etc.
        """
        try:
            resp = await self._client.get(_ECB_CALENDAR_URL)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch ECB calendar page")
            return []

        date_pattern = (
            r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{4})"
        )
        raw_dates = re.findall(date_pattern, resp.text)

        events: list[EconomicEventORM] = []
        today = datetime.now().strftime("%Y-%m-%d")
        seen: set[str] = set()

        for raw in raw_dates:
            try:
                dt = datetime.strptime(raw.strip(), "%d %B %Y")
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

            if date_str <= today or date_str in seen:
                continue

            # Filter out epoch dates and implausible dates
            if dt.year < 2024:
                continue
            seen.add(date_str)

            events.append(EconomicEventORM(
                event_key=f"ecb_gc_{date_str}",
                date=date_str,
                event="ECB Governing Council Meeting",
                country="EU",
                country_name="Eurozone",
                institution="European Central Bank",
                category="Monetary Policy",
                importance="high",
                description="ECB Governing Council monetary policy meeting.",
                frequency="6-week cycle",
                source="ecb_calendar",
                indicator_key="ecb_rate",
                fetched_at=datetime.now(UTC),
            ))

        return events

    async def _parse_boe_upcoming(self) -> list[EconomicEventORM]:
        """Parse Bank of England MPC meeting dates from their page.

        Verified: HTTP 200, not bot-blocked. Dates appear as
        "30 April 2026", "02 April 2026", etc.
        """
        try:
            resp = await self._client.get(_BOE_MPC_URL)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch BOE MPC dates page")
            return []

        date_pattern = (
            r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{4})"
        )
        raw_dates = re.findall(date_pattern, resp.text)

        events: list[EconomicEventORM] = []
        today = datetime.now().strftime("%Y-%m-%d")
        seen: set[str] = set()

        for raw in raw_dates:
            try:
                dt = datetime.strptime(raw.strip(), "%d %B %Y")
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

            if date_str <= today or date_str in seen:
                continue
            seen.add(date_str)

            events.append(EconomicEventORM(
                event_key=f"boe_mpc_{date_str}",
                date=date_str,
                event="BOE MPC Meeting",
                country="GB",
                country_name="United Kingdom",
                institution="Bank of England",
                category="Monetary Policy",
                importance="high",
                description="Bank of England Monetary Policy Committee interest rate decision.",
                frequency="8x/year",
                source="boe_calendar",
                indicator_key="gb_rate",
                fetched_at=datetime.now(UTC),
            ))

        return events

    async def _parse_boj_upcoming(self) -> list[EconomicEventORM]:
        """Parse Bank of Japan MPM meeting dates from their schedule page.

        Verified: HTTP 200. Dates appear as "May 7", "June 19", etc.
        without year — we infer the year from context (current/next year).
        """
        try:
            resp = await self._client.get(_BOJ_SCHEDULE_URL)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch BOJ schedule page")
            return []

        # BOJ uses month-day format without year
        date_pattern = (
            r"((?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{1,2})"
        )
        raw_dates = re.findall(date_pattern, resp.text)

        events: list[EconomicEventORM] = []
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        seen: set[str] = set()

        for raw in raw_dates:
            # Try current year first, then next year
            for year in [now.year, now.year + 1]:
                try:
                    dt = datetime.strptime(f"{raw.strip()} {year}", "%B %d %Y")
                    date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue

                if date_str > today and date_str not in seen:
                    seen.add(date_str)
                    events.append(EconomicEventORM(
                        event_key=f"boj_mpm_{date_str}",
                        date=date_str,
                        event="BOJ Monetary Policy Meeting",
                        country="JP",
                        country_name="Japan",
                        institution="Bank of Japan",
                        category="Monetary Policy",
                        importance="high",
                        description="Bank of Japan Monetary Policy Meeting.",
                        frequency="8x/year",
                        source="boj_calendar",
                        indicator_key="jp_rate",
                        fetched_at=datetime.now(UTC),
                    ))
                    break  # Use the first valid year match

        return events

    # -----------------------------------------------------------------------
    # Alpha Vantage indicator refresh
    # -----------------------------------------------------------------------

    async def _refresh_av_indicators(self) -> None:
        """Fetch and persist US economic indicator values from Alpha Vantage.

        Each indicator returns a time series with real dates and values.
        We store the most recent readings as economic events.

        Uses :class:`AsyncRateLimiter` to pace requests at max 1/second,
        respecting AV's free-tier rate limit.
        """
        if not self._av_key:
            return

        all_events: list[EconomicEventORM] = []

        for key, cfg in AV_INDICATORS.items():
            await self._av_limiter.acquire()
            try:
                events = await self._fetch_av_indicator(key, cfg)
                all_events.extend(events)
                logger.info("Fetched %d readings for %s", len(events), key)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("Failed to fetch AV indicator %s: %s", key, exc)

        await self._upsert_events(all_events)

    async def _fetch_av_indicator(
        self, key: str, cfg: dict[str, str],
    ) -> list[EconomicEventORM]:
        """Fetch a single AV indicator time series and create events.

        Uses real dates from the API response — not generated.

        Args:
            key: Indicator key (e.g. "us_cpi").
            cfg: Indicator config from AV_INDICATORS.

        Returns:
            List of EconomicEventORM for the most recent readings.
        """
        params = _build_av_params(cfg["function"], self._av_key)

        try:
            resp = await self._client.get(_AV_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch AV indicator %s", key)
            return []

        # Check for error responses
        if "Error Message" in data or "Information" in data:
            msg = data.get("Error Message") or data.get("Information", "")
            logger.warning("AV returned error for %s: %s", key, msg[:200])
            return []

        readings = data.get("data", [])
        if not readings:
            return []

        unit = cfg["unit"]
        events: list[EconomicEventORM] = []
        for i, reading in enumerate(readings[:24]):
            date_str = reading.get("date", "")
            value = reading.get("value", "")
            if not date_str or not value or value == ".":
                continue

            formatted = _format_av_value(value, unit)

            # Previous value = next entry in the list (older)
            prev_value = ""
            if i + 1 < len(readings):
                pv = readings[i + 1].get("value", "")
                if pv and pv != ".":
                    prev_value = _format_av_value(pv, unit)

            events.append(EconomicEventORM(
                event_key=f"{key}_{date_str}",
                date=date_str,
                event=cfg["event"],
                country="US",
                country_name="United States",
                institution=cfg["institution"],
                category=cfg["category"],
                importance=cfg["importance"],
                actual=formatted,
                previous=prev_value,
                unit=cfg["unit"],
                description=cfg["description"],
                frequency=cfg["frequency"],
                source="alpha_vantage",
                indicator_key=key,
                fetched_at=datetime.now(UTC),
            ))

        return events

    async def _fetch_av_history(
        self, function: str, limit: int,
    ) -> list[dict]:
        """Fetch raw historical readings from Alpha Vantage for a chart.

        Rate-limited via ``_av_limiter`` to respect AV free-tier limits.

        Args:
            function: AV function name (e.g. "CPI", "NONFARM_PAYROLL").
            limit: Maximum data points.

        Returns:
            List of ``{"date": str, "value": str}`` sorted oldest first.
        """
        await self._av_limiter.acquire()
        params = _build_av_params(function, self._av_key)

        try:
            resp = await self._client.get(_AV_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch AV history for %s", function)
            return []

        readings = data.get("data", [])
        result = []
        for r in readings[:limit]:
            date = r.get("date", "")
            value = r.get("value", "")
            if date and value and value != ".":
                result.append({"date": date, "value": value})

        # Return sorted oldest first (AV returns newest first)
        result.reverse()
        return result

    async def _fetch_bis_rate_history(
        self, bis_code: str, limit: int,
    ) -> list[dict]:
        """Fetch monthly policy rate timeseries from the BIS CBPOL API.

        Returns end-of-month rate observations for a single country.
        The BIS API returns monthly data (e.g. "2025-01", "2025-02") which
        we convert to end-of-month dates for charting.

        Args:
            bis_code: BIS country code (e.g. "US", "XM", "GB").
            limit: Maximum number of months to return.

        Returns:
            List of ``{"date": "YYYY-MM-DD", "value": "X.XX"}`` oldest first.
        """
        start_dt = datetime.now() - timedelta(days=limit * 31)
        start_period = start_dt.strftime("%Y-%m")
        url = _BIS_RATE_HISTORY_URL.format(code=bis_code, start=start_period)

        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch BIS rate history for %s", bis_code)
            return []

        try:
            reader = csv.DictReader(io.StringIO(resp.text))
            result: list[dict] = []
            for row in reader:
                period = (row.get("TIME_PERIOD") or "").strip()
                value = (row.get("OBS_VALUE") or "").strip()
                if not period or not value or value == "NaN":
                    continue

                # Convert "YYYY-MM" → end-of-month "YYYY-MM-DD"
                try:
                    year, month = int(period[:4]), int(period[5:7])
                    last_day = _calendar_mod.monthrange(year, month)[1]
                    date_str = f"{year}-{month:02d}-{last_day:02d}"
                except (ValueError, IndexError):
                    continue

                result.append({"date": date_str, "value": value})

            # BIS CSV is chronological — already oldest first
            return result[-limit:]

        except (KeyError, ValueError):
            logger.exception("Failed to parse BIS rate history CSV for %s", bis_code)
            return []

    # -----------------------------------------------------------------------
    # DB persistence
    # -----------------------------------------------------------------------

    async def _upsert_events(self, events: list[EconomicEventORM]) -> None:
        """Insert or update economic events in the database.

        Uses event_key as the unique constraint for upsert logic.
        """
        if not events:
            return

        try:
            async with self._db.session() as session:
                for ev in events:
                    # Check if exists
                    result = await session.execute(
                        select(EconomicEventORM).where(
                            EconomicEventORM.event_key == ev.event_key
                        )
                    )
                    existing = result.scalar()

                    if existing:
                        # Update mutable fields
                        existing.actual = ev.actual or existing.actual
                        existing.previous = ev.previous or existing.previous
                        existing.expected = ev.expected or existing.expected
                        existing.fetched_at = ev.fetched_at
                        # Update description/metadata in case it improved
                        if ev.description:
                            existing.description = ev.description
                        if ev.institution:
                            existing.institution = ev.institution
                    else:
                        session.add(ev)

                await session.commit()
        except (OSError, sqlalchemy_exc.SQLAlchemyError):
            logger.exception("Failed to upsert %d economic events", len(events))
