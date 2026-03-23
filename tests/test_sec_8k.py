"""
Tests for sentiment/sec_8k_source.py — SEC Form 8-K filing retrieval.

Covers:
  - 8-K filing retrieval with mocked SEC responses
  - Text extraction from HTML to clean plain text
  - Empty results when no recent 8-Ks exist
  - Truncation of long filing content
  - Item number extraction from 8-K text
  - Error handling for failed downloads
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.models import Form8KFiling
from data.sec_edgar_utils import FilingRef
from sentiment.sec_8k_source import (
    MAX_TEXT_LENGTH,
    SEC8KSource,
    _build_description,
    _extract_8k_items,
    _strip_html_to_text,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_filing_ref(
    form_type: str = "8-K",
    filing_date: str = "2024-06-15",
    accession: str = "000012345624000001",
    accession_dashed: str = "0000123456-24-000001",
    primary_document: str = "filing-8k.htm",
    cik: str = "0000320193",
) -> FilingRef:
    """Create a FilingRef for testing."""
    return FilingRef(
        form_type=form_type,
        filing_date=filing_date,
        accession=accession,
        accession_dashed=accession_dashed,
        primary_document=primary_document,
        cik=cik,
    )


_SAMPLE_8K_HTML = """
<html>
<head><title>Form 8-K</title>
<style>body { font-family: Arial; }</style>
</head>
<body>
<h1>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</h1>
<h2>FORM 8-K</h2>
<p>CURRENT REPORT</p>
<p>Pursuant to Section 13 or 15(d) of the Securities Exchange Act of 1934</p>
<p>Date of Report: June 15, 2024</p>

<h3>Item 2.02 Results of Operations and Financial Condition</h3>
<p>On June 15, 2024, Example Corp announced its quarterly earnings results.
Revenue increased 15% year-over-year to $5.2 billion. Net income was $1.1 billion,
compared to $950 million in the prior year period.</p>

<h3>Item 9.01 Financial Statements and Exhibits</h3>
<p>Press release dated June 15, 2024.</p>

