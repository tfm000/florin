"""
SEC 13F filing provider — fetch and parse institutional holdings from EDGAR.

Uses the EDGAR full-text search API and submissions API to find 13F-HR filings,
then parses the XML holdings data. CUSIPs are mapped to tickers via OpenFIGI.
"""

from __future__ import annotations

import asyncio
import logging
import time
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
USER_AGENT = "FlorinTerminal admin@example.com"

# Cache: CUSIP → ticker (hydrated from DB on startup, updated by OpenFIGI)
_cusip_cache: dict[str, str] = {}

# SEC name → ticker lookup (loaded from company_tickers.json)
_name_to_ticker: dict[str, str] = {}

# DB reference for persisting new mappings (set by load_cusip_cache)
_db_ref = None

# Rate limiting for SEC (10 req/sec)
_last_sec_request: float = 0.0

# Unauthenticated: serialize (25 req/min is tight)
# Authenticated: allow up to 4 concurrent (25 req/6s is generous but not unlimited)
_openfigi_lock = asyncio.Lock()
_openfigi_semaphore = asyncio.Semaphore(4)
# Lock to serialize DB writes (SQLite single-writer)
_persist_lock = asyncio.Lock()


async def load_cusip_cache(db) -> None:
    """Hydrate the in-memory CUSIP cache from DB and load SEC name→ticker map."""
    global _db_ref
    _db_ref = db
    from sqlalchemy import select

    from db.models import CusipTickerORM

    async with db.session() as session:
        result = await session.execute(select(CusipTickerORM))
        for row in result.scalars():
            _cusip_cache[row.cusip] = row.ticker
    logger.info("CUSIP cache loaded: %d mappings from DB", len(_cusip_cache))

    # Load SEC company_tickers.json for name-based matching
    await _load_sec_name_map()


async def _load_sec_name_map() -> None:
    """Load SEC company_tickers.json to build issuer name → ticker lookup."""
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        ) as client:
            resp = await client.get("https://www.sec.gov/files/company_tickers.json")
            if resp.status_code == 200:
                data = resp.json()
                for entry in data.values():
                    name = entry.get("title", "").upper().strip()
                    ticker = entry.get("ticker", "")
                    if name and ticker:
                        _name_to_ticker[name] = ticker
                logger.info("SEC name→ticker map loaded: %d entries", len(_name_to_ticker))
    except Exception:
        logger.exception("Failed to load SEC company_tickers.json")


async def _persist_cusip_mappings(mappings: dict[str, str]) -> None:
    """Persist new CUSIP→ticker mappings to the database using bulk upsert."""
    if not _db_ref or not mappings:
        return
    from datetime import UTC, datetime

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from db.models import CusipTickerORM

    async with _persist_lock:
        try:
            async with _db_ref.session() as session:
                now = datetime.now(UTC)
                stmt = sqlite_insert(CusipTickerORM).values(
                    [
                        {"cusip": cusip, "ticker": ticker, "updated_at": now}
                        for cusip, ticker in mappings.items()
                    ]
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["cusip"],
                    set_={"ticker": stmt.excluded.ticker, "updated_at": stmt.excluded.updated_at},
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            logger.exception("Failed to persist CUSIP mappings")


async def _sec_rate_limit():
    global _last_sec_request
    now = time.monotonic()
    if now - _last_sec_request < 0.15:
        await asyncio.sleep(0.15 - (now - _last_sec_request))
    _last_sec_request = time.monotonic()


async def search_filers(query: str) -> list[dict]:
    """Search for institutional filers by name via EDGAR full-text search."""
    await _sec_rate_limit()
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        ) as client:
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": query, "forms": "13F-HR"},
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            filers = []
            seen_ciks = set()
            for hit in hits:
                src = hit.get("_source", {})
                ciks = src.get("ciks", [])
                names = src.get("display_names", [])
                if not ciks:
                    continue
                cik = ciks[0].lstrip("0")
                if cik in seen_ciks:
                    continue
                seen_ciks.add(cik)
                # display_names format: "COMPANY NAME  (CIK 0001234567)"
                raw_name = names[0] if names else ""
                name = raw_name.split("(CIK")[0].strip() if "(CIK" in raw_name else raw_name
                filers.append(
                    {
                        "cik": cik,
                        "name": name,
                        "filing_date": src.get("file_date", ""),
                    }
                )
            return filers

    except Exception:
        logger.exception("13F filer search failed for %s", query)

    return []


