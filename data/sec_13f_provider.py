"""
SEC 13F filing provider — fetch and parse institutional holdings from EDGAR.

Uses the EDGAR full-text search API and submissions API to find 13F-HR filings,
then parses the XML holdings data. CUSIPs are mapped to tickers via OpenFIGI.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
USER_AGENT = "SentinelTerminal admin@example.com"

# Cache: CUSIP → ticker
_cusip_cache: dict[str, str] = {}

# Rate limiting for SEC (10 req/sec)
_last_sec_request: float = 0.0


async def _sec_rate_limit():
    global _last_sec_request
    now = time.monotonic()
    if now - _last_sec_request < 0.15:
        await asyncio.sleep(0.15 - (now - _last_sec_request))
    _last_sec_request = time.monotonic()


async def search_filers(query: str) -> list[dict]:
    """Search for institutional filers by name."""
    await _sec_rate_limit()
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=15.0,
        ) as client:
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={
                    "q": f'"{query}" formType:"13F-HR"',
                    "dateRange": "custom",
                    "startdt": "2020-01-01",
                    "forms": "13F-HR",
                },
            )
            if resp.status_code != 200:
                # Fallback: use EDGAR company search
                resp = await client.get(
                    "https://www.sec.gov/cgi-bin/browse-edgar",
                    params={
                        "company": query,
                        "CIK": "",
                        "type": "13F-HR",
                        "dateb": "",
                        "owner": "include",
                        "count": 20,
                        "search_text": "",
                        "action": "getcompany",
                        "output": "atom",
                    },
                )

            # Try full-text search API
            resp2 = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": query, "forms": "13F-HR", "dateRange": "custom",
                        "startdt": "2023-01-01"},
            )
            if resp2.status_code == 200:
                data = resp2.json()
                hits = data.get("hits", {}).get("hits", [])
                filers = []
                seen_ciks = set()
                for hit in hits[:20]:
                    src = hit.get("_source", {})
                    cik = src.get("entity_id", "")
                    if cik in seen_ciks:
                        continue
                    seen_ciks.add(cik)
                    filers.append({
                        "cik": cik,
                        "name": src.get("entity_name", ""),
                        "filing_date": src.get("file_date", ""),
                    })
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
            headers={"User-Agent": USER_AGENT}, timeout=15.0,
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
                filings.append({
                    "accession": accessions[i].replace("-", ""),
                    "date": dates[i],
                    "document": docs[i] if i < len(docs) else "",
                })

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
            headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True,
        ) as client:
            # Find the infotable XML file
            index_resp = await client.get(f"{url}/index.json")
            if index_resp.status_code != 200:
                return []

            index_data = index_resp.json()
            xml_file = None
            for item in index_data.get("directory", {}).get("item", []):
                name = item.get("name", "").lower()
                if "infotable" in name and name.endswith(".xml"):
                    xml_file = item["name"]
                    break

            if not xml_file:
                # Try common naming patterns
                for item in index_data.get("directory", {}).get("item", []):
                    name = item.get("name", "").lower()
                    if name.endswith(".xml") and "13f" in name:
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
        xml_text = xml_text.replace('xmlns=', 'xmlns_disabled=')
        root = ElementTree.fromstring(xml_text)

        for entry in root.iter():
            if 'infoTable' in entry.tag:
                holding = {}
                for child in entry:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if tag == "nameOfIssuer":
                        holding["name"] = child.text or ""
                    elif tag == "titleOfClass":
                        holding["title"] = child.text or ""
                    elif tag == "cusip":
                        holding["cusip"] = (child.text or "").strip()
                    elif tag == "value":
                        try:
                            holding["value"] = int(child.text or 0) * 1000  # in thousands
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


async def map_cusips_to_tickers(cusips: list[str]) -> dict[str, str]:
    """Map CUSIPs to ticker symbols via OpenFIGI API (free, no key needed)."""
    unmapped = [c for c in cusips if c not in _cusip_cache]
    if not unmapped:
        return {c: _cusip_cache[c] for c in cusips if c in _cusip_cache}

    # OpenFIGI accepts batch of up to 100
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for i in range(0, len(unmapped), 100):
                batch = unmapped[i:i + 100]
                body = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
                resp = await client.post(
                    OPENFIGI_URL,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    results = resp.json()
                    for j, result in enumerate(results):
                        if isinstance(result, dict) and "data" in result:
                            for item in result["data"]:
                                ticker = item.get("ticker", "")
                                if ticker:
                                    _cusip_cache[batch[j]] = ticker
                                    break
                elif resp.status_code == 429:
                    await asyncio.sleep(30)  # OpenFIGI rate limit

    except Exception:
        logger.exception("OpenFIGI CUSIP mapping failed")

    return {c: _cusip_cache.get(c, "") for c in cusips}
