"""
Reddit sentiment source via PRAW.

Searches stock subreddits for mentions of a given ticker.
Extracts posts, scores, author metadata, and comment activity.

PRAW is synchronous — all calls are wrapped with asyncio.to_thread().
Rate limit: 100 requests/minute (generous for our use case).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import praw
from praw.models import Submission

from config.constants import STOCK_SUBREDDITS
from config.settings import Settings
from core.models import RedditPost
from sentiment.base import SentimentSource

logger = logging.getLogger(__name__)

# Max posts to fetch per subreddit search
MAX_POSTS_PER_SUBREDDIT = 10
# Max total posts to return
MAX_TOTAL_POSTS = 25


class RedditSource(SentimentSource):
    """
    Scrapes Reddit for ticker mentions via PRAW.

    Searches configured subreddits (r/pennystocks, r/wallstreetbets, etc.)
    for the ticker symbol and company name. Extracts post data including
    author karma and account age for fraud detection.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reddit: praw.Reddit | None = None

    @property
    def name(self) -> str:
        return "Reddit"

    async def health_check(self) -> bool:
        try:
            reddit = self._get_reddit()
            await asyncio.to_thread(lambda: reddit.subreddit("pennystocks").id)
            return True
        except Exception:
            return False

    async def fetch(self, ticker: str, company_name: str = "") -> dict[str, Any]:
        """
        Search Reddit for ticker mentions.

        Returns dict with keys: "posts", "mention_count"
        """
        try:
            posts = await self._search_subreddits(ticker, company_name)

            return {
                "posts": posts,
                "mention_count": len(posts),
            }

        except Exception:
            logger.exception("Reddit fetch failed for %s", ticker)
            return {"posts": [], "mention_count": 0}

    async def _search_subreddits(
        self, ticker: str, company_name: str,
    ) -> list[RedditPost]:
        """Search all configured subreddits for ticker mentions."""
        reddit = self._get_reddit()
        all_posts: list[RedditPost] = []

        # Build search queries
        queries = [f"${ticker}", ticker]
        if company_name:
            queries.append(company_name)

        for subreddit_name in STOCK_SUBREDDITS:
            if len(all_posts) >= MAX_TOTAL_POSTS:
                break

            for query in queries:
                try:
                    posts = await asyncio.to_thread(
                        self._search_subreddit, reddit, subreddit_name, query,
                    )
                    # Deduplicate by URL
                    existing_urls = {p.url for p in all_posts}
                    for post in posts:
                        if post.url not in existing_urls:
                            all_posts.append(post)
                            existing_urls.add(post.url)

                    if len(all_posts) >= MAX_TOTAL_POSTS:
                        break

                except Exception:
                    logger.warning(
                        "Reddit search failed: r/%s query=%s", subreddit_name, query
                    )

        # Sort by score descending
        all_posts.sort(key=lambda p: p.score, reverse=True)
        return all_posts[:MAX_TOTAL_POSTS]

    def _search_subreddit(
        self, reddit: praw.Reddit, subreddit_name: str, query: str,
    ) -> list[RedditPost]:
        """Synchronous search — called via asyncio.to_thread."""
        posts: list[RedditPost] = []
        subreddit = reddit.subreddit(subreddit_name)

        for submission in subreddit.search(
            query, sort="relevance", time_filter="week", limit=MAX_POSTS_PER_SUBREDDIT,
        ):
            post = self._parse_submission(submission, subreddit_name)
            if post:
                posts.append(post)

        return posts

    def _parse_submission(
        self, submission: Submission, subreddit_name: str,
    ) -> RedditPost | None:
        """Convert a PRAW Submission to our RedditPost model."""
        try:
            author = submission.author
            author_name = ""
            author_karma = 0
            account_age_days = 0

            if author:
                author_name = str(author.name) if hasattr(author, "name") else ""
                try:
                    author_karma = getattr(author, "link_karma", 0) + getattr(author, "comment_karma", 0)
                    created = getattr(author, "created_utc", 0)
                    if created:
                        age = datetime.now(timezone.utc) - datetime.fromtimestamp(created, tz=timezone.utc)
                        account_age_days = age.days
                except Exception:
                    pass  # Author may be suspended/deleted

            return RedditPost(
                subreddit=subreddit_name,
                title=submission.title or "",
                body=(submission.selftext or "")[:500],  # Truncate long posts
                score=submission.score,
                num_comments=submission.num_comments,
                upvote_ratio=submission.upvote_ratio,
                url=f"https://reddit.com{submission.permalink}",
                author=author_name,
                author_karma=author_karma,
                account_age_days=account_age_days,
                created_at=datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
            )
        except Exception:
            logger.warning("Failed to parse Reddit submission")
            return None

    def _get_reddit(self) -> praw.Reddit:
        """Lazy-initialise the PRAW Reddit instance."""
        if self._reddit is None:
            self._reddit = praw.Reddit(
                client_id=self._settings.reddit_client_id,
                client_secret=self._settings.reddit_client_secret,
                user_agent=self._settings.reddit_user_agent,
            )
        return self._reddit
