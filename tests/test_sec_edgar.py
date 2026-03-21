"""
Tests for SEC EDGAR utilities and sentiment source.

Tests CIK resolution, Form 4 XML parsing, filing retrieval,
and the full SECEdgarSource integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import SECFiling
from data.sec_edgar_utils import (
    FilingRef,
    Form4Transaction,
    parse_form4_transactions,
    _parse_xml_transaction,
    _TRANSACTION_CODE_MAP,
)
from sentiment.sec_edgar_source import SECEdgarSource, _parse_date


# =============================================================================
# Sample Form 4 XML for testing
# =============================================================================

SAMPLE_FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0407</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>2026-03-15</periodOfReport>
    <issuer>
        <issuerCik>0000320193</issuerCik>
        <issuerName>Apple Inc</issuerName>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001234567</rptOwnerCik>
            <rptOwnerName>COOK TIMOTHY D</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerAddress>
            <rptOwnerCity>Cupertino</rptOwnerCity>
            <rptOwnerState>CA</rptOwnerState>
        </reportingOwnerAddress>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector>
            <isOfficer>1</isOfficer>
            <officerTitle>Chief Executive Officer</officerTitle>
            <isTenPercentOwner>0</isTenPercentOwner>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2026-03-15</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>S</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>50000</value></transactionShares>
                <transactionPricePerShare><value>175.50</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>3279726</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2026-03-14</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>P</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>10000</value></transactionShares>
                <transactionPricePerShare><value>170.25</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>3329726</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
    <derivativeTable>
        <derivativeTransaction>
            <securityTitle><value>Stock Option (right to buy)</value></securityTitle>
            <transactionDate><value>2026-03-10</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>A</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>250000</value></transactionShares>
                <transactionPricePerShare><value>0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>500000</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </derivativeTransaction>
    </derivativeTable>
</ownershipDocument>"""


SAMPLE_FORM4_DIRECTOR_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerName>GORE ALBERT A JR</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>1</isDirector>
            <isOfficer>0</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-02-20</value></transactionDate>
            <transactionCoding>
                <transactionCode>P</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>5000</value></transactionShares>
                <transactionPricePerShare><value>2.50</value></transactionPricePerShare>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>15000</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>"""


SAMPLE_FORM4_MINIMAL_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerName>DOE JANE</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isTenPercentOwner>1</isTenPercentOwner>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-01-15</value></transactionDate>
            <transactionCoding>
                <transactionCode>S</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>100000</value></transactionShares>
                <transactionPricePerShare><value>3.75</value></transactionPricePerShare>
            </transactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>"""


# =============================================================================
# Form 4 XML parsing tests
# =============================================================================