</body>
</html>
"""


# ===========================================================================
# Tests — HTML text extraction
# ===========================================================================


class TestStripHtmlToText:
    """Test _strip_html_to_text function."""

    def test_strips_html_tags(self) -> None:
        """HTML tags are removed from the output."""
        result = _strip_html_to_text("<p>Hello <b>world</b></p>")
        assert "<" not in result
        assert "Hello" in result
        assert "world" in result

    def test_removes_style_blocks(self) -> None:
        """Style blocks are completely removed."""
        html = "<style>body { color: red; }</style><p>Content</p>"
        result = _strip_html_to_text(html)
        assert "color" not in result
        assert "Content" in result

    def test_removes_script_blocks(self) -> None:
        """Script blocks are completely removed."""
        html = "<script>alert('test');</script><p>Content</p>"
        result = _strip_html_to_text(html)
        assert "alert" not in result
        assert "Content" in result

    def test_decodes_html_entities(self) -> None:
        """HTML entities are decoded to their characters."""
        result = _strip_html_to_text("<p>AT&amp;T &lt;stock&gt;</p>")
        assert "AT&T" in result
        assert "<stock>" in result

    def test_preserves_line_breaks(self) -> None:
        """Paragraph and div boundaries become newlines."""
        html = "<p>Line one</p><p>Line two</p>"
        result = _strip_html_to_text(html)
        assert "Line one" in result
        assert "Line two" in result

    def test_collapses_excessive_whitespace(self) -> None:
        """Multiple spaces and blank lines are collapsed."""
        html = "<p>  Lots   of   spaces  </p>"
        result = _strip_html_to_text(html)
        # Should not have multiple consecutive spaces
        assert "  " not in result.replace("\n\n", "  ")

    def test_full_8k_html(self) -> None:
        """Full sample 8-K HTML produces readable text."""
        result = _strip_html_to_text(_SAMPLE_8K_HTML)
        assert "FORM 8-K" in result
        assert "Item 2.02" in result
        assert "$5.2 billion" in result
        # No HTML tags remain
        assert "<p>" not in result
        assert "<h3>" not in result

    def test_handles_non_breaking_spaces(self) -> None:
        """Non-breaking spaces are converted to regular spaces."""
        result = _strip_html_to_text("Hello\xa0World")
        assert "Hello World" in result


# ===========================================================================
# Tests — 8-K item extraction
# ===========================================================================


class TestExtract8KItems:
    """Test _extract_8k_items function."""

    def test_extracts_item_numbers(self) -> None:
        """Standard item references are extracted."""
        text = "Item 2.02 Results of Operations\nItem 9.01 Financial Statements"
        items = _extract_8k_items(text)
        assert "Item 2.02" in items
        assert "Item 9.01" in items

    def test_deduplicates_items(self) -> None:
        """Duplicate item numbers are removed."""
        text = "Item 2.02 Something\nItem 2.02 Again"
        items = _extract_8k_items(text)
        assert items.count("Item 2.02") == 1

    def test_case_insensitive(self) -> None:
        """Matches ITEM, item, Item."""
        text = "ITEM 5.02 Leadership Changes\nitem 9.01 Exhibits"
        items = _extract_8k_items(text)
        assert len(items) == 2
        # Should be normalised to title case
        assert "Item 5.02" in items
        assert "Item 9.01" in items

    def test_no_items_returns_empty(self) -> None:
        """Text without item numbers returns empty list."""
        text = "This is a filing with no item references."
        items = _extract_8k_items(text)
        assert items == []


# ===========================================================================
# Tests — description building
# ===========================================================================


class TestBuildDescription:
    """Test _build_description function."""

    def test_with_items(self) -> None:
        """Description includes item numbers."""
        desc = _build_description(["Item 2.02", "Item 9.01"])
        assert "Item 2.02" in desc
        assert "Item 9.01" in desc
        assert "Material Event" in desc

    def test_without_items(self) -> None:
        """Description is generic when no items found."""
        desc = _build_description([])
        assert desc == "Material Event"


# ===========================================================================
# Tests — SEC8KSource.fetch() with mocked API
# ===========================================================================


class TestSEC8KSourceFetch:
    """Test the full fetch pipeline with mocked SEC API calls."""

    @pytest.mark.asyncio
    async def test_fetch_returns_form8k_filings(self) -> None:
        """Successful fetch returns a list of Form8KFiling objects."""
        source = SEC8KSource()

        with (
            patch("sentiment.sec_8k_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik,
            patch("sentiment.sec_8k_source.get_company_filings", new_callable=AsyncMock) as mock_filings,
            patch("sentiment.sec_8k_source.sec_rate_limit", new_callable=AsyncMock),
        ):
            mock_cik.return_value = "320193"
            mock_filings.return_value = [_make_filing_ref()]

            # Mock the HTTP client for document download
            with patch("sentiment.sec_8k_source.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = httpx.Response(
                    status_code=200,
                    text=_SAMPLE_8K_HTML,
                    request=httpx.Request("GET", "https://www.sec.gov/test"),
                )
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                result = await source.fetch("AAPL")

        assert len(result) >= 1
        filing = result[0]
        assert isinstance(filing, Form8KFiling)
        assert filing.ticker == "AAPL"
        assert filing.form_type == "8-K"
        assert "Item 2.02" in filing.items
        assert "quarterly earnings" in filing.text_content.lower()

    @pytest.mark.asyncio
    async def test_fetch_no_cik_returns_empty(self) -> None:
        """Returns empty when ticker cannot be resolved to CIK."""
        source = SEC8KSource()

        with patch(
            "sentiment.sec_8k_source.resolve_ticker_to_cik",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await source.fetch("INVALID")

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_no_filings_returns_empty(self) -> None:
        """Returns empty when no 8-K filings are found."""
        source = SEC8KSource()

        with (
            patch("sentiment.sec_8k_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik,
            patch("sentiment.sec_8k_source.get_company_filings", new_callable=AsyncMock) as mock_filings,
        ):
            mock_cik.return_value = "320193"
            mock_filings.return_value = []

            result = await source.fetch("AAPL")

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_handles_download_failure(self) -> None:
        """Filing is still returned even if document download fails (empty text)."""
        source = SEC8KSource()

        with (
            patch("sentiment.sec_8k_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik,
            patch("sentiment.sec_8k_source.get_company_filings", new_callable=AsyncMock) as mock_filings,
            patch("sentiment.sec_8k_source.sec_rate_limit", new_callable=AsyncMock),
        ):
            mock_cik.return_value = "320193"
            mock_filings.return_value = [_make_filing_ref()]

            # Mock client that returns 404 for all documents
            with patch("sentiment.sec_8k_source.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = httpx.Response(
                    status_code=404,
                    request=httpx.Request("GET", "https://www.sec.gov/test"),
                )
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                result = await source.fetch("AAPL")

        # Filing metadata is still present, just no text content
        assert len(result) >= 1
        assert result[0].text_content == ""


# ===========================================================================
# Tests — text truncation
# ===========================================================================


class TestTextTruncation:
    """Test that long filing text is truncated to MAX_TEXT_LENGTH."""

    @pytest.mark.asyncio
    async def test_long_text_is_truncated(self) -> None:
        """Filing text longer than MAX_TEXT_LENGTH is truncated."""
        source = SEC8KSource()
        long_html = "<p>" + "x" * (MAX_TEXT_LENGTH + 5000) + "</p>"

        with (
            patch("sentiment.sec_8k_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik,
            patch("sentiment.sec_8k_source.get_company_filings", new_callable=AsyncMock) as mock_filings,
            patch("sentiment.sec_8k_source.sec_rate_limit", new_callable=AsyncMock),
        ):
            mock_cik.return_value = "320193"
            mock_filings.return_value = [_make_filing_ref()]

            with patch("sentiment.sec_8k_source.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = httpx.Response(
                    status_code=200,
                    text=long_html,
                    request=httpx.Request("GET", "https://www.sec.gov/test"),
                )
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                result = await source.fetch("AAPL")

        assert len(result) >= 1
        assert len(result[0].text_content) <= MAX_TEXT_LENGTH


# ===========================================================================
# Tests — error resilience
# ===========================================================================


class TestSEC8KSourceErrorResilience:
    """Test that the source handles exceptions without crashing."""

    @pytest.mark.asyncio
    async def test_exception_in_fetch_returns_empty(self) -> None:
        """Unhandled exception in _get_8k_filings returns empty list."""
        source = SEC8KSource()

        with patch(
            "sentiment.sec_8k_source.resolve_ticker_to_cik",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Unexpected error"),
        ):
            result = await source.fetch("AAPL")

        assert result == []
