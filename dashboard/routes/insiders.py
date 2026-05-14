"""
Insider trading API — fetch Form 4 filings from SEC EDGAR.

Parses insider transactions (buys/sells/grants) for a given ticker,
including insider name, title, shares, value, and transaction date.

Uses shared SEC EDGAR utilities for CIK resolution, filing retrieval,
and Form 4 XML parsing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from data.sec_edgar_utils import (
    fetch_form4_xml,
    get_company_filings,
    parse_form4_transactions,
    resolve_ticker_to_cik,
    sec_headers,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["insiders"])


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


# Map from canonical types (data layer) to display types (API layer)
_DISPLAY_TYPE_MAP = {
    "Purchase": "Buy",
    "Sale": "Sell",
    "Grant": "Grant",
    "Exercise": "Exercise",
    "Gift": "Gift",
    "Tax": "Tax",
    "Other": "Other",
}


def _detect_cluster_buys(transactions: list[InsiderTransaction]) -> list[dict[str, Any]]:
    """Detect cluster buys: multiple insiders buying within a 2-week window."""
    buys = [t for t in transactions if t.transaction_type == "Buy"]
    if len(buys) < 2:
        return []

    clusters: list[dict[str, Any]] = []
    used: set[int] = set()

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
            clusters.append(
                {
                    "start_date": dates[0],
                    "end_date": dates[-1],
                    "insider_count": len(unique_insiders),
                    "insiders": list(unique_insiders),
                    "total_shares": sum(b.shares for b in window_buys),
                    "total_value": sum(b.value for b in window_buys),
                }
            )
            used.update(window_indices)

    return clusters


@router.get("/insiders/{ticker}", response_model=InsiderResponse)
async def get_insider_transactions(
    ticker: str,
    limit: int = Query(30, ge=1, le=100, description="Max filings to parse"),
):
    """Get recent insider transactions for a ticker from SEC EDGAR Form 4 filings."""
    ticker = ticker.upper()

    # Resolve ticker to CIK
    cik = await resolve_ticker_to_cik(ticker)
    if not cik:
        return InsiderResponse(ticker=ticker, transactions=[], cluster_buys=[])

    # Get Form 4 filings only
    filings = await get_company_filings(cik, form_types={"4"}, limit=limit)
    if not filings:
        return InsiderResponse(ticker=ticker, transactions=[], cluster_buys=[])

    # Parse each filing's XML
    all_transactions: list[InsiderTransaction] = []

    async with httpx.AsyncClient(
        headers=sec_headers(),
        timeout=15.0,
        follow_redirects=True,
    ) as client:
        for filing in filings:
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{filing.cik}/{filing.accession}/{filing.primary_document}"
            )
            xml_text = await fetch_form4_xml(client, filing)
            if not xml_text:
                continue

            txns = parse_form4_transactions(xml_text, filing.filing_date, filing_url)
            for txn in txns:
                display_type = _DISPLAY_TYPE_MAP.get(txn.transaction_type, "Other")
                value = round(txn.shares * txn.price_per_share, 2)
                all_transactions.append(
                    InsiderTransaction(
                        date=txn.transaction_date or filing.filing_date,
                        insider_name=txn.insider_name,
                        title=txn.insider_title,
                        transaction_type=display_type,
                        shares=int(txn.shares),
                        value=value,
                        price_per_share=txn.price_per_share,
                        filing_url=filing_url,
                    )
                )

    # Sort by date descending
    all_transactions.sort(key=lambda t: t.date, reverse=True)

    # Detect cluster buys
    cluster_buys = _detect_cluster_buys(all_transactions)

    return InsiderResponse(
        ticker=ticker,
        transactions=all_transactions,
        cluster_buys=cluster_buys,
    )