class TestForm4Parsing:
    def test_parse_officer_sale_and_purchase(self):
        """Test parsing a Form 4 with officer sale and purchase transactions."""
        txns = parse_form4_transactions(SAMPLE_FORM4_XML, "2026-03-16", "https://sec.gov/filing")

        # Should have 3 transactions: sale, purchase, grant (derivative)
        assert len(txns) == 3

        # All should have the same insider name
        for t in txns:
            assert t.insider_name == "COOK TIMOTHY D"
            assert t.insider_title == "Chief Executive Officer"

        # First non-derivative: Sale of 50,000 shares at $175.50
        sale = [t for t in txns if t.transaction_type == "Sale"][0]
        assert sale.shares == 50000.0
        assert sale.price_per_share == 175.50
        assert sale.transaction_date == "2026-03-15"
        assert sale.post_transaction_shares == 3279726.0

        # Second non-derivative: Purchase of 10,000 shares at $170.25
        purchase = [t for t in txns if t.transaction_type == "Purchase"][0]
        assert purchase.shares == 10000.0
        assert purchase.price_per_share == 170.25
        assert purchase.transaction_date == "2026-03-14"
        assert purchase.post_transaction_shares == 3329726.0

        # Derivative: Grant of 250,000 options
        grant = [t for t in txns if t.transaction_type == "Grant"][0]
        assert grant.shares == 250000.0
        assert grant.price_per_share == 0.0

    def test_parse_director_purchase(self):
        """Test parsing a Form 4 from a director with a purchase."""
        txns = parse_form4_transactions(SAMPLE_FORM4_DIRECTOR_XML, "2026-02-21", "")

        assert len(txns) == 1
        t = txns[0]
        assert t.insider_name == "GORE ALBERT A JR"
        assert t.insider_title == "Director"
        assert t.transaction_type == "Purchase"
        assert t.shares == 5000.0
        assert t.price_per_share == 2.50
        assert t.post_transaction_shares == 15000.0

    def test_parse_ten_percent_owner(self):
        """Test parsing a Form 4 from a 10% owner."""
        txns = parse_form4_transactions(SAMPLE_FORM4_MINIMAL_XML, "2026-01-16", "")

        assert len(txns) == 1
        t = txns[0]
        assert t.insider_name == "DOE JANE"
        assert t.insider_title == "10% Owner"
        assert t.transaction_type == "Sale"
        assert t.shares == 100000.0
        assert t.price_per_share == 3.75
        # No post-transaction amounts in this XML
        assert t.post_transaction_shares == 0.0

    def test_parse_invalid_xml(self):
        """Test that invalid XML returns empty list."""
        txns = parse_form4_transactions("not xml at all", "2026-01-01", "")
        assert txns == []

    def test_parse_empty_xml(self):
        """Test parsing XML with no transactions."""
        xml = """<?xml version="1.0"?>
        <ownershipDocument>
            <reportingOwner>
                <reportingOwnerId><rptOwnerName>NOBODY</rptOwnerName></reportingOwnerId>
            </reportingOwner>
        </ownershipDocument>"""
        txns = parse_form4_transactions(xml, "2026-01-01", "")
        assert txns == []

    def test_transaction_code_map_coverage(self):
        """Verify all expected transaction codes are mapped."""
        assert _TRANSACTION_CODE_MAP["P"] == "Purchase"
        assert _TRANSACTION_CODE_MAP["S"] == "Sale"
        assert _TRANSACTION_CODE_MAP["A"] == "Grant"
        assert _TRANSACTION_CODE_MAP["M"] == "Exercise"
        assert _TRANSACTION_CODE_MAP["G"] == "Gift"
        assert _TRANSACTION_CODE_MAP["F"] == "Tax"

    def test_filing_url_propagated(self):
        """Test that filing_url is propagated to all transactions."""
        url = "https://sec.gov/Archives/edgar/data/12345/filing.xml"
        txns = parse_form4_transactions(SAMPLE_FORM4_DIRECTOR_XML, "2026-02-21", url)
        assert len(txns) == 1
        assert txns[0].filing_url == url


# =============================================================================
# CIK resolution tests
# =============================================================================