async def get_filings(cik: str) -> list[dict]:
    """Get list of 13F-HR filings for a given CIK."""
    await _sec_rate_limit()
    cik_padded = cik.zfill(10)
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        ) as client:
            resp = await client.get(
                f"{SEC_SUBMISSIONS_URL}/CIK{cik_padded}.json",
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])

            filings = []
            for i, form in enumerate(forms):
                if form != "13F-HR":
                    continue
                filings.append(
                    {
                        "accession": accessions[i].replace("-", ""),
                        "date": dates[i],
                        "document": docs[i] if i < len(docs) else "",
                    }
                )

            return filings[:20]

    except Exception:
        logger.exception("Failed to get filings for CIK %s", cik)
        return []


async def get_holdings(cik: str, accession: str) -> list[dict]:
    """Parse 13F holdings from an XML filing."""
    await _sec_rate_limit()
    cik_padded = cik.zfill(10)
    url = f"{SEC_ARCHIVES_URL}/{cik_padded}/{accession}"

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            # Find the infotable XML file
            index_resp = await client.get(f"{url}/index.json")
            if index_resp.status_code != 200:
                return []

            index_data = index_resp.json()
            xml_file = None
            xml_items = [
                item
                for item in index_data.get("directory", {}).get("item", [])
                if item.get("name", "").lower().endswith(".xml")
            ]
            # Priority 1: filename contains "infotable"
            for item in xml_items:
                if "infotable" in item["name"].lower():
                    xml_file = item["name"]
                    break
            # Priority 2: filename contains "13f"
            if not xml_file:
                for item in xml_items:
                    if "13f" in item["name"].lower():
                        xml_file = item["name"]
                        break
            # Priority 3: any XML that isn't primary_doc or index
            if not xml_file:
                for item in xml_items:
                    name_lower = item["name"].lower()
                    if name_lower not in ("primary_doc.xml",) and "index" not in name_lower:
                        xml_file = item["name"]
                        break

            if not xml_file:
                return []

            await _sec_rate_limit()
            xml_resp = await client.get(f"{url}/{xml_file}")
            if xml_resp.status_code != 200:
                return []

            return _parse_13f_xml(xml_resp.text)

    except Exception:
        logger.exception("Failed to get holdings for %s/%s", cik, accession)
        return []


def _parse_13f_xml(xml_text: str) -> list[dict]:
    """Parse 13F information table XML into holdings list."""
    holdings = []
    try:
        # Handle namespace
        xml_text = xml_text.replace("xmlns=", "xmlns_disabled=")
        root = ElementTree.fromstring(xml_text)

        for entry in root.iter():
            if "infoTable" in entry.tag:
                holding = {}
                for child in entry:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if tag == "nameOfIssuer":
                        holding["name"] = child.text or ""
                    elif tag == "titleOfClass":
                        holding["title"] = child.text or ""
                    elif tag == "cusip":
                        holding["cusip"] = (child.text or "").strip()
                    elif tag == "figi":
                        holding["figi"] = (child.text or "").strip()
                    elif tag == "value":
                        try:
                            holding["value"] = int(child.text or 0)
                        except (ValueError, TypeError):
                            holding["value"] = 0
                    elif tag == "sshPrnamt" or tag == "shrsOrPrnAmt":
                        for sub in child:
                            sub_tag = sub.tag.split("}")[-1] if "}" in sub.tag else sub.tag
                            if sub_tag == "sshPrnamt":
                                try:
                                    holding["shares"] = int(sub.text or 0)
                                except (ValueError, TypeError):
                                    holding["shares"] = 0

                if holding.get("cusip"):
                    holdings.append(holding)

    except Exception:
        logger.exception("Failed to parse 13F XML")

    return holdings


