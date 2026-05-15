"""
Tests for news/scraper.py and news/summarizer.py.

Covers RSS feed parsing, error handling, deduplication,
and LLM-based summarization with mocked dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from news.scraper import RawArticle, scrape_all_feeds
from news.summarizer import (
    _deduplicate,
    _fallback_summaries,
    _parse_batch_response,
    summarize_articles,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW_ISO = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")

VALID_RSS_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Stock Market Surges on Fed Decision</title>
      <link>https://example.com/article1</link>
      <description>&lt;p&gt;The market rallied sharply.&lt;/p&gt;</description>
      <pubDate>{_NOW_ISO}</pubDate>
    </item>
    <item>
      <title>Oil Prices Decline Amid Weak Demand</title>
      <link>https://example.com/article2</link>
      <description>Crude benchmarks dropped 3%.</description>
      <pubDate>{_NOW_ISO}</pubDate>
    </item>
  </channel>
</rss>
"""

MALFORMED_XML = "<<< this is not valid XML at all >>>"


def _mock_response(
    text: str, status_code: int = 200, content_type: str = "application/xml"
) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": content_type},
        text=text,
        request=httpx.Request("GET", "https://example.com/feed"),
    )


# ===================================================================
# scraper.py tests
# ===================================================================


class TestScrapeFeedParsesRSS:
    """test_scrape_feed_parses_rss — valid RSS XML is parsed into RawArticles."""

    @pytest.mark.asyncio
    async def test_parses_valid_rss(self):
        mock_resp = _mock_response(VALID_RSS_XML)

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            articles = await scrape_all_feeds({"TestFeed": "https://example.com/feed"})

        assert len(articles) == 2
        assert articles[0].headline == "Stock Market Surges on Fed Decision"
        assert articles[1].headline == "Oil Prices Decline Amid Weak Demand"
        # HTML tags should be stripped from excerpt
        assert "<p>" not in articles[0].excerpt
        assert "The market rallied sharply." in articles[0].excerpt
        assert articles[0].source == "TestFeed"
        assert articles[0].url == "https://example.com/article1"


class TestScrapeFeedHandlesMalformedXML:
    """test_scrape_feed_handles_malformed_xml — invalid XML does not crash."""

    @pytest.mark.asyncio
    async def test_malformed_xml_returns_empty(self):
        mock_resp = _mock_response(MALFORMED_XML)

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            articles = await scrape_all_feeds({"Bad": "https://example.com/bad"})

        assert articles == []


class TestScrapeFeedHandlesNetworkError:
    """test_scrape_feed_handles_network_error — httpx raising returns empty list."""

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

            articles = await scrape_all_feeds({"Down": "https://example.com/down"})

        assert articles == []


class TestDeduplicateArticles:
    """test_deduplicate_articles — duplicate headlines are removed."""

    @pytest.mark.asyncio
    async def test_exact_duplicate_removed(self):
        """Same headline appearing in two feeds should be deduplicated."""
        mock_resp = _mock_response(VALID_RSS_XML)

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            # Two feeds returning the same articles
            feeds = {
                "Feed1": "https://example.com/feed1",
                "Feed2": "https://example.com/feed2",
            }
            articles = await scrape_all_feeds(feeds)

        # Should be deduplicated to 2 unique headlines (not 4)
        assert len(articles) == 2

    def test_deduplicate_helper_on_raw_articles(self):
        """Verify _deduplicate from summarizer.py removes near-duplicates."""
        articles = [
            RawArticle(headline="Apple Reports Record Q4 Earnings"),
            RawArticle(headline="Apple Reports Record Q4 Earnings"),  # exact dup
            RawArticle(headline="Something Completely Different"),
        ]
        unique = _deduplicate(articles, threshold=0.7)
        assert len(unique) == 2
        headlines = [a.headline for a in unique]
        assert "Something Completely Different" in headlines


# ===================================================================
# summarizer.py tests
# ===================================================================


class TestSummarizeHandlesNoArticles:
    """test_summarize_handles_no_articles — empty input returns empty output."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        result = await summarize_articles([])
        assert result == []


class TestSummarizeFormatsPrompt:
    """test_summarize_formats_prompt — verify the LLM prompt construction."""

    @pytest.mark.asyncio
    async def test_prompt_contains_article_info(self):
        articles = [
            RawArticle(
                headline="Fed Raises Rates by 50bps",
                excerpt="The Federal Reserve raised interest rates.",
                url="https://example.com/fed",
                pub_date=datetime.now(UTC),
                source="Reuters",
            ),
        ]

        # Mock the Groq client so we can inspect what prompt was sent
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '[{"index": 0, "summary": "Fed raised rates", "category": "Economy", '
            '"importance": 9, "tickers": []}]'
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_instance.close = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.groq_api_key = "fake-key"
        mock_settings.groq_model = "llama3-8b-8192"

        with patch("news.summarizer.AsyncGroq", return_value=mock_client_instance):
            result = await summarize_articles(articles, settings=mock_settings)

        # Verify the LLM was called
        mock_client_instance.chat.completions.create.assert_awaited_once()
        call_kwargs = mock_client_instance.chat.completions.create.call_args

        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        assert messages is not None
        assert len(messages) == 2

        # System prompt should contain categories
        assert "Finance" in messages[0]["content"]
        assert "importance" in messages[0]["content"]

        # User prompt should contain the article headline and source
        user_msg = messages[1]["content"]
        assert "Fed Raises Rates by 50bps" in user_msg
        assert "Reuters" in user_msg

        # Result should be properly structured
        assert len(result) == 1
        assert result[0].headline == "Fed Raises Rates by 50bps"
        assert result[0].category == "Economy"
        assert result[0].importance == 9


class TestParseBatchResponse:
    """Additional coverage for the JSON parsing helper."""

    def test_parse_plain_array(self):
        raw = (
            '[{"index": 0, "summary": "test", "category": "Tech", "importance": 5, "tickers": []}]'
        )
        result = _parse_batch_response(raw)
        assert len(result) == 1
        assert result[0]["category"] == "Tech"

    def test_parse_wrapped_in_object(self):
        """Groq json_object mode sometimes wraps the array in an object."""
        raw = '{"articles": [{"index": 0, "summary": "test"}]}'
        result = _parse_batch_response(raw)
        assert len(result) == 1

    def test_parse_markdown_fenced(self):
        raw = '```json\n[{"index": 0}]\n```'
        result = _parse_batch_response(raw)
        assert len(result) == 1

    def test_parse_garbage_returns_empty(self):
        result = _parse_batch_response("not json at all")
        assert result == []


class TestFallbackSummaries:
    """Coverage for _fallback_summaries when LLM fails."""

    def test_creates_placeholder_summaries(self):
        articles = [
            RawArticle(headline="Test", excerpt="An excerpt", source="Test"),
        ]
        result = _fallback_summaries(articles)
        assert len(result) == 1
        assert result[0].headline == "Test"
        assert result[0].category == "Other"
        assert result[0].importance == 3
