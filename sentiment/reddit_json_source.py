"""
Reddit sentiment source via public .json endpoints (no API key needed).

Fallback for when PRAW OAuth credentials aren't configured.
Uses reddit.com/search.json which is publicly accessible but rate-limited
to ~10 requests/minute for unauthenticated access.

Searches across all stock subreddits in a single request to minimise
API calls. Results are cached with a 5-minute TTL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from config.constants import STOCK_SUBREDDITS
from core.models import RedditPost
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Rate limiting: 10 req/min → min 6s between requests
_MIN_REQUEST_INTERVAL = 6.0

# Cache: ticker → (timestamp, result)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 300  # 5 minutes

# Max posts to return
_MAX_POSTS = 25


class RedditJsonSource(SentimentSource):
    """
    Reddit sentiment via public .json endpoints.

    No API key required. Rate limited to ~10 requests/minute.
    Uses combined search across all configured subreddits in a
    single request to stay well within the limit.
    """

    BASE_URL = "https://www.reddit.com"
    HEADERS = {
        "User-Agent": "florin-terminal/0.2 (market research tool)",
        "Accept": "application/json",
    }

    def __init__(self) -> None:
        self._last_request_time: float = 0.0

    @property
    def name(self) -> str:
        return "Reddit"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(headers=self.HEADERS, timeout=10.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/r/pennystocks/about.json",
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Search Reddit for ticker mentions via public .json endpoints.

        Returns dict with keys: "posts", "mention_count"
        """
        # Check cache first
        cache_key = ticker.upper()
        if cache_key in _cache:
            ts, result = _cache[cache_key]
            if time.time() - ts < _CACHE_TTL:
                return result

        try:
            posts = await self._search(ticker, company_name)
            result = {
                "posts": posts,
                "mention_count": len(posts),
            }
            _cache[cache_key] = (time.time(), result)
            return result

        except Exception:
            logger.exception("Reddit .json fetch failed for %s", ticker)
            return {"posts": [], "mention_count": 0}

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def _search(self, ticker: str, company_name: str) -> list[RedditPost]:
        """Search Reddit for ticker mentions across all configured subreddits."""
        await self._rate_limit()

        # Build search query — combine ticker variants
        # Use reddit.com/search.json which searches across all subreddits
        query = f"${ticker} OR {ticker}"
        if company_name:
            query += f" OR {company_name}"

        # Restrict to our configured subreddits
        subreddit_str = "+".join(STOCK_SUBREDDITS)

        params = {
            "q": query,
            "sort": "relevance",
            "t": "week",
            "limit": str(_MAX_POSTS),
            "restrict_sr": "true",
            "type": "link",
        }

        try:
            async with httpx.AsyncClient(
                headers=self.HEADERS,
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/r/{subreddit_str}/search.json",
                    params=params,
                )

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning("Reddit rate limited — waiting %ds", retry_after)
                    await asyncio.sleep(retry_after)
                    return []

                if resp.status_code != 200:
                    logger.warning("Reddit search returned %d", resp.status_code)
                    return []

                data = resp.json()

        except Exception:
            logger.exception("Reddit .json request failed")
            return []

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> list[RedditPost]:
        """Parse Reddit search JSON response into RedditPost objects."""
        posts: list[RedditPost] = []

        listing = data.get("data", {})
        children = listing.get("children", [])

        for child in children:
            if child.get("kind") != "t3":  # t3 = link/submission
                continue

            post_data = child.get("data", {})
            try:
                # Extract author metadata
                created_utc = post_data.get("created_utc", 0)
                created_at = (
                    datetime.fromtimestamp(created_utc, tz=UTC)
                    if created_utc
                    else datetime.now(UTC)
                )

                # Reddit .json doesn't provide author karma/account age directly
                # in search results — set to defaults
                post = RedditPost(
                    subreddit=post_data.get("subreddit", ""),
                    title=post_data.get("title", ""),
                    body=(post_data.get("selftext", "") or "")[:500],
                    score=post_data.get("score", 0),
                    num_comments=post_data.get("num_comments", 0),
                    upvote_ratio=post_data.get("upvote_ratio", 0.5),
                    url=f"https://reddit.com{post_data.get('permalink', '')}",
                    author=post_data.get("author", "[deleted]"),
                    author_karma=0,  # Not available in search results
                    account_age_days=365,  # Assume established account (conservative)
                    created_at=created_at,
                )
                posts.append(post)

            except Exception:
                logger.debug("Failed to parse Reddit post: %s", post_data.get("title", "?"))
                continue

        # Sort by score descending
        posts.sort(key=lambda p: p.score, reverse=True)
        return posts[:_MAX_POSTS]
