"""
Insider trading API — fetch Form 4 filings from SEC EDGAR.

Parses insider transactions (buys/sells/grants) for a given ticker,
including insider name, title, shares, value, and transaction date.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, UTC
from typing import Any
from xml.etree import ElementTree

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["insiders"])

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
USER_AGENT = "SentinelTerminal admin@example.com"

# Rate limiting for SEC (10 req/sec)
_last_sec_request: float = 0.0


async def _sec_rate_limit():
    global _last_sec_request
    now = time.monotonic()
    if now - _last_sec_request < 0.15:
        await asyncio.sleep(0.15 - (now - _last_sec_request))
    _last_sec_request = time.monotonic()


class InsiderTransaction(BaseModel):
    date: str
    insider_name: str
    title: str = ""
    transaction_type: str  # "Buy", "Sell", "Grant", "Exercise", "Other"
    shares: int = 0
    value: float = 0
    price_per_share: float = 0
    filing_url: str = ""


class InsiderResponse(BaseModel):
    ticker: str
    transactions: list[InsiderTransaction]
    cluster_buys: list[dict[str, Any]] = []  # windows with multiple insiders buying


def _detect_cluster_buys(transactions: list[InsiderTransaction]) -> list[dict[str, Any]]:
    """Detect cluster buys: multiple insiders buying within a 2-week window."""
    buys = [t for t in transactions if t.transaction_type == "Buy"]
    if len(buys) < 2:
        return []

    clusters: list[dict[str, Any]] = []
    used = set()

    for i, buy in enumerate(buys):
        if i in used:
            continue
        try:
            base_date = datetime.strptime(buy.date, "%Y-%m-%d")
        except ValueError:
            continue

        window_buys = [buy]
        window_indices = {i}

        for j, other in enumerate(buys):
            if j <= i or j in used:
                continue
            try:
                other_date = datetime.strptime(other.date, "%Y-%m-%d")
            except ValueError:
                continue
            if abs((other_date - base_date).days) <= 14:
                window_buys.append(other)
                window_indices.add(j)

        unique_insiders = set(b.insider_name for b in window_buys)
        if len(unique_insiders) >= 2:
            dates = sorted(b.date for b in window_buys)
            clusters.append({
                "start_date": dates[0],
                "end_date": dates[-1],
                "insider_count": len(unique_insiders),
                "insiders": list(unique_insiders),
                "total_shares": sum(b.shares for b in window_buys),
                "total_value": sum(b.value for b in window_buys),
            })
            used.update(window_indices)

    return clusters


async def _resolve_ticker_to_cik(ticker: str) -> str | None:
    """Look up the CIK for a ticker using SEC EDGAR company tickers JSON."""
    await _sec_rate_limit()
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=15.0,
        ) as client:
            resp = await client.get("https://www.sec.gov/files/company_tickers.json")
            if resp.status_code != 200:
                return None
            data = resp.json()
            ticker_upper = ticker.upper()
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker_upper:
                    return str(entry["cik_str"])
    except Exception:
        logger.exception("Failed to resolve ticker %s to CIK", ticker)
    return None


async def _get_form4_filings(cik: str) -> list[dict]:
    """Get recent Form 4 filings for a CIK from EDGAR submissions."""
    await _sec_rate_limit()
    cik_padded = cik.zfill(10)
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=15.0,
        ) as client:
            resp = await client.get(f"{SEC_SUBMISSIONS_URL}/CIK{cik_padded}.json")
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
                if form not in ("4", "4/A"):
                    continue
                filings.append({
                    "accession": accessions[i].replace("-", ""),
                    "accession_dashed": accessions[i],
                    "date": dates[i],
                    "document": docs[i] if i < len(docs) else "",
                    "cik": cik_padded,
                })
                if len(filings) >= 50:
                    break

            return filings

    except Exception:
        logger.exception("Failed to get Form 4 filings for CIK %s", cik)
        return []


async def _parse_form4_xml(
    client: httpx.AsyncClient, filing: dict,
) -> list[InsiderTransaction]:
    """Download and parse a Form 4 XML filing into transactions."""
    await _sec_rate_limit()
    cik = filing["cik"]
    accession = filing["accession"]
    doc = filing.get("document", "")
    filing_date = filing.get("date", "")
    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"

    # Try to get the XML document
    url = f"{SEC_ARCHIVES_URL}/{cik}/{accession}/{doc}"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            # Try index to find the XML
            await _sec_rate_limit()
            idx_resp = await client.get(
                f"{SEC_ARCHIVES_URL}/{cik}/{accession}/index.json"
            )
            if idx_resp.status_code != 200:
                return []
            idx_data = idx_resp.json()
            xml_file = None
            for item in idx_data.get("directory", {}).get("item", []):
                name = item.get("name", "").lower()
                if name.endswith(".xml") and "primary_doc" not in name:
                    xml_file = item["name"]
                    break
            if not xml_file:
                return []
            await _sec_rate_limit()
            resp = await client.get(
                f"{SEC_ARCHIVES_URL}/{cik}/{accession}/{xml_file}"
            )
            if resp.status_code != 200:
                return []

        return _extract_transactions(resp.text, filing_date, filing_url)

    except Exception:
        logger.debug("Failed to parse Form 4 at %s", url)
        return []


def _extract_transactions(
    xml_text: str, filing_date: str, filing_url: str,
) -> list[InsiderTransaction]:
    """Extract insider transactions from Form 4 XML."""
    transactions = []
    try:
        # Disable namespace to simplify parsing
        xml_text = xml_text.replace('xmlns=', 'xmlns_disabled=')
        root = ElementTree.fromstring(xml_text)

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
            # Also check relationship
            if not insider_title:
                rel = owner.find(".//reportingOwnerRelationship")
                if rel is not None:
                    if rel.find("isDirector") is not None and (
                        rel.find("isDirector").text or ""
                    ).strip() == "1":
                        insider_title = "Director"
                    elif rel.find("isOfficer") is not None and (
                        rel.find("isOfficer").text or ""
                    ).strip() == "1":
                        title_el2 = rel.find("officerTitle")
                        insider_title = (
                            title_el2.text.strip() if title_el2 is not None and title_el2.text else "Officer"
                        )
                    elif rel.find("isTenPercentOwner") is not None and (
                        rel.find("isTenPercentOwner").text or ""
                    ).strip() == "1":
                        insider_title = "10% Owner"

        # Non-derivative transactions
        for txn in root.iter("nonDerivativeTransaction"):
            t = _parse_transaction_element(txn, insider_name, insider_title, filing_date, filing_url)
            if t:
                transactions.append(t)

        # Derivative transactions
        for txn in root.iter("derivativeTransaction"):
            t = _parse_transaction_element(txn, insider_name, insider_title, filing_date, filing_url)
            if t:
                transactions.append(t)

    except ElementTree.ParseError:
        logger.debug("Failed to parse Form 4 XML")
    except Exception:
        logger.debug("Error extracting Form 4 transactions")

    return transactions


def _parse_transaction_element(
    txn, insider_name: str, insider_title: str,
    filing_date: str, filing_url: str,
) -> InsiderTransaction | None:
    """Parse a single transaction element from Form 4 XML."""
    try:
        # Transaction date
        date_el = txn.find(".//transactionDate/value")
        txn_date = date_el.text.strip() if date_el is not None and date_el.text else filing_date

        # Transaction code: P=Purchase, S=Sale, A=Grant/Award, M=Exercise
        code_el = txn.find(".//transactionCoding/transactionCode")
        code = code_el.text.strip() if code_el is not None and code_el.text else ""

        type_map = {
            "P": "Buy",
            "S": "Sell",
            "A": "Grant",
            "M": "Exercise",
            "G": "Gift",
            "F": "Tax",
            "J": "Other",
            "C": "Exercise",
        }
        txn_type = type_map.get(code, "Other")

        # Shares
        shares_el = txn.find(".//transactionAmounts/transactionShares/value")
        shares = 0
        if shares_el is not None and shares_el.text:
            try:
                shares = int(float(shares_el.text.strip()))
            except (ValueError, TypeError):
                pass

        # Price per share
        price_el = txn.find(".//transactionAmounts/transactionPricePerShare/value")
        price = 0.0
        if price_el is not None and price_el.text:
            try:
                price = float(price_el.text.strip())
            except (ValueError, TypeError):
                pass

        value = round(shares * price, 2)

        return InsiderTransaction(
            date=txn_date,
            insider_name=insider_name,
            title=insider_title,
            transaction_type=txn_type,
            shares=shares,
            value=value,
            price_per_share=price,
            filing_url=filing_url,
        )

    except Exception:
        return None


@router.get("/insiders/{ticker}", response_model=InsiderResponse)
async def get_insider_transactions(
    ticker: str,
    limit: int = Query(30, ge=1, le=100, description="Max filings to parse"),
):
    """Get recent insider transactions for a ticker from SEC EDGAR Form 4 filings."""
    ticker = ticker.upper()

    # Resolve ticker to CIK
    cik = await _resolve_ticker_to_cik(ticker)
    if not cik:
        return InsiderResponse(ticker=ticker, transactions=[], cluster_buys=[])

    # Get Form 4 filings
    filings = await _get_form4_filings(cik)
    if not filings:
        return InsiderResponse(ticker=ticker, transactions=[], cluster_buys=[])

    # Parse each filing (limit to avoid too many requests)
    filings = filings[:limit]
    all_transactions: list[InsiderTransaction] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=15.0, follow_redirects=True,
    ) as client:
        for filing in filings:
            txns = await _parse_form4_xml(client, filing)
            all_transactions.extend(txns)

    # Sort by date descending
    all_transactions.sort(key=lambda t: t.date, reverse=True)

    # Detect cluster buys
    cluster_buys = _detect_cluster_buys(all_transactions)

    return InsiderResponse(
        ticker=ticker,
        transactions=all_transactions,
        cluster_buys=cluster_buys,
    )
