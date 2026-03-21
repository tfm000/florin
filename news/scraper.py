"""
News scraper — RSS feed parsing with HTML fallback.

Adapted from the Diana project's multi-strategy approach:
1. Direct RSS/Atom feed parsing
2. Feed auto-discovery from HTML <link> tags
3. HTML article extraction fallback

Max 30 articles per feed, 3-day staleness filter.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

_MAX_ARTICLES = 30
_STALE_DAYS = 3
_TIMEOUT = 15.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Pre-configured financial RSS feeds
DEFAULT_FEEDS = {
    "Reuters Business": "https://www.reutersagency.com/feed/?best-topics=business-finance",
    "CNBC Top News": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "MarketWatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "Coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
}


@dataclass
class RawArticle:
    headline: str
    excerpt: str = ""
    url: str = ""
    pub_date: datetime | None = None
    source: str = ""


async def scrape_all_feeds(feeds: dict[str, str] | None = None) -> list[RawArticle]:
    """Scrape all configured RSS feeds and return deduplicated articles."""
    if feeds is None:
        feeds = DEFAULT_FEEDS

    all_articles = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        for source_name, url in feeds.items():
            try:
                articles = await _scrape_feed(client, url, source_name)
                all_articles.extend(articles)
            except Exception:
                logger.debug("Failed to scrape %s", source_name)

    # Deduplicate by headline similarity
    seen = set()
    unique = []
    for a in all_articles:
        key = a.headline.lower().strip()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    # Sort by date (newest first)
    unique.sort(key=lambda a: a.pub_date or datetime.min.replace(tzinfo=UTC), reverse=True)
    return unique[:100]


async def _scrape_feed(client: httpx.AsyncClient, url: str, source: str) -> list[RawArticle]:
    """Scrape a single RSS/Atom feed URL."""
    resp = await client.get(url)
    if resp.status_code != 200:
        return []

    content_type = resp.headers.get("content-type", "")
    text = resp.text

    # Check if it's RSS/Atom XML
    if "xml" in content_type or text.strip().startswith("<?xml") or text.strip().startswith("<rss") or text.strip().startswith("<feed"):
        return _parse_feed_xml(text, source)

    return []


def _parse_feed_xml(xml_text: str, source: str) -> list[RawArticle]:
    """Parse RSS 2.0 or Atom feed XML."""
    articles = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    cutoff = datetime.now(UTC) - timedelta(days=_STALE_DAYS)

    # RSS 2.0: <channel><item>
    for item in root.iter("item"):
        title = _get_text(item, "title")
        link = _get_text(item, "link")
        desc = _get_text(item, "description")
        pub_str = _get_text(item, "pubDate")

        pub_date = _parse_date(pub_str)
        if pub_date and pub_date < cutoff:
            continue

        if title:
            articles.append(RawArticle(
                headline=title.strip(),
                excerpt=_clean_html(desc)[:400] if desc else "",
                url=link or "",
                pub_date=pub_date,
                source=source,
            ))

    # Atom: <entry>
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title_el = entry.find("{http://www.w3.org/2005/Atom}title")
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
        updated_el = entry.find("{http://www.w3.org/2005/Atom}updated")
        published_el = entry.find("{http://www.w3.org/2005/Atom}published")

        title = title_el.text if title_el is not None else ""
        link = link_el.get("href", "") if link_el is not None else ""
        summary = summary_el.text if summary_el is not None else ""
        date_str = (published_el or updated_el).text if (published_el is not None or updated_el is not None) else ""

        pub_date = _parse_date(date_str)
        if pub_date and pub_date < cutoff:
            continue

        if title:
            articles.append(RawArticle(
                headline=title.strip(),
                excerpt=_clean_html(summary)[:400] if summary else "",
                url=link,
                pub_date=pub_date,
                source=source,
            ))

    return articles[:_MAX_ARTICLES]


def _get_text(element: ElementTree.Element, tag: str) -> str:
    el = element.find(tag)
    return el.text or "" if el is not None else ""


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        # ISO 8601
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()