class TestCIKResolution:
    @pytest.mark.asyncio
    async def test_resolve_ticker_to_cik(self):
        """Test CIK resolution with mocked company_tickers.json."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "0": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": "789019", "ticker": "MSFT", "title": "Microsoft Corp"},
            "2": {"cik_str": "1018724", "ticker": "AMZN", "title": "Amazon.com Inc"},
        }

        with patch("data.sec_edgar_utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            # Clear cache
            import data.sec_edgar_utils as utils
            utils._cik_cache = {}
            utils._cik_cache_time = 0.0

            from data.sec_edgar_utils import resolve_ticker_to_cik
            result = await resolve_ticker_to_cik("AAPL")
            assert result == "320193"

            # Test case insensitivity
            result2 = await resolve_ticker_to_cik("aapl")
            assert result2 == "320193"

    @pytest.mark.asyncio
    async def test_resolve_unknown_ticker(self):
        """Test CIK resolution for a ticker not in the database."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "0": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc."},
        }

        with patch("data.sec_edgar_utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            import data.sec_edgar_utils as utils
            utils._cik_cache = {}
            utils._cik_cache_time = 0.0

            from data.sec_edgar_utils import resolve_ticker_to_cik
            result = await resolve_ticker_to_cik("ZZZZ")
            assert result is None

    @pytest.mark.asyncio
    async def test_resolve_uses_cache(self):
        """Test that CIK resolution uses cache on second call."""
        import time
        import data.sec_edgar_utils as utils

        # Pre-populate cache
        utils._cik_cache = {"AAPL": "320193", "MSFT": "789019"}
        utils._cik_cache_time = time.time()  # fresh cache

        from data.sec_edgar_utils import resolve_ticker_to_cik

        # Should use cache without any HTTP call
        with patch("data.sec_edgar_utils.httpx.AsyncClient") as mock_cls:
            result = await resolve_ticker_to_cik("MSFT")
            assert result == "789019"
            mock_cls.assert_not_called()


# =============================================================================
# Company filings tests
# =============================================================================


class TestCompanyFilings:
    @pytest.mark.asyncio
    async def test_get_company_filings(self):
        """Test fetching filings from submissions API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "filings": {
                "recent": {
                    "form": ["4", "8-K", "10-Q", "4/A", "DEF 14A"],
                    "filingDate": ["2026-03-15", "2026-03-10", "2026-02-28", "2026-02-20", "2026-02-15"],
                    "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003",
                                        "0001-26-000004", "0001-26-000005"],
                    "primaryDocument": ["doc1.xml", "doc2.htm", "doc3.htm", "doc4.xml", "doc5.htm"],
                },
            },
        }

        with patch("data.sec_edgar_utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            from data.sec_edgar_utils import get_company_filings
            filings = await get_company_filings("320193", form_types={"4", "8-K", "10-Q"})

        # Should get 4 filings (4, 8-K, 10-Q, 4/A) — DEF 14A excluded
        assert len(filings) == 4
        assert filings[0].form_type == "4"
        assert filings[0].filing_date == "2026-03-15"
        assert filings[1].form_type == "8-K"
        assert filings[3].form_type == "4"  # 4/A -> "4"

    @pytest.mark.asyncio
    async def test_get_company_filings_empty(self):
        """Test handling when API returns no matching filings."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": []}},
        }

        with patch("data.sec_edgar_utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            from data.sec_edgar_utils import get_company_filings
            filings = await get_company_filings("320193")

        assert filings == []


# =============================================================================
# SECEdgarSource integration tests
# =============================================================================


class TestSECEdgarSource:
    @pytest.mark.asyncio
    async def test_fetch_returns_insider_counts(self):
        """Test the full fetch pipeline produces correct insider buy/sell counts."""
        source = SECEdgarSource()

        with patch("sentiment.sec_edgar_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik, \
             patch("sentiment.sec_edgar_source.get_company_filings", new_callable=AsyncMock) as mock_filings, \
             patch("sentiment.sec_edgar_source.fetch_form4_xml", new_callable=AsyncMock) as mock_xml:

            mock_cik.return_value = "320193"
            mock_filings.return_value = [
                FilingRef(form_type="4", filing_date="2026-03-15", accession="000126000001",
                          accession_dashed="0001-26-000001", primary_document="doc.xml", cik="0000320193"),
                FilingRef(form_type="8-K", filing_date="2026-03-10", accession="000126000002",
                          accession_dashed="0001-26-000002", primary_document="doc.htm", cik="0000320193"),
            ]
            mock_xml.return_value = SAMPLE_FORM4_XML

            result = await source.fetch("AAPL", "Apple Inc")

        assert result["insider_buys"] == 1   # one Purchase
        assert result["insider_sells"] == 1  # one Sale
        filings = result["filings"]
        assert len(filings) >= 3  # 3 from Form 4 XML + 1 from 8-K

        # Verify Form 4 transactions have full details
        purchases = [f for f in filings if f.transaction_type == "Purchase"]
        assert len(purchases) == 1
        assert purchases[0].insider_name == "COOK TIMOTHY D"
        assert purchases[0].insider_title == "Chief Executive Officer"
        assert purchases[0].shares == 10000.0
        assert purchases[0].price_per_share == 170.25

        # Verify 8-K is present
        eight_ks = [f for f in filings if f.form_type == "8-K"]
        assert len(eight_ks) == 1

    @pytest.mark.asyncio
    async def test_fetch_graceful_on_cik_failure(self):
        """Test that fetch returns empty when CIK resolution fails."""
        source = SECEdgarSource()

        with patch("sentiment.sec_edgar_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik:
            mock_cik.return_value = None

            result = await source.fetch("ZZZZ")

        assert result["filings"] == []
        assert result["insider_buys"] == 0
        assert result["insider_sells"] == 0

    @pytest.mark.asyncio
    async def test_fetch_handles_xml_failure(self):
        """Test that fetch still records filings when XML download fails."""
        source = SECEdgarSource()

        with patch("sentiment.sec_edgar_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik, \
             patch("sentiment.sec_edgar_source.get_company_filings", new_callable=AsyncMock) as mock_filings, \
             patch("sentiment.sec_edgar_source.fetch_form4_xml", new_callable=AsyncMock) as mock_xml:

            mock_cik.return_value = "320193"
            mock_filings.return_value = [
                FilingRef(form_type="4", filing_date="2026-03-15", accession="000126000001",
                          accession_dashed="0001-26-000001", primary_document="doc.xml", cik="0000320193"),
            ]
            mock_xml.return_value = None  # XML download fails

            result = await source.fetch("AAPL")

        # Should still have a filing record (metadata-only)
        assert len(result["filings"]) == 1
        assert result["filings"][0].form_type == "4"
        # But no transaction details
        assert result["insider_buys"] == 0
        assert result["insider_sells"] == 0

    @pytest.mark.asyncio
    async def test_fetch_multiple_form4s(self):
        """Test parsing multiple Form 4 filings with different insiders."""
        source = SECEdgarSource()

        with patch("sentiment.sec_edgar_source.resolve_ticker_to_cik", new_callable=AsyncMock) as mock_cik, \
             patch("sentiment.sec_edgar_source.get_company_filings", new_callable=AsyncMock) as mock_filings, \
             patch("sentiment.sec_edgar_source.fetch_form4_xml", new_callable=AsyncMock) as mock_xml:

            mock_cik.return_value = "320193"
            mock_filings.return_value = [
                FilingRef(form_type="4", filing_date="2026-03-15", accession="000126000001",
                          accession_dashed="0001-26-000001", primary_document="doc1.xml", cik="0000320193"),
                FilingRef(form_type="4", filing_date="2026-02-21", accession="000126000002",
                          accession_dashed="0001-26-000002", primary_document="doc2.xml", cik="0000320193"),
            ]
            # First call returns officer, second returns director
            mock_xml.side_effect = [SAMPLE_FORM4_XML, SAMPLE_FORM4_DIRECTOR_XML]

            result = await source.fetch("AAPL")

        # Cook: 1 sale + 1 purchase + 1 grant = 3; Gore: 1 purchase = 1; total = 4
        assert len(result["filings"]) == 4
        assert result["insider_buys"] == 2   # Cook purchase + Gore purchase
        assert result["insider_sells"] == 1  # Cook sale

        # Verify different insiders
        names = set(f.insider_name for f in result["filings"] if f.insider_name)
        assert "COOK TIMOTHY D" in names
        assert "GORE ALBERT A JR" in names


# =============================================================================
# Helper function tests
# =============================================================================


class TestHelpers:
    def test_parse_date_valid(self):
        dt = _parse_date("2026-03-15")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15
        assert dt.tzinfo == UTC

    def test_parse_date_empty(self):
        dt = _parse_date("")
        assert dt.year == datetime.now().year

    def test_parse_date_invalid(self):
        dt = _parse_date("not-a-date")
        assert dt.year == datetime.now().year

    def test_to_summary_with_insider_details(self):
        """Test that SentimentData.to_summary includes insider transaction details."""
        from core.models import SentimentData
        data = SentimentData(
            ticker="TEST",
            sec_filings=[
                SECFiling(
                    form_type="4", filed_date=datetime.now(UTC),
                    insider_name="SMITH JOHN", insider_title="CEO",
                    transaction_type="Purchase", shares=10000, price_per_share=2.50,
                ),
                SECFiling(
                    form_type="8-K", filed_date=datetime.now(UTC),
                    description="Material Event",
                ),
            ],
            insider_buy_count=1,
            insider_sell_count=0,
        )
        summary = data.to_summary()
        assert "SMITH JOHN" in summary
        assert "CEO" in summary
        assert "Purchase" in summary
        assert "10,000 shares" in summary
        assert "$2.50" in summary
        assert "8-K" in summary
        assert "Material Event" in summary
