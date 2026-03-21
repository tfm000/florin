"""Tests for Reddit .json fallback sentiment source."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

import httpx

from sentiment.reddit_json_source import RedditJsonSource


SAMPLE_RESPONSE = {
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "subreddit": "pennystocks",
                    "title": "AAPL is going to the moon",
                    "selftext": "I think Apple will go up because...",
                    "score": 42,
                    "num_comments": 15,
                    "upvote_ratio": 0.85,
                    "permalink": "/r/pennystocks/comments/abc123/aapl_moon/",
                    "author": "trader123",
                    "created_utc": 1700000000,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "subreddit": "wallstreetbets",
                    "title": "AAPL DD - strong buy signal",
                    "selftext": "",
                    "score": 100,
                    "num_comments": 50,
                    "upvote_ratio": 0.9,
                    "permalink": "/r/wallstreetbets/comments/def456/aapl_dd/",
                    "author": "yolo_trader",
                    "created_utc": 1700001000,
                },
            },
        ],
    },
}


class TestRedditJsonSource:
    @pytest.fixture
    def source(self):
        return RedditJsonSource()

    def test_name(self, source):
        assert source.name == "Reddit"

    @pytest.mark.asyncio
    async def test_fetch_parses_response(self, source):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE

        with patch("sentiment.reddit_json_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Clear cache
            from sentiment.reddit_json_source import _cache
            _cache.clear()
            source._last_request_time = 0

            result = await source.fetch("AAPL")

        assert result["mention_count"] == 2
        assert len(result["posts"]) == 2
        # Sorted by score descending
        assert result["posts"][0].score == 100
        assert result["posts"][1].score == 42

    @pytest.mark.asyncio
    async def test_fetch_returns_reddit_posts(self, source):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE

        with patch("sentiment.reddit_json_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from sentiment.reddit_json_source import _cache
            _cache.clear()
            source._last_request_time = 0

            result = await source.fetch("AAPL")

        post = result["posts"][1]  # second by score
        assert post.subreddit == "pennystocks"
        assert post.title == "AAPL is going to the moon"
        assert post.author == "trader123"
        assert post.num_comments == 15
        assert post.url.startswith("https://reddit.com/")

    @pytest.mark.asyncio
    async def test_fetch_handles_429(self, source):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "1"}

        with patch("sentiment.reddit_json_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from sentiment.reddit_json_source import _cache
            _cache.clear()
            source._last_request_time = 0

            result = await source.fetch("AAPL")

        assert result["mention_count"] == 0
        assert result["posts"] == []

    @pytest.mark.asyncio
    async def test_fetch_handles_empty_response(self, source):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"children": []}}

        with patch("sentiment.reddit_json_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from sentiment.reddit_json_source import _cache
            _cache.clear()
            source._last_request_time = 0

            result = await source.fetch("XXXX")

        assert result["mention_count"] == 0

    @pytest.mark.asyncio
    async def test_caching(self, source):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE

        with patch("sentiment.reddit_json_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from sentiment.reddit_json_source import _cache
            _cache.clear()
            source._last_request_time = 0

            # First call — hits API
            result1 = await source.fetch("AAPL")
            assert result1["mention_count"] == 2

            # Second call — should use cache (no API call)
            mock_client.get.reset_mock()
            result2 = await source.fetch("AAPL")
            assert result2["mention_count"] == 2
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_handles_network_error(self, source):
        with patch("sentiment.reddit_json_source.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from sentiment.reddit_json_source import _cache
            _cache.clear()
            source._last_request_time = 0

            result = await source.fetch("AAPL")

        assert result["mention_count"] == 0
        assert result["posts"] == []
