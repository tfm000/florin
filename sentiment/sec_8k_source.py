"""
SEC Form 8-K filing retrieval source.

Downloads and extracts plain text from recent Form 8-K filings via
SEC EDGAR. These material event disclosures are valuable for LLM
analysis of corporate announcements (earnings, acquisitions,
leadership changes, etc.).

This source is NOT a SentimentSource — it is used directly by the
announcement analysis pipeline in Phase 4. It reuses the existing
SEC EDGAR utilities (CIK resolution, rate limiting, filing lookup)
from data.sec_edgar_utils.

SEC EDGAR is free. No API key is required, only a User-Agent header
with a contact email per SEC policy.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, datetime

import httpx

from config.constants import SEC_ARCHIVES_URL
from core.models import Form8KFiling
from data.sec_edgar_utils import (
    FilingRef,
    get_company_filings,
    resolve_ticker_to_cik,
    sec_headers,
    sec_rate_limit,
)

logger = logging.getLogger(__name__)

# Maximum number of 8-K filings to retrieve and parse per ticker
MAX_8K_FILINGS = 3

# Maximum character length for extracted 8-K text content
MAX_TEXT_LENGTH = 8000


class SEC8KSource:
    """
    Retrieves and extracts plain text from recent SEC Form 8-K filings.

    For a given ticker, this source:
      1. Resolves the ticker to a CIK via the SEC company tickers file
      2. Fetches recent filings filtered to form type '8-K'
      3. Downloads each filing's index page to locate the primary document
      4. Downloads and extracts plain text from the primary document
      5. Returns a list of Form8KFiling objects with truncated text

    All SEC requests respect the rate limiter from sec_edgar_utils
    (~6.6 req/s, well under SEC's 10 req/s limit).
    """

    async def fetch(self, ticker: str) -> list[Form8KFiling]:
        """
        Fetch recent 8-K filings for a ticker with extracted text content.

        Args:
            ticker: Stock symbol (e.g., "AAPL").

        Returns:
            List of Form8KFiling objects, most recent first.
            Returns empty list on any error without raising.
        """
        try:
            return await self._get_8k_filings(ticker)
        except Exception:
            logger.exception("SEC 8-K fetch failed for %s", ticker)
            return []

    async def _get_8k_filings(self, ticker: str) -> list[Form8KFiling]:
        """Internal implementation of 8-K filing retrieval.

        Args:
            ticker: Stock symbol.

        Returns:
            List of Form8KFiling objects with extracted text content.
        """
        # Step 1: Resolve ticker to CIK
        cik = await resolve_ticker_to_cik(ticker)
        if not cik:
            logger.warning("SEC 8-K: could not resolve ticker %s to CIK", ticker)
            return []

        # Step 2: Get recent 8-K filings
        filing_refs = await get_company_filings(
            cik,
            form_types={"8-K"},
            limit=MAX_8K_FILINGS,
        )
        if not filing_refs:
            logger.debug("SEC 8-K: no recent 8-K filings for %s (CIK %s)", ticker, cik)
            return []

        # Step 3: Download and parse each 8-K
        filings: list[Form8KFiling] = []
        async with httpx.AsyncClient(
            headers=sec_headers(),
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            for ref in filing_refs[:MAX_8K_FILINGS]:
                filing = await self._process_filing(client, ref, ticker)
                if filing:
                    filings.append(filing)

        # Sort by filed date descending
        filings.sort(key=lambda f: f.filed_date, reverse=True)
        return filings

    async def _process_filing(
        self,
        client: httpx.AsyncClient,
        ref: FilingRef,
        ticker: str,
    ) -> Form8KFiling | None:
        """Download and parse a single 8-K filing.

        Args:
            client: Shared httpx client with SEC headers.
            ref: Filing reference from the submissions API.
            ticker: Stock symbol (for the output model).

        Returns:
            Form8KFiling with extracted text, or None on failure.
        """
        base_url = f"{SEC_ARCHIVES_URL}/{ref.cik}/{ref.accession}"
        filing_url = f"{base_url}/{ref.primary_document}"

        try:
            # Try the primary document directly first
            text_content = await self._download_and_extract(
                client,
                filing_url,
            )

            # If primary document failed, try the filing index to find
            # the correct document
            if not text_content:
                text_content = await self._find_and_extract_from_index(
                    client,
                    base_url,
                )

            filed_date = _parse_date(ref.filing_date)

            # Extract 8-K item numbers from the text if available
            items = _extract_8k_items(text_content) if text_content else []

            return Form8KFiling(
                ticker=ticker,
                filed_date=filed_date,
                form_type=ref.form_type,
                description=_build_description(items),
                items=items,
                text_content=(text_content or "")[:MAX_TEXT_LENGTH],
                url=filing_url,
                accession_number=ref.accession_dashed,
            )

        except Exception:
            logger.debug(
                "SEC 8-K: failed to process filing %s for %s",
                ref.accession_dashed,
                ticker,
            )
            return None

    async def _download_and_extract(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> str | None:
        """Download a document and extract plain text.

        Args:
            client: httpx client.
            url: URL of the SEC filing document.

        Returns:
            Extracted plain text string, or None on failure.
        """
        await sec_rate_limit()
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.debug("SEC 8-K: HTTP %d for %s", resp.status_code, url)
                return None

            content = resp.text
            if not content or len(content.strip()) < 50:
                return None

            return _strip_html_to_text(content)

        except Exception:
            logger.debug("SEC 8-K: download failed for %s", url)
            return None

    async def _find_and_extract_from_index(
        self,
        client: httpx.AsyncClient,
        base_url: str,
    ) -> str | None:
        """Find the primary 8-K document via the filing index and extract text.

        Falls back to searching the filing index JSON for .htm or .txt
        documents when the primary document URL fails.

        Args:
            client: httpx client.
            base_url: Base URL of the filing directory on SEC EDGAR.

        Returns:
            Extracted plain text, or None if no suitable document found.
        """
        await sec_rate_limit()
        try:
            idx_resp = await client.get(f"{base_url}/index.json")
            if idx_resp.status_code != 200:
                return None

            idx_data = idx_resp.json()
            items = idx_data.get("directory", {}).get("item", [])

            # Look for the primary 8-K document (.htm or .txt, not XBRL/XML)
            for item in items:
                name = item.get("name", "")
                lower_name = name.lower()
                # Skip XBRL, XML, and metadata files
                if any(
                    skip in lower_name
                    for skip in (
                        ".xml",
                        "xbrl",
                        "xsl",
                        "r1.htm",
                        "defnref",
                        "cal.htm",
                        "pre.htm",
                        "lab.htm",
                    )
                ):
                    continue
                # Prefer .htm or .txt files
                if lower_name.endswith((".htm", ".html", ".txt")):
                    doc_url = f"{base_url}/{name}"
                    text = await self._download_and_extract(client, doc_url)
                    if text and len(text.strip()) > 100:
                        return text

        except Exception:
            logger.debug("SEC 8-K: index search failed for %s", base_url)

        return None


def _strip_html_to_text(raw: str) -> str:
    """Strip HTML tags from raw filing content and return clean plain text.

    Handles common SEC filing HTML patterns including:
    - Standard HTML tags (p, div, span, table, etc.)
    - SGML document headers
    - Style and script blocks
    - HTML entities
    - Excessive whitespace

    Args:
        raw: Raw HTML/text content from an SEC filing.

    Returns:
        Clean plain text with normalised whitespace.
    """
    text = raw

    # Remove SGML document wrappers (common in SEC filings)
    text = re.sub(r"<DOCUMENT>.*?<TYPE>[^<]*", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Remove style and script blocks entirely
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Replace <br>, <p>, <div>, <tr> with newlines for readability
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|tr|li|h[1-6])\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(td|th)\b[^>]*>", " ", text, flags=re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode HTML entities
    text = html.unescape(text)

    # Remove non-breaking spaces and other unicode whitespace
    text = text.replace("\xa0", " ")

    # Collapse multiple whitespace/newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)

    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)

    return text.strip()


def _extract_8k_items(text: str) -> list[str]:
    """Extract 8-K item numbers from the filing text.

    SEC 8-K filings are organised by item numbers (e.g., "Item 2.02 -
    Results of Operations and Financial Condition"). This function
    extracts all item references found in the text.

    Args:
        text: Plain text content of the 8-K filing.

    Returns:
        List of item strings (e.g., ["Item 2.02", "Item 9.01"]).
    """
    # Match patterns like "Item 2.02" or "ITEM 2.02" with optional description
    pattern = r"Item\s+\d+\.\d+"
    matches = re.findall(pattern, text, re.IGNORECASE)

    # Normalise to title case and deduplicate while preserving order
    seen: set[str] = set()
    items: list[str] = []
    for match in matches:
        normalised = match.strip().title()
        if normalised not in seen:
            seen.add(normalised)
            items.append(normalised)

    return items


def _build_description(items: list[str]) -> str:
    """Build a human-readable description from 8-K item numbers.

    Args:
        items: List of item number strings.

    Returns:
        Description string, e.g., "Material Event (Item 2.02, Item 9.01)"
        or "Material Event" if no items found.
    """
    if items:
        return f"Material Event ({', '.join(items)})"
    return "Material Event"


def _parse_date(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD date string into a timezone-aware datetime.

    Args:
        date_str: Date string in YYYY-MM-DD format.

    Returns:
        UTC-aware datetime. Falls back to current time if parsing fails.
    """
    if not date_str:
        return datetime.now(UTC)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)
