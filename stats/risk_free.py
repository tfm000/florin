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
        """Fetch today's rate for all G10 currencies. Idempotent per day."""
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=5)).isoformat()  # cover weekends

        for currency in BENCHMARKS:
            if self._last_fetch.get(currency) == today:
                continue
            try:
                observations = await self._dispatch_fetch(currency, yesterday, today)
                if observations:
                    await self._store(observations)
                self._last_fetch[currency] = today
            except Exception:
                logger.exception("refresh_today failed for %s", currency)

    async def get_daily_rates(
        self, currency: str, dates: list[str]
    ) -> np.ndarray:
        """Get daily risk-free rates aligned to *dates*.

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
            return np.zeros(len(dates), dtype=np.float64)

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
        return await fn(start, end)

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
            "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
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
        resp = await self._client.get(url, headers=headers)
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
        """JPY TONA (uncollateralised overnight call rate) from the BoJ."""
        try:
            return await self._fetch_tona_api(start, end)
        except Exception:
            logger.debug("BoJ REST API failed for TONA")
            return []

    async def _fetch_tona_api(self, start: str, end: str) -> list[RateObservation]:
        """BoJ REST API (launched Feb 2026)."""
        url = (
            "https://www.stat-search.boj.or.jp/api/getDataCode"
            f"?code=FM01'STRDCLUCON&from={start.replace('-', '')}"
            f"&to={end.replace('-', '')}&format=json"
        )
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()

        observations = []
        for item in data.get("data", []):
            try:
                raw_date = str(item.get("date", ""))
                if len(raw_date) == 8:
                    d = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                else:
                    d = raw_date
                val = item.get("value")
                if val is not None:
                    observations.append(RateObservation(
                        currency="JPY", benchmark="TONA",
                        date=d, rate=float(val), source="Bank of Japan API",
                    ))
            except (ValueError, KeyError):
                continue
        return observations

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
        """NOK NOWA from Norges Bank SDMX API."""
        url = (
            "https://data.norges-bank.no/api/data/SHORT_RATES/.NOWA"
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
                if d and val:
                    observations.append(RateObservation(
                        currency="NOK", benchmark="NOWA",
                        date=d, rate=float(val), source="Norges Bank API",
                    ))
            except (ValueError, KeyError):
                continue
        return observations

    async def _fetch_ocr(self, start: str, end: str) -> list[RateObservation]:
        """NZD OCR from the RBNZ (Excel download).

        Falls back to empty if openpyxl is not available.
        """
        url = (
            "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files"
            "/statistics/series/b/b2/hb2-daily-close.xlsx"
        )
        try:
            import openpyxl
        except ImportError:
            logger.warning("openpyxl not installed — cannot fetch RBNZ OCR data")
            return []

        resp = await self._client.get(url)
        resp.raise_for_status()

        observations = []
        wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
        ws = wb.active

        # Find the OCR column
        ocr_col = None
        header_row = None
        for row in ws.iter_rows(max_row=10, values_only=False):
            for cell in row:
                val = str(cell.value or "").lower()
                if "official cash rate" in val or "ocr" in val:
                    ocr_col = cell.column - 1
                    header_row = cell.row
                    break
            if ocr_col is not None:
                break

        if ocr_col is None or header_row is None:
            wb.close()
            return []

        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            try:
                raw_date = row[0]
                if isinstance(raw_date, datetime):
                    d = raw_date.strftime("%Y-%m-%d")
                elif isinstance(raw_date, str):
                    d = raw_date[:10]
                else:
                    continue

                if d < start or d > end:
                    continue

                val = row[ocr_col]
                if val is not None:
                    observations.append(RateObservation(
                        currency="NZD", benchmark="OCR",
                        date=d, rate=float(val), source="RBNZ B2 Table",
                    ))
            except (ValueError, IndexError, TypeError):
                continue

        wb.close()
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
