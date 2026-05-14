"""Market news API — RSS scraping + LLM summarisation."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["news"])


class NewsStory(BaseModel):
    headline: str
    excerpt: str = ""
    url: str = ""
    pub_date: str = ""
    source: str = ""


@router.get("/news/feed", response_model=list[NewsStory])
async def get_news_feed():
    """Fetch latest news from configured RSS feeds."""
    from news.scraper import scrape_all_feeds

    articles = await scrape_all_feeds()
    return [
        NewsStory(
            headline=a.headline,
            excerpt=a.excerpt,
            url=a.url,
            pub_date=a.pub_date.isoformat() if a.pub_date else "",
            source=a.source,
        )
        for a in articles
    ]
