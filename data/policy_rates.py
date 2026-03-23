"""
G10 central bank policy rate fetcher.

Fetches policy rates from the BIS CBPOL SDMX API and caches them
in-memory (24h TTL) and in the database for fallback.

The BIS API returns monthly observations for each country.
We take the latest observation per country as the current policy rate.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from db.models import PolicyRateORM

if TYPE_CHECKING:
    from db.database import Database

logger = logging.getLogger(__name__)

# BIS country codes → metadata
G10_COUNTRIES: dict[str, dict] = {
    "US": {"country": "United States", "central_bank": "Federal Reserve", "currency": "USD"},
    "XM": {"country": "Eurozone", "central_bank": "ECB", "currency": "EUR"},
    "GB": {"country": "United Kingdom", "central_bank": "Bank of England", "currency": "GBP"},
    "JP": {"country": "Japan", "central_bank": "Bank of Japan", "currency": "JPY"},
    "CA": {"country": "Canada", "central_bank": "Bank of Canada", "currency": "CAD"},
    "AU": {"country": "Australia", "central_bank": "RBA", "currency": "AUD"},
    "NZ": {"country": "New Zealand", "central_bank": "RBNZ", "currency": "NZD"},
    "CH": {"country": "Switzerland", "central_bank": "SNB", "currency": "CHF"},
    "SE": {"country": "Sweden", "central_bank": "Riksbank", "currency": "SEK"},
    "NO": {"country": "Norway", "central_bank": "Norges Bank", "currency": "NOK"},
}

_COUNTRY_KEYS = "+".join(G10_COUNTRIES.keys())
_BIS_URL = (
    f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/"
    f"M.{_COUNTRY_KEYS}?format=csv"
)

_CACHE_TTL = 86400  # 24 hours

# Hardcoded seed values — used only when both API and DB are empty (first run)
_SEED_RATES: dict[str, float] = {
    "US": 4.50, "XM": 2.65, "GB": 4.50, "JP": 0.50, "CA": 2.75,
    "AU": 4.10, "NZ": 3.75, "CH": 0.25, "SE": 2.25, "NO": 4.50,
}


class PolicyRateFetcher:
    """Fetches and caches G10 central bank policy rates from BIS."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": "FlorinTerminal/1.0 (+https://github.com/florin-terminal)",
            },
        )
        self._cache: list[dict] | None = None
        self._cache_time: float = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def get_rates(self) -> list[dict]:
        """Return G10 policy rates. Fallback chain: cache → API → DB → seeds."""
        now = time.time()
        if self._cache and now - self._cache_time < _CACHE_TTL:
            return self._cache

        # Try fetching from BIS API
        rates = await self._fetch_from_bis()
        if rates:
            self._cache = rates
            self._cache_time = time.time()
            await self._persist(rates)
            return rates

        # Fallback: read from DB
        rates = await self._read_from_db()
        if rates:
            self._cache = rates
            self._cache_time = time.time()
            return rates

        # Last resort: seed values
        logger.warning("Using seed policy rates (BIS API and DB both unavailable)")
        return self._seed_rates()

    async def _fetch_from_bis(self) -> list[dict]:
        """Fetch latest policy rates from BIS CBPOL SDMX API."""
        try:
            resp = await self._client.get(_BIS_URL)
            resp.raise_for_status()
        except Exception:
            logger.exception("Failed to fetch policy rates from BIS")
            return []

        # Parse CSV — find latest observation per country
        latest: dict[str, tuple[str, float]] = {}  # code → (date, rate)
        try:
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                code = (row.get("REF_AREA") or "").strip()
                date_str = (row.get("TIME_PERIOD") or "").strip()
                val = (row.get("OBS_VALUE") or "").strip()
                if not code or not date_str or not val or val == "NaN":
                    continue
                if code not in G10_COUNTRIES:
                    continue
                try:
                    rate = float(val)
                except ValueError:
                    continue
                # Keep the latest date per country
                if code not in latest or date_str > latest[code][0]:
                    latest[code] = (date_str, rate)
        except Exception:
            logger.exception("Failed to parse BIS CBPOL CSV")
            return []

        if not latest:
            return []

        rates = []
        for code, meta in G10_COUNTRIES.items():
            if code in latest:
                eff_date, rate = latest[code]
                rates.append({
                    "country": meta["country"],
                    "central_bank": meta["central_bank"],
                    "rate": rate,
                    "currency": meta["currency"],
                    "effective_date": eff_date,
                    "country_code": code,
                })

        logger.info("Fetched %d policy rates from BIS CBPOL API", len(rates))
        return rates

    async def _persist(self, rates: list[dict]) -> None:
        """Upsert rates into the database."""
        try:
            async with self._db.session() as session:
                for r in rates:
                    result = await session.execute(
                        select(PolicyRateORM).where(
                            PolicyRateORM.country_code == r["country_code"]
                        )
                    )
                    existing = result.scalar()
                    if existing:
                        existing.rate = r["rate"]
                        existing.effective_date = r.get("effective_date", "")
                        existing.fetched_at = datetime.now(UTC)
                    else:
                        session.add(PolicyRateORM(
                            country_code=r["country_code"],
                            country=r["country"],
                            central_bank=r["central_bank"],
                            currency=r["currency"],
                            rate=r["rate"],
                            effective_date=r.get("effective_date", ""),
                        ))
                await session.commit()
        except Exception:
            logger.exception("Failed to persist policy rates")

    async def _read_from_db(self) -> list[dict]:
        """Read all stored policy rates from DB."""
        try:
            async with self._db.session() as session:
                result = await session.execute(select(PolicyRateORM))
                rows = result.scalars().all()
                if not rows:
                    return []
                return [
                    {
                        "country": r.country,
                        "central_bank": r.central_bank,
                        "rate": r.rate,
                        "currency": r.currency,
                        "effective_date": r.effective_date,
                        "country_code": r.country_code,
                    }
                    for r in rows
                ]
        except Exception:
            logger.exception("Failed to read policy rates from DB")
            return []

    @staticmethod
    def _seed_rates() -> list[dict]:
        """Return hardcoded seed values as a last resort."""
        return [
            {
                "country": meta["country"],
                "central_bank": meta["central_bank"],
                "rate": _SEED_RATES[code],
                "currency": meta["currency"],
                "effective_date": "",
                "country_code": code,
            }
            for code, meta in G10_COUNTRIES.items()
        ]