async def map_cusips_to_tickers(
    cusips: list[str],
    holdings: list[dict] | None = None,
) -> dict[str, str]:
    """Map CUSIPs to tickers using a multi-layer strategy.

    Layer 1: In-memory / DB cache (instant)
    Layer 2: SEC company_tickers.json name matching (no rate limit)
    Layer 3: OpenFIGI FIGI→ticker lookup for FIGIs found in XML
    Layer 4: OpenFIGI CUSIP→ticker lookup (rate-limited fallback)
    """
    result: dict[str, str] = {}
    still_unmapped: list[str] = []

    # Build helpers from holdings data
    cusip_to_name: dict[str, str] = {}
    cusip_to_figi: dict[str, str] = {}
    if holdings:
        for h in holdings:
            c = h.get("cusip", "")
            if c:
                cusip_to_name[c] = h.get("name", "").upper().strip()
                if h.get("figi"):
                    cusip_to_figi[c] = h["figi"]

    # Layer 1: Cache lookup
    for c in cusips:
        if c in _cusip_cache:
            result[c] = _cusip_cache[c]
        else:
            still_unmapped.append(c)

    if not still_unmapped:
        return result

    # Layer 2: SEC name matching
    new_mappings: dict[str, str] = {}
    remaining: list[str] = []
    for c in still_unmapped:
        name = cusip_to_name.get(c, "")
        ticker = _name_to_ticker.get(name, "")
        if ticker:
            result[c] = ticker
            _cusip_cache[c] = ticker
            new_mappings[c] = ticker
        else:
            remaining.append(c)

    if new_mappings:
        logger.info("SEC name match resolved %d CUSIPs", len(new_mappings))
        await _persist_cusip_mappings(new_mappings)

    if not remaining:
        return result

    # Layer 3: OpenFIGI with FIGIs from XML (more reliable than CUSIP lookup)
    figi_batch = [(c, cusip_to_figi[c]) for c in remaining if c in cusip_to_figi]
    non_figi = [c for c in remaining if c not in cusip_to_figi]

    if figi_batch:
        figi_mappings = await _openfigi_lookup(
            [{"idType": "ID_BB_GLOBAL", "idValue": figi} for _, figi in figi_batch],
            [c for c, _ in figi_batch],
        )
        result.update(figi_mappings)
        non_figi_set = set(non_figi)
        # Any FIGI lookups that failed go to CUSIP fallback
        for c, _ in figi_batch:
            if c not in figi_mappings:
                non_figi_set.add(c)
        non_figi = list(non_figi_set)

    # Layer 4: OpenFIGI CUSIP fallback for anything still unmapped
    if non_figi:
        cusip_mappings = await _openfigi_lookup(
            [{"idType": "ID_CUSIP", "idValue": c} for c in non_figi],
            non_figi,
        )
        result.update(cusip_mappings)

    # Fill empty strings for completely unmapped
    for c in cusips:
        if c not in result:
            result[c] = ""

    return result


async def _openfigi_lookup(
    jobs: list[dict],
    cusips: list[str],
) -> dict[str, str]:
    """Call OpenFIGI API in batches and return CUSIP→ticker mappings.

    Adapts batch size and delay based on whether an OpenFIGI API key is
    configured:
      - Authenticated:   100 items/batch, 0.25s delay (25 req/6s)
      - Unauthenticated: 10 items/batch,  2.5s delay  (25 req/min)
    """
    mapped: dict[str, str] = {}
    new_db_mappings: dict[str, str] = {}

    # Re-check cache to skip CUSIPs resolved by a concurrent request
    filtered_jobs = []
    filtered_cusips = []
    for job, cusip in zip(jobs, cusips, strict=True):
        if cusip in _cusip_cache:
            mapped[cusip] = _cusip_cache[cusip]
        else:
            filtered_jobs.append(job)
            filtered_cusips.append(cusip)

    if not filtered_jobs:
        return mapped

    # Determine rate limits from API key
    from config.settings import get_settings

    api_key = get_settings().openfigi_api_key
    if api_key:
        batch_size = 100
        batch_delay = 0.3  # ~20 req/6s, well under 25 req/6s limit
    else:
        batch_size = 10
        batch_delay = 2.5  # ~24 req/min, under 25 req/min limit

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    async def _do_lookup():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for i in range(0, len(filtered_jobs), batch_size):
                    batch_jobs = filtered_jobs[i : i + batch_size]
                    batch_cusips = filtered_cusips[i : i + batch_size]

                    for attempt in range(3):
                        resp = await client.post(
                            OPENFIGI_URL,
                            json=batch_jobs,
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            results = resp.json()
                            for j, res in enumerate(results):
                                if isinstance(res, dict) and "data" in res:
                                    for item in res["data"]:
                                        ticker = item.get("ticker", "")
                                        if not ticker:
                                            continue
                                        c = batch_cusips[j]
                                        mapped[c] = ticker
                                        _cusip_cache[c] = ticker
                                        new_db_mappings[c] = ticker
                                        break
                            break
                        elif resp.status_code in (429, 413):
                            wait = 7 if api_key else 30
                            logger.warning(
                                "OpenFIGI %d, waiting %ds (attempt %d)",
                                resp.status_code,
                                wait,
                                attempt + 1,
                            )
                            await asyncio.sleep(wait)
                        else:
                            logger.warning("OpenFIGI returned %d", resp.status_code)
                            break

                    await asyncio.sleep(batch_delay)

        except Exception:
            logger.exception("OpenFIGI lookup failed")

    # Unauthenticated: full lock (25 req/min is tight, serialize everything).
    # Authenticated: semaphore allows up to 4 concurrent lookups with delay.
    if api_key:
        async with _openfigi_semaphore:
            await _do_lookup()
    else:
        async with _openfigi_lock:
            await _do_lookup()

    if new_db_mappings:
        await _persist_cusip_mappings(new_db_mappings)

    return mapped
