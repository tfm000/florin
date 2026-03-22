"""
G10 overnight benchmark rate fetcher.

Fetches risk-free rates from central bank APIs and persists them in
the database. One fetch per currency per day — subsequent requests
serve from the DB.

Supported benchmarks:
  USD → SOFR   (NY Fed)         GBP → SONIA  (BoE)
  EUR → ESTR   (ECB)            JPY → TONA   (BoJ)
  CAD → CORRA  (BoC)            AUD → Cash   (RBA)
  CHF → SARON  (SNB)            SEK → SWESTR (Riksbank)
  NOK → NOWA   (Norges Bank)    NZD → OCR    (RBNZ)
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import numpy as np
from sqlalchemy import select

if TYPE_CHECKING:
    from db.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BENCHMARKS: dict[str, str] = {
    "USD": "SOFR",
    "GBP": "SONIA",
    "EUR": "ESTR",
    "JPY": "TONA",
    "CAD": "CORRA",
    "AUD": "CASH_RATE",
    "CHF": "SARON",
    "SEK": "SWESTR",
    "NOK": "NOWA",
    "NZD": "OCR",
}

# Day count conventions for overnight benchmark rates.
# ACT/360: SOFR, ESTR, SARON, SWESTR, NOWA
# ACT/365: SONIA, TONA, CORRA, RBA Cash Rate, OCR
_DAY_COUNT_BASIS: dict[str, int] = {
    "USD": 360,  # SOFR — ACT/360
    "GBP": 365,  # SONIA — ACT/365
    "EUR": 360,  # ESTR — ACT/360
    "JPY": 365,  # TONA — ACT/365
    "CAD": 365,  # CORRA — ACT/365
    "AUD": 365,  # RBA Cash Rate — ACT/365
    "CHF": 360,  # SARON — ACT/360
    "SEK": 360,  # SWESTR — ACT/360
    "NOK": 360,  # NOWA — ACT/360
    "NZD": 365,  # OCR — ACT/365
}

_RATE_LOCK = asyncio.Lock()
_MIN_INTERVAL = 1.0  # 1 req/s per source — conservative


def _normalize_date(s: str) -> str:
    """Extract YYYY-MM-DD from any date/datetime string.

    yfinance returns dates like '2025-03-21 00:00:00-04:00' — we only
    need the date portion for DB queries and central bank API calls.
    """
    return s[:10]


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class RateObservation:
    currency: str
    benchmark: str
    date: str        # YYYY-MM-DD
    rate: float      # annual %
    source: str


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class RiskFreeRateFetcher:
    """Fetches and caches G10 overnight benchmark rates.

    Strategy:
    - On first request for a currency+range, backfills from the central
      bank API and stores in DB.
    - Subsequent requests serve from DB (one fetch per currency per day).
    - ``refresh_today()`` is called daily by a background task.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": (
                    "PennyStockSentinel/1.0 "
                    "(+https://github.com/penny-stock-sentinel)"
                ),
            },
        )
        self._last_fetch: dict[str, str] = {}  # currency → last-fetch date
        self._last_request_time: float = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    # -- rate limiting -----------------------------------------------------

    async def _rate_limit(self) -> None:
        async with _RATE_LOCK:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()

    # -- public API --------------------------------------------------------

    async def ensure_rates(self, currency: str, start: str, end: str) -> None:
        """Ensure DB has rates for [start, end]. Fetches only missing ranges."""
        currency = currency.upper()
        start = _normalize_date(start)
        end = _normalize_date(end)
        if currency not in BENCHMARKS:
            return

        from db.models import RiskFreeRateORM

        # Check what we already have
        async with self._db.session() as session:
            result = await session.execute(
                select(RiskFreeRateORM.date)
                .where(RiskFreeRateORM.currency == currency)
                .where(RiskFreeRateORM.date >= start)
                .where(RiskFreeRateORM.date <= end)
            )
            existing = {row[0] for row in result.all()}

        if existing:
            # Check if we have reasonable coverage (at least 60% of business days)
            d_start = date.fromisoformat(start)
            d_end = date.fromisoformat(end)
            expected_days = max(1, (d_end - d_start).days * 5 // 7)
            if len(existing) >= expected_days * 0.6:
                return

        # Fetch from central bank
        try:
            observations = await self._dispatch_fetch(currency, start, end)
            if observations:
                await self._store(observations)
        except Exception:
            logger.exception("Failed to fetch %s rates", currency)

    async def refresh_today(self) -> None:
        """Fetch today's rate for all G10 currencies. Idempotent per day.

        On startup, checks the DB first — if a currency already has a rate
        for today (or the most recent business day), it skips the HTTP fetch.
        """
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=5)).isoformat()  # cover weekends

        # Hydrate _last_fetch from DB so we don't re-fetch on every restart
        if not self._last_fetch:
            await self._hydrate_last_fetch(yesterday, today)

        # Collect all observations first, then store in a single DB transaction
        # to avoid SQLite "database is locked" errors from concurrent writes.
        all_observations: list[RateObservation] = []
        for currency in BENCHMARKS:
            if self._last_fetch.get(currency) == today:
                continue
            try:
                observations = await self._dispatch_fetch(currency, yesterday, today)
                if observations:
                    all_observations.extend(observations)
                    self._last_fetch[currency] = today
                else:
                    # Don't mark as fetched — allows retry later when data
                    # becomes available (e.g. SNB publishes SARON with a lag).
                    logger.debug("No observations returned for %s", currency)
            except Exception:
                logger.exception("refresh_today failed for %s", currency)

        if all_observations:
            await self._store(all_observations)

    async def _hydrate_last_fetch(self, start: str, today: str) -> None:
        """Populate _last_fetch from DB so restarts don't re-fetch.

        For each currency, if we already have a rate fetched within the
        last 24 hours (by fetched_at timestamp), skip the HTTP request.
        """
        from db.models import RiskFreeRateORM

        cutoff = datetime.now() - timedelta(hours=24)
        async with self._db.session() as session:
            for currency in BENCHMARKS:
                result = await session.execute(
                    select(RiskFreeRateORM.date)
                    .where(RiskFreeRateORM.currency == currency)
                    .where(RiskFreeRateORM.fetched_at >= cutoff)
                    .order_by(RiskFreeRateORM.fetched_at.desc())
                    .limit(1)
                )
                row = result.first()
                if row:
                    self._last_fetch[currency] = today
                    logger.debug(
                        "%s: rate for %s fetched within 24h, skipping",
                        currency, row[0],
                    )

    async def get_daily_rates(
        self, currency: str, dates: list[str]
    ) -> np.ndarray:
        """Get daily risk-free rates aligned to *dates*.

        *dates* may contain full datetime strings (e.g. from yfinance);
        only the ``YYYY-MM-DD`` prefix is used.

        Returns array in DECIMAL form, converted using the correct day
        count convention for each benchmark:

        - ACT/360 (SOFR, ESTR, SARON, SWESTR, NOWA):
          daily_rate = annual_pct / 100 / 360
        - ACT/365 (SONIA, TONA, CORRA, RBA Cash, OCR):
          daily_rate = annual_pct / 100 / 365

        Forward-fills missing dates (weekends/holidays).
        """
        currency = currency.upper()
        if not dates or currency not in BENCHMARKS:
            return np.zeros(len(dates) if dates else 0, dtype=np.float64)

        # Normalize dates — yfinance may pass full datetime strings
        dates = [_normalize_date(d) for d in dates]

        # Ensure we have the data
        await self.ensure_rates(currency, dates[0], dates[-1])

        from db.models import RiskFreeRateORM

        async with self._db.session() as session:
            result = await session.execute(
                select(RiskFreeRateORM.date, RiskFreeRateORM.rate)
                .where(RiskFreeRateORM.currency == currency)
                .where(RiskFreeRateORM.date >= dates[0])
                .where(RiskFreeRateORM.date <= dates[-1])
                .order_by(RiskFreeRateORM.date)
            )
            rate_map: dict[str, float] = {row[0]: row[1] for row in result.all()}

        # Align to requested dates with forward-fill
        out = np.zeros(len(dates), dtype=np.float64)
        last_rate = 0.0
        # Also look back for a rate before the range for initial fill
        if dates[0] not in rate_map:
            async with self._db.session() as session:
                result = await session.execute(
                    select(RiskFreeRateORM.rate)
                    .where(RiskFreeRateORM.currency == currency)
                    .where(RiskFreeRateORM.date < dates[0])
                    .order_by(RiskFreeRateORM.date.desc())
                    .limit(1)
                )
                row = result.first()
                if row:
                    last_rate = row[0]

        for i, d in enumerate(dates):
            if d in rate_map:
                last_rate = rate_map[d]
            out[i] = last_rate

        # Convert: annual % → daily decimal using correct day count basis
        basis = _DAY_COUNT_BASIS.get(currency, 360)
        return out / 100.0 / basis

    async def get_current_rate(self, currency: str) -> tuple[float, str]:
        """Get the most recent rate for a currency. Returns (rate_annual_pct, source)."""
        currency = currency.upper()
        if currency not in BENCHMARKS:
            return (0.0, "unsupported currency")

        from db.models import RiskFreeRateORM

        async with self._db.session() as session:
            result = await session.execute(
                select(RiskFreeRateORM.rate, RiskFreeRateORM.source)
                .where(RiskFreeRateORM.currency == currency)
                .order_by(RiskFreeRateORM.date.desc())
                .limit(1)
            )
            row = result.first()

        if row:
            return (row[0], row[1])

        # Try fetching latest
        today = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        await self.ensure_rates(currency, week_ago, today)

        async with self._db.session() as session:
            result = await session.execute(
                select(RiskFreeRateORM.rate, RiskFreeRateORM.source)
                .where(RiskFreeRateORM.currency == currency)
                .order_by(RiskFreeRateORM.date.desc())
                .limit(1)
            )
            row = result.first()

        return (row[0], row[1]) if row else (0.0, "unavailable")

    # -- dispatch ----------------------------------------------------------

    async def _dispatch_fetch(
        self, currency: str, start: str, end: str
    ) -> list[RateObservation]:
        fetchers = {
            "USD": self._fetch_sofr,
            "GBP": self._fetch_sonia,
            "EUR": self._fetch_estr,
            "JPY": self._fetch_tona,
            "CAD": self._fetch_corra,
            "AUD": self._fetch_rba,
            "CHF": self._fetch_saron,
            "SEK": self._fetch_swestr,
            "NOK": self._fetch_nowa,
            "NZD": self._fetch_ocr,
        }
        fn = fetchers.get(currency)
        if not fn:
            return []
        await self._rate_limit()
        try:
            return await fn(start, end)
        except httpx.HTTPStatusError as e:
            logger.warning(
                "%s rate fetch returned HTTP %d for %s",
                currency, e.response.status_code, e.request.url,
            )
            return []
        except (httpx.RequestError, ValueError) as e:
            logger.warning("%s rate fetch failed: %s", currency, e)
            return []

    # -- storage -----------------------------------------------------------

    async def _store(self, observations: list[RateObservation]) -> None:
        from db.models import RiskFreeRateORM

        async with self._db.session() as session:
            for obs in observations:
                # Upsert: check existence first
                existing = await session.execute(
                    select(RiskFreeRateORM.id)
                    .where(RiskFreeRateORM.currency == obs.currency)
                    .where(RiskFreeRateORM.date == obs.date)
                )
                if existing.first():
                    continue
                session.add(RiskFreeRateORM(
                    id=uuid4().hex[:16],
                    currency=obs.currency,
                    benchmark=obs.benchmark,
                    date=obs.date,
                    rate=obs.rate,
                    source=obs.source,
                ))
            await session.commit()

    # -- per-currency fetchers --------------------------------------------

    async def _fetch_sofr(self, start: str, end: str) -> list[RateObservation]:
        """USD SOFR from the NY Fed Markets API.

        Endpoint: /api/rates/secured/sofr/search.json (rate type is in the path).
        """
        url = (
            "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"
            f"?startDate={start}&endDate={end}"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()

        observations = []
        for item in data.get("refRates", []):
            rate = item.get("percentRate")
            if rate is None:
                continue
            observations.append(RateObservation(
                currency="USD",
                benchmark="SOFR",
                date=item["effectiveDate"],
                rate=float(rate),
                source="NY Fed Markets API",
            ))
        return observations

    async def _fetch_sonia(self, start: str, end: str) -> list[RateObservation]:
        """GBP SONIA from the Bank of England.

        The BoE endpoint requires a browser-like User-Agent header,
        otherwise it returns HTML instead of CSV.
        """
        d_start = date.fromisoformat(start)
        d_end = date.fromisoformat(end)
        fmt_start = d_start.strftime("%d/%b/%Y")
        fmt_end = d_end.strftime("%d/%b/%Y")
        url = (
            "https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"
            f"?csv.x=yes&SeriesCodes=IUDSOIA&UsingCodes=Y"
            f"&Datefrom={fmt_start}&Dateto={fmt_end}&CSVF=TN&VPD=Y"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PennyStockSentinel/1.0; "
                "+https://github.com/penny-stock-sentinel)"
            ),
            "Accept": "text/csv, text/plain, */*",
        }
        resp = await self._client.get(url, headers=headers, follow_redirects=True)
        resp.raise_for_status()

        # BoE may return HTML on error — check content looks like CSV
        if resp.text.strip().startswith("<!") or "<html" in resp.text[:200].lower():
            logger.warning("BoE returned HTML instead of CSV for SONIA")
            return []

        observations = []
        reader = csv.reader(io.StringIO(resp.text))
        for row in reader:
            if len(row) < 2:
                continue
            try:
                # BoE date format: DD/Mon/YYYY or DD Mon YYYY
                d = _parse_boe_date(row[0].strip())
                rate = float(row[1].strip())
                observations.append(RateObservation(
                    currency="GBP", benchmark="SONIA",
                    date=d, rate=rate, source="Bank of England",
                ))
            except (ValueError, IndexError):
                continue
        return observations

    async def _fetch_estr(self, start: str, end: str) -> list[RateObservation]:
        """EUR ESTR from the ECB SDMX API."""
        url = (
            "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT"
            f"?startPeriod={start}&endPeriod={end}&format=csvdata&detail=dataonly"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()

        observations = []
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            try:
                d = row.get("TIME_PERIOD", "").strip()
                val = row.get("OBS_VALUE", "").strip()
                if d and val:
                    observations.append(RateObservation(
                        currency="EUR", benchmark="ESTR",
                        date=d, rate=float(val), source="ECB SDMX API",
                    ))
            except (ValueError, KeyError):
                continue
        return observations

    async def _fetch_tona(self, start: str, end: str) -> list[RateObservation]:
        """JPY TONA (uncollateralised overnight call rate average) from BoJ.

        Two formats depending on era:
        - Oct 2025+: XLSX files on www.boj.or.jp (cell C10 = average rate)
        - Pre-Oct 2025: HTML files on www3.boj.or.jp ([Avg.] X.XXX%)

        Files only exist for business days — weekends/holidays return 404.
        """
        d_start = date.fromisoformat(start)
        d_end = date.fromisoformat(end)
        # Oct 3, 2025 = first day of the new XLSX format
        xlsx_cutover = date(2025, 10, 3)
        observations = []

        current = d_start
        while current <= d_end:
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            d_str = current.isoformat()

            if current >= xlsx_cutover:
                obs = await self._fetch_tona_xlsx(current, d_str)
            else:
                obs = await self._fetch_tona_html(current, d_str)

            if obs is not None:
                observations.append(obs)

            current += timedelta(days=1)

        return observations

    async def _fetch_tona_xlsx(
        self, dt: date, d_str: str,
    ) -> RateObservation | None:
        """Fetch TONA from the new XLSX format (Oct 2025+)."""
        try:
            import openpyxl
        except ImportError:
            logger.warning("openpyxl not installed — cannot fetch BoJ TONA data")
            return None

        ymd = dt.strftime("%Y%m%d")
        yyyy = dt.strftime("%Y")
        urls = [
            (
                f"https://www.boj.or.jp/en/statistics/market/short/mutan"
                f"/d_release/md/{yyyy}/md{ymd}.xlsx"
            ),
            (
                f"https://www.boj.or.jp/en/statistics/market/short/mutan"
                f"/d_release/mp/mp{ymd}.xlsx"
            ),
        ]

        for url in urls:
            try:
                await self._rate_limit()
                resp = await self._client.get(url)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()

                wb = openpyxl.load_workbook(
                    io.BytesIO(resp.content), read_only=True, data_only=True,
                )
                ws = wb.active
                val = ws.cell(row=10, column=3).value
                wb.close()

                if val is not None:
                    return RateObservation(
                        currency="JPY", benchmark="TONA",
                        date=d_str, rate=float(val),
                        source="Bank of Japan",
                    )
            except Exception as e:
                logger.debug("BoJ TONA XLSX fetch failed for %s: %s", d_str, e)
                continue
        return None

    async def _fetch_tona_html(
        self, dt: date, d_str: str,
    ) -> RateObservation | None:
        """Fetch TONA from the old HTML format (pre-Oct 2025).

        URL: https://www3.boj.or.jp/market/en/stat/md{YYMMDD}.htm
        Page contains: [Avg.] 0.227%
        """
        yymmdd = dt.strftime("%y%m%d")
        url = f"https://www3.boj.or.jp/market/en/stat/md{yymmdd}.htm"

        try:
            await self._rate_limit()
            resp = await self._client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

            # HTML wraps values in tags: <STRONG>[Avg.]</STRONG> <SPAN ...>0.227%</SPAN>
            match = re.search(r"\[Avg\.\].*?([\d.]+)%", resp.text, re.DOTALL)
            if match:
                return RateObservation(
                    currency="JPY", benchmark="TONA",
                    date=d_str, rate=float(match.group(1)),
                    source="Bank of Japan",
                )
        except Exception as e:
            logger.debug("BoJ TONA HTML fetch failed for %s: %s", d_str, e)
        return None

    async def _fetch_corra(self, start: str, end: str) -> list[RateObservation]:
        """CAD CORRA from the Bank of Canada Valet API."""
        url = (
            "https://www.bankofcanada.ca/valet/observations/AVG.INTWO/json"
            f"?start_date={start}&end_date={end}"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()

        observations = []
        for obs in data.get("observations", []):
            try:
                d = obs["d"]
                val = obs.get("AVG.INTWO", {}).get("v")
                if val is not None:
                    observations.append(RateObservation(
                        currency="CAD", benchmark="CORRA",
                        date=d, rate=float(val), source="Bank of Canada Valet API",
                    ))
            except (ValueError, KeyError):
                continue
        return observations

    async def _fetch_rba(self, start: str, end: str) -> list[RateObservation]:
        """AUD Cash Rate from the RBA (static CSV download)."""
        url = "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"
        resp = await self._client.get(url)
        resp.raise_for_status()

        observations = []
        reader = csv.reader(io.StringIO(resp.text))
        header = None
        cash_rate_col = None

        for row in reader:
            if not row:
                continue
            # Find header row with "Cash Rate Target"
            if header is None:
                for i, cell in enumerate(row):
                    if "cash rate" in cell.lower() and "target" in cell.lower():
                        cash_rate_col = i
                        header = row
                        break
                continue

            if cash_rate_col is None or cash_rate_col >= len(row):
                continue

            try:
                raw_date = row[0].strip()
                d = _parse_rba_date(raw_date)
                if d < start or d > end:
                    continue
                val = row[cash_rate_col].strip()
                if val:
                    observations.append(RateObservation(
                        currency="AUD", benchmark="CASH_RATE",
                        date=d, rate=float(val), source="RBA F1 Table",
                    ))
            except (ValueError, IndexError):
                continue
        return observations

    async def _fetch_saron(self, start: str, end: str) -> list[RateObservation]:
        """CHF SARON from the SNB Data Portal."""
        url = (
            "https://data.snb.ch/api/cube/snbgwdzid/data/csv/en"
            f"?dimSel=D0(SARON)&fromDate={start}&toDate={end}"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()

        observations = []
        # SNB uses semicolon-delimited CSV
        reader = csv.reader(io.StringIO(resp.text), delimiter=";")
        header_found = False
        for row in reader:
            if not row or len(row) < 2:
                continue
            if not header_found:
                if "Date" in row[0] or "date" in row[0].lower():
                    header_found = True
                continue
            try:
                d = row[0].strip()
                val = row[-1].strip()
                if d and val:
                    observations.append(RateObservation(
                        currency="CHF", benchmark="SARON",
                        date=d, rate=float(val), source="SNB Data Portal",
                    ))
            except (ValueError, IndexError):
                continue
        return observations

    async def _fetch_swestr(self, start: str, end: str) -> list[RateObservation]:
        """SEK SWESTR from the Riksbank API."""
        url = (
            "https://api.riksbank.se/swestr/v1/all/SWESTR"
            f"?fromDate={start}&toDate={end}"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()

        observations = []
        items = data if isinstance(data, list) else data.get("data", data.get("rates", []))
        for item in items:
            try:
                d = item.get("date", item.get("effectiveDate", ""))
                rate = item.get("rate", item.get("interestRate"))
                if d and rate is not None:
                    observations.append(RateObservation(
                        currency="SEK", benchmark="SWESTR",
                        date=d[:10], rate=float(rate), source="Riksbank API",
                    ))
            except (ValueError, KeyError):
                continue
        return observations

    async def _fetch_nowa(self, start: str, end: str) -> list[RateObservation]:
        """NOK NOWA from Norges Bank SDMX API.

        The CSV is semicolon-delimited and contains multiple unit types
        (Transactions, Volume, Rate, Index, etc.). We filter for
        UNIT_MEASURE=R (Rate) rows only.
        """
        url = (
            "https://data.norges-bank.no/api/data/SHORT_RATES/.NOWA"
            f"?startPeriod={start}&endPeriod={end}&format=csv"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()

        observations = []
        reader = csv.DictReader(io.StringIO(resp.text), delimiter=";")
        for row in reader:
            try:
                # Only take Rate rows, not Transactions/Volume/Index
                if row.get("UNIT_MEASURE", "").strip() != "R":
                    continue
                d = row.get("TIME_PERIOD", "").strip()
                val = row.get("OBS_VALUE", "").strip()
                if d and val:
                    observations.append(RateObservation(
                        currency="NOK", benchmark="NOWA",
                        date=d, rate=float(val), source="Norges Bank API",
                    ))
            except (ValueError, KeyError):
                continue
        return observations

    async def _fetch_ocr(self, start: str, end: str) -> list[RateObservation]:
        """NZD OCR from the BIS central bank policy rates API.

        The RBNZ website blocks non-browser requests (HTTP 403), so we
        use the BIS SDMX API which mirrors the same RBNZ data daily.
        """
        url = (
            "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.NZ"
            f"?startPeriod={start}&endPeriod={end}&format=csv"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()

        observations = []
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            try:
                d = row.get("TIME_PERIOD", "").strip()
                val = row.get("OBS_VALUE", "").strip()
                if not d or not val or val == "NaN":
                    continue
                observations.append(RateObservation(
                    currency="NZD", benchmark="OCR",
                    date=d, rate=float(val), source="BIS (RBNZ OCR)",
                ))
            except (ValueError, KeyError):
                continue
        return observations


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def _parse_boe_date(s: str) -> str:
    """Parse BoE date format (e.g. '02 Jan 2024' or '02/Jan/2024') to YYYY-MM-DD."""
    for fmt in ("%d %b %Y", "%d/%b/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse BoE date: {s}")


def _parse_rba_date(s: str) -> str:
    """Parse RBA date format to YYYY-MM-DD."""
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse RBA date: {s}")
