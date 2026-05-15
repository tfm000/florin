"""
Shared SEC EDGAR utilities.

Provides CIK resolution, Form 4 XML parsing, and rate-limited HTTP
access to SEC EDGAR APIs. Used by both the sentiment source and the
dashboard insiders route.

Key SEC endpoints:
  - https://www.sec.gov/files/company_tickers.json  (ticker -> CIK)
  - https://data.sec.gov/submissions/CIK{cik}.json  (company filings)
  - https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}  (filing docs)

Rate limit: 10 requests/second (we use 0.15s between requests for safety).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

from config.constants import (
    SEC_ARCHIVES_URL,
    SEC_COMPANY_TICKERS_URL,
    SEC_EDGAR_SUBMISSIONS,
    SEC_EDGAR_USER_AGENT,
    SEC_FORM_TYPES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
_rate_lock = asyncio.Lock()
_last_request_time: float = 0.0
_MIN_INTERVAL = 0.15  # ~6.6 req/s, well under SEC's 10 req/s limit


async def sec_rate_limit() -> None:
    """Enforce minimum interval between SEC requests (async-safe)."""
    global _last_request_time
    async with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)
        _last_request_time = time.monotonic()


def sec_headers() -> dict[str, str]:
    """Standard headers for SEC requests."""
    return {
        "User-Agent": SEC_EDGAR_USER_AGENT,
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# CIK resolution with in-memory cache
# ---------------------------------------------------------------------------
_cik_cache: dict[str, str] = {}
_cik_cache_time: float = 0.0
_CIK_CACHE_TTL = 3600  # 1 hour


async def resolve_ticker_to_cik(ticker: str) -> str | None:
    """
    Resolve a stock ticker to its SEC CIK number.

    Uses https://www.sec.gov/files/company_tickers.json with 1-hour cache.
    Returns the CIK as a string (not zero-padded), or None if not found.
    """
    global _cik_cache, _cik_cache_time

    ticker_upper = ticker.upper()

    # Check cache
    if _cik_cache and (time.time() - _cik_cache_time) < _CIK_CACHE_TTL:
        return _cik_cache.get(ticker_upper)

    # Fetch and rebuild cache
    await sec_rate_limit()
    try:
        async with httpx.AsyncClient(
            headers=sec_headers(),
            timeout=15.0,
        ) as client:
            resp = await client.get(SEC_COMPANY_TICKERS_URL)
            if resp.status_code != 200:
                logger.warning("Failed to fetch company_tickers.json: %d", resp.status_code)
                return _cik_cache.get(ticker_upper)  # stale cache fallback

            data = resp.json()
            new_cache: dict[str, str] = {}
            for entry in data.values():
                t = (entry.get("ticker") or "").upper()
                if t:
                    new_cache[t] = str(entry["cik_str"])

            _cik_cache = new_cache
            _cik_cache_time = time.time()
            return _cik_cache.get(ticker_upper)

    except Exception:
        logger.exception("Failed to resolve ticker %s to CIK", ticker)
        return _cik_cache.get(ticker_upper)


# ---------------------------------------------------------------------------
# Company filings from submissions API
# ---------------------------------------------------------------------------


@dataclass
class FilingRef:
    """Reference to a single SEC filing from the submissions API."""

    form_type: str
    filing_date: str  # YYYY-MM-DD
    accession: str  # no dashes (for URL building)
    accession_dashed: str
    primary_document: str
    cik: str  # zero-padded


async def get_company_filings(
    cik: str,
    form_types: set[str] | None = None,
    limit: int = 50,
) -> list[FilingRef]:
    """
    Fetch recent filings for a CIK from the SEC submissions API.

    Args:
        cik: CIK number (will be zero-padded to 10 digits)
        form_types: set of form types to include (e.g. {"4", "4/A", "8-K"}).
                    If None, includes all types in SEC_FORM_TYPES.
        limit: max filings to return
    """
    if form_types is None:
        form_types = set(SEC_FORM_TYPES.keys())
    # Also include amended versions
    expanded = set()
    for ft in form_types:
        expanded.add(ft)
        expanded.add(f"{ft}/A")

    cik_padded = cik.zfill(10)
    await sec_rate_limit()

    try:
        async with httpx.AsyncClient(
            headers=sec_headers(),
            timeout=15.0,
        ) as client:
            resp = await client.get(f"{SEC_EDGAR_SUBMISSIONS}/CIK{cik_padded}.json")
            if resp.status_code != 200:
                logger.warning("SEC submissions returned %d for CIK %s", resp.status_code, cik)
                return []

            data = resp.json()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])

            filings: list[FilingRef] = []
            for i, form in enumerate(forms):
                if form not in expanded:
                    continue
                filings.append(
                    FilingRef(
                        form_type=form.split("/")[0],  # "4/A" -> "4"
                        filing_date=dates[i] if i < len(dates) else "",
                        accession=accessions[i].replace("-", "") if i < len(accessions) else "",
                        accession_dashed=accessions[i] if i < len(accessions) else "",
                        primary_document=docs[i] if i < len(docs) else "",
                        cik=cik_padded,
                    )
                )
                if len(filings) >= limit:
                    break

            return filings

    except Exception:
        logger.exception("Failed to get filings for CIK %s", cik)
        return []


# ---------------------------------------------------------------------------
# Form 4 XML parsing
# ---------------------------------------------------------------------------


@dataclass
class Form4Transaction:
    """Parsed transaction from a Form 4 XML filing."""

    insider_name: str = ""
    insider_title: str = ""
    transaction_type: str = (
        ""  # "Purchase" | "Sale" | "Grant" | "Exercise" | "Gift" | "Tax" | "Other"
    )
    transaction_date: str = ""  # YYYY-MM-DD
    shares: float = 0.0
    price_per_share: float = 0.0
    post_transaction_shares: float = 0.0
    filing_url: str = ""


# SEC transaction code -> human-readable type
_TRANSACTION_CODE_MAP = {
    "P": "Purchase",
    "S": "Sale",
    "A": "Grant",
    "M": "Exercise",
    "G": "Gift",
    "F": "Tax",
    "J": "Other",
    "C": "Exercise",
}


async def fetch_form4_xml(
    client: httpx.AsyncClient,
    filing: FilingRef,
) -> str | None:
    """
    Download the raw XML content of a Form 4 filing.

    The primaryDocument field often points to an XSLT-rendered HTML version
    (e.g. "xslF345X05/wk-form4_xxx.xml"). We strip the XSLT prefix to get
    the raw XML, then fall back to the filing index if needed.
    """
    cik = filing.cik
    accession = filing.accession
    doc = filing.primary_document

    # Strip XSLT prefix (e.g. "xslF345X05/wk-form4.xml" -> "wk-form4.xml")
    raw_doc = doc.split("/")[-1] if "/" in doc else doc
    base_url = f"{SEC_ARCHIVES_URL}/{cik}/{accession}"

    await sec_rate_limit()
    try:
        # Try the raw XML filename first
        resp = await client.get(f"{base_url}/{raw_doc}")
        if resp.status_code == 200 and _is_xml(resp.text):
            return resp.text

        # Try the original path if different
        if raw_doc != doc:
            await sec_rate_limit()
            resp = await client.get(f"{base_url}/{doc}")
            if resp.status_code == 200 and _is_xml(resp.text):
                return resp.text

        # Fallback: find XML via filing index
        await sec_rate_limit()
        idx_resp = await client.get(f"{base_url}/index.json")
        if idx_resp.status_code != 200:
            return None

        idx_data = idx_resp.json()
        for item in idx_data.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name.lower().endswith(".xml") and "xsl" not in name.lower():
                await sec_rate_limit()
                resp = await client.get(f"{base_url}/{name}")
                if resp.status_code == 200 and _is_xml(resp.text):
                    return resp.text

    except Exception:
        logger.debug("Failed to fetch Form 4 XML for %s/%s", cik, accession)

    return None


def _is_xml(text: str) -> bool:
    """Check if text looks like XML (not HTML)."""
    stripped = text.strip()
    return stripped.startswith("<?xml") or stripped.startswith("<ownershipDocument")


def parse_form4_transactions(
    xml_text: str,
    filing_date: str = "",
    filing_url: str = "",
) -> list[Form4Transaction]:
    """
    Parse a Form 4 XML document and extract all transactions.

    Handles both non-derivative and derivative transactions.
    Extracts insider name, title, transaction type, shares, price,
    and post-transaction holdings.
    """
    transactions: list[Form4Transaction] = []

    try:
        # Disable namespace to simplify XPath
        cleaned = xml_text.replace("xmlns=", "xmlns_disabled=")
        root = ElementTree.fromstring(cleaned)

        # Get reporting owner info
        insider_name = ""
        insider_title = ""

        for owner in root.iter("reportingOwner"):
            name_el = owner.find(".//rptOwnerName")
            if name_el is not None and name_el.text:
                insider_name = name_el.text.strip()

            title_el = owner.find(".//officerTitle")
            if title_el is not None and title_el.text:
                insider_title = title_el.text.strip()

            # Fallback: check relationship flags
            if not insider_title:
                rel = owner.find(".//reportingOwnerRelationship")
                if rel is not None:
                    if _flag_is_set(rel, "isDirector"):
                        insider_title = "Director"
                    elif _flag_is_set(rel, "isOfficer"):
                        officer_el = rel.find("officerTitle")
                        if officer_el is not None and officer_el.text:
                            insider_title = officer_el.text.strip()
                        else:
                            insider_title = "Officer"
                    elif _flag_is_set(rel, "isTenPercentOwner"):
                        insider_title = "10% Owner"

        # Parse non-derivative transactions
        for txn in root.iter("nonDerivativeTransaction"):
            t = _parse_xml_transaction(txn, insider_name, insider_title, filing_date, filing_url)
            if t:
                transactions.append(t)

        # Parse derivative transactions
        for txn in root.iter("derivativeTransaction"):
            t = _parse_xml_transaction(txn, insider_name, insider_title, filing_date, filing_url)
            if t:
                transactions.append(t)

    except ElementTree.ParseError:
        logger.debug("Failed to parse Form 4 XML")
    except Exception:
        logger.debug("Error extracting Form 4 transactions", exc_info=True)

    return transactions


def _flag_is_set(rel_el, tag: str) -> bool:
    """Check if a reportingOwnerRelationship flag element is set to '1' or 'true'."""
    el = rel_el.find(tag)
    if el is None or not el.text:
        return False
    return el.text.strip() in ("1", "true")


def _parse_xml_transaction(
    txn,
    insider_name: str,
    insider_title: str,
    filing_date: str,
    filing_url: str,
) -> Form4Transaction | None:
    """Parse a single transaction element from Form 4 XML."""
    try:
        # Transaction date
        date_el = txn.find(".//transactionDate/value")
        txn_date = date_el.text.strip() if date_el is not None and date_el.text else filing_date

        # Transaction code
        code_el = txn.find(".//transactionCoding/transactionCode")
        code = code_el.text.strip() if code_el is not None and code_el.text else ""
        txn_type = _TRANSACTION_CODE_MAP.get(code, "Other")

        # Shares
        shares = _parse_float(txn, ".//transactionAmounts/transactionShares/value")

        # Price per share
        price = _parse_float(txn, ".//transactionAmounts/transactionPricePerShare/value")

        # Post-transaction holdings
        post_shares = _parse_float(
            txn, ".//postTransactionAmounts/sharesOwnedFollowingTransaction/value"
        )

        return Form4Transaction(
            insider_name=insider_name,
            insider_title=insider_title,
            transaction_type=txn_type,
            transaction_date=txn_date,
            shares=shares,
            price_per_share=price,
            post_transaction_shares=post_shares,
            filing_url=filing_url,
        )

    except Exception:
        return None


def _parse_float(element, xpath: str) -> float:
    """Safely extract a float from an XML element at the given XPath."""
    el = element.find(xpath)
    if el is not None and el.text:
        try:
            return float(el.text.strip())
        except (ValueError, TypeError):
            pass
    return 0.0
