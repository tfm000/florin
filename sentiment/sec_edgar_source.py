"""
SEC EDGAR sentiment source.

Fetches recent SEC filings for a ticker, focusing on:
  - Form 4: Insider trading (buys/sells by executives)
  - Form 8-K: Material events (earnings, M&A, etc.)
  - SC 13D/13G: Beneficial ownership changes

API: https://efts.sec.gov/LATEST/search-index (full-text search)
     https://data.sec.gov/submissions/CIK{cik}.json (company filings)

Free, no auth required. Rate limit: 10 requests/second.
User-Agent header required.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from config.constants import (
    SEC_EDGAR_BASE,
    SEC_EDGAR_SUBMISSIONS,
    SEC_EDGAR_USER_AGENT,
    SEC_FORM_TYPES,
)
from core.models import SECFiling
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# How far back to look for filings
LOOKBACK_DAYS = 90


class SECEdgarSource(SentimentSource):
    """
    Fetches SEC EDGAR filings for a given ticker.

    Looks for insider trades (Form 4), material events (8-K),
    and institutional ownership changes (SC 13D/13G).
    """

    def __init__(self) -> None:
        self._headers = {
            "User-Agent": SEC_EDGAR_USER_AGENT,
            "Accept": "application/json",
        }

    @property
    def name(self) -> str:
        return "SEC EDGAR"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=self._headers) as client:
                resp = await client.get(f"{SEC_EDGAR_BASE}/search-index",
                                        params={"q": "test", "dateRange": "custom",
                                                "startdt": "2024-01-01", "enddt": "2024-01-02"})
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Fetch recent SEC filings for a ticker.

        Returns dict with keys: "filings", "insider_buys", "insider_sells"
        """
        try:
            filings = await self._search_filings(ticker, company_name)

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

    async def _search_filings(
        self, ticker: str, company_name: str,
    ) -> list[SECFiling]:
        """Search EDGAR full-text search for recent filings."""
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)

        # Search by ticker
        query = f'"{ticker}"'
        if company_name:
            query = f'"{ticker}" OR "{company_name}"'

        filings: list[SECFiling] = []

        try:
            async with httpx.AsyncClient(
                timeout=15.0, headers=self._headers,
            ) as client:
                resp = await client.get(
                    f"{SEC_EDGAR_BASE}/search-index",
                    params={
                        "q": query,
                        "dateRange": "custom",
                        "startdt": start_date.strftime("%Y-%m-%d"),
                        "enddt": end_date.strftime("%Y-%m-%d"),
                        "forms": "4,8-K,SC 13D,SC 13G,13F-HR",
                    },
                )

                if resp.status_code != 200:
                    logger.warning("EDGAR search returned %d", resp.status_code)
                    return []

                data = resp.json()

                for hit in data.get("hits", {}).get("hits", []):
                    filing = self._parse_filing(hit)
                    if filing:
                        filings.append(filing)

        except httpx.HTTPStatusError as e:
            logger.error("EDGAR search failed: %s", e)
        except Exception:
            logger.exception("Error searching EDGAR")

        return filings

    def _parse_filing(self, hit: dict[str, Any]) -> SECFiling | None:
        """Parse an EDGAR search result into an SECFiling."""
        try:
            source = hit.get("_source", {})
            form_type = source.get("forms", "")
            filed_date_str = source.get("file_date", "")

            if not form_type or not filed_date_str:
                return None

            # Only process filing types we care about
            base_form = form_type.split("/")[0].strip()
            if base_form not in SEC_FORM_TYPES:
                return None

            try:
                filed_date = datetime.strptime(filed_date_str, "%Y-%m-%d")
            except ValueError:
                filed_date = datetime.now(UTC)

            description = SEC_FORM_TYPES.get(base_form, form_type)

            # Build EDGAR URL
            entity_id = source.get("entity_id", "")
            file_num = source.get("file_num", "")
            url = ""
            if entity_id:
                url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={entity_id}&type={form_type}"

            # For Form 4, try to extract insider transaction details
            insider_name = ""
            transaction_type = ""
            shares = 0.0
            price_per_share = 0.0

            display_names = source.get("display_names", [])
            if display_names and base_form == "4":
                insider_name = display_names[0] if display_names else ""

                # Simple heuristic based on form description
                desc_lower = source.get("display_description", "").lower()
                if "purchase" in desc_lower or "acquisition" in desc_lower:
                    transaction_type = "Purchase"
                elif "sale" in desc_lower or "disposition" in desc_lower:
                    transaction_type = "Sale"
                elif "grant" in desc_lower or "award" in desc_lower:
                    transaction_type = "Grant"

            return SECFiling(
                form_type=base_form,
                filed_date=filed_date,
                description=description,
                url=url,
                insider_name=insider_name,
                transaction_type=transaction_type,
                shares=shares,
                price_per_share=price_per_share,
            )

        except Exception:
            logger.warning("Failed to parse EDGAR filing: %s", hit)
            return None
