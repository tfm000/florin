"""
SEC EDGAR sentiment source.

Fetches recent SEC filings for a ticker via the submissions API,
then downloads and parses Form 4 XML to extract actual insider
transaction details (buy/sell, shares, price, post-transaction holdings).

Also captures non-Form-4 filings (8-K, SC 13D/13G, 13F-HR, 10-K, 10-Q)
as metadata-only records.

Uses shared utilities from data.sec_edgar_utils for CIK resolution,
rate limiting, and XML parsing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from config.constants import SEC_EDGAR_SUBMISSIONS, SEC_FORM_TYPES
from core.models import SECFiling
from data.sec_edgar_utils import (
    Form4Transaction,
    fetch_form4_xml,
    get_company_filings,
    parse_form4_transactions,
    resolve_ticker_to_cik,
    sec_headers,
    sec_rate_limit,
)
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Max Form 4 filings to download and parse XML for (each = 1-3 HTTP requests)
MAX_FORM4_TO_PARSE = 20


class SECEdgarSource(SentimentSource):
    """
    Fetches SEC EDGAR filings for a given ticker.

    Uses the SEC submissions API for reliable ticker-based lookup,
    then parses Form 4 XML for full insider transaction details.
    """

    @property
    def name(self) -> str:
        return "SEC EDGAR"

    async def health_check(self) -> bool:
        try:
            await sec_rate_limit()
            async with httpx.AsyncClient(
                timeout=10.0, headers=sec_headers(),
            ) as client:
                # Apple's CIK — known-good test
                resp = await client.get(
                    f"{SEC_EDGAR_SUBMISSIONS}/CIK0000320193.json"
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch recent SEC filings for a ticker.

        Returns dict with keys: "filings", "insider_buys", "insider_sells"
        """
        try:
            filings = await self._get_filings(ticker)

            insider_buys = sum(
                1 for f in filings
                if f.form_type == "4" and f.transaction_type == "Purchase"
            )
            insider_sells = sum(
                1 for f in filings
                if f.form_type == "4" and f.transaction_type == "Sale"
            )

            return {
                "filings": filings,
                "insider_buys": insider_buys,
                "insider_sells": insider_sells,
            }

        except Exception:
            logger.exception("SEC EDGAR fetch failed for %s", ticker)
            return {"filings": [], "insider_buys": 0, "insider_sells": 0}

    async def _get_filings(self, ticker: str) -> list[SECFiling]:
        """
        Fetch filings via submissions API + parse Form 4 XML.

        Two-phase approach:
          1. Get all recent filings from submissions API
          2. For Form 4s, download and parse XML for transaction details
        """
        # Step 1: Resolve ticker to CIK
        cik = await resolve_ticker_to_cik(ticker)
        if not cik:
            logger.warning("Could not resolve ticker %s to CIK", ticker)
            return []

        # Step 2: Get all filings of interest
        filing_refs = await get_company_filings(cik, limit=50)
        if not filing_refs:
            return []

        # Step 3: Separate Form 4s from other filing types
        form4_refs = [f for f in filing_refs if f.form_type == "4"]
        other_refs = [f for f in filing_refs if f.form_type != "4"]

        result: list[SECFiling] = []

        # Step 4: Parse Form 4 XML for transaction details
        form4_refs = form4_refs[:MAX_FORM4_TO_PARSE]
        if form4_refs:
            async with httpx.AsyncClient(
                headers=sec_headers(), timeout=15.0, follow_redirects=True,
            ) as client:
                for ref in form4_refs:
                    filing_url = (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{ref.cik}/{ref.accession}/{ref.primary_document}"
                    )
                    xml_text = await fetch_form4_xml(client, ref)
                    if not xml_text:
                        # Still record the filing even without XML details
                        result.append(SECFiling(
                            form_type="4",
                            filed_date=_parse_date(ref.filing_date),
                            description=SEC_FORM_TYPES.get("4", "Insider Trading"),
                            url=filing_url,
                        ))
                        continue

                    transactions = parse_form4_transactions(
                        xml_text, ref.filing_date, filing_url,
                    )

                    if not transactions:
                        result.append(SECFiling(
                            form_type="4",
                            filed_date=_parse_date(ref.filing_date),
                            description=SEC_FORM_TYPES.get("4", "Insider Trading"),
                            url=filing_url,
                        ))
                        continue

                    # Create one SECFiling per transaction
                    for txn in transactions:
                        result.append(_txn_to_filing(txn, ref))

        # Step 5: Add non-Form-4 filings as metadata-only
        for ref in other_refs:
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{ref.cik}/{ref.accession}/{ref.primary_document}"
            )
            result.append(SECFiling(
                form_type=ref.form_type,
                filed_date=_parse_date(ref.filing_date),
                description=SEC_FORM_TYPES.get(ref.form_type, ref.form_type),
                url=filing_url,
            ))

        # Sort by date descending
        result.sort(key=lambda f: f.filed_date, reverse=True)
        return result


def _txn_to_filing(txn: Form4Transaction, ref) -> SECFiling:
    """Convert a parsed Form4Transaction into an SECFiling model."""
    return SECFiling(
        form_type="4",
        filed_date=_parse_date(txn.transaction_date or ref.filing_date),
        description=SEC_FORM_TYPES.get("4", "Insider Trading"),
        url=txn.filing_url,
        insider_name=txn.insider_name,
        insider_title=txn.insider_title,
        transaction_type=txn.transaction_type,
        shares=txn.shares,
        price_per_share=txn.price_per_share,
        post_transaction_shares=txn.post_transaction_shares,
    )


def _parse_date(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD date string, falling back to now."""
    if not date_str:
        return datetime.now(UTC)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)
