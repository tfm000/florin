"""Tests for Calendar and News Feed API endpoints."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from dashboard.routes.calendar import EarningsEvent, EconomicEvent
from db.database import Database
from news.scraper import RawArticle


@pytest.fixture
async def app():
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()

    yf_mock = AsyncMock()
    yf_mock.get_history.return_value = []
    yf_mock.get_info.return_value = {}

    app = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("rf_fetcher", None)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ============================================================================
# Calendar routes
# ============================================================================


class TestCalendarEmpty:
    @pytest.mark.asyncio
    async def test_calendar_empty(self, client):
        """No tickers, no date range — returns empty earnings and default economic events."""
        resp = await client.get("/api/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert "earnings" in data
        assert "economic" in data
        assert data["earnings"] == []
        # Economic events use defaults (current year start to 2027-12-31),
        # so there will be some events generated from the static schedule.
        assert isinstance(data["economic"], list)


class TestCalendarWithTickers:
    @pytest.mark.asyncio
    @patch("dashboard.routes.calendar._get_earnings_sync")
    async def test_calendar_with_tickers(self, mock_earnings_sync, client):
        """With tickers provided, earnings data is returned from mocked yfinance."""
        mock_earnings_sync.return_value = [
            EarningsEvent(
                ticker="AAPL",
                name="Apple Inc.",
                date="2026-04-30",
                eps_estimate=1.62,
                reported_eps=None,
                surprise_pct=None,
                is_future=True,
            ),
            EarningsEvent(
                ticker="AAPL",
                name="Apple Inc.",
                date="2026-01-30",
                eps_estimate=2.35,
                reported_eps=2.40,
                surprise_pct=2.13,
                is_future=False,
            ),
        ]

        resp = await client.get("/api/calendar?tickers=AAPL")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["earnings"]) == 2
        # Results are sorted by date descending
        assert data["earnings"][0]["date"] >= data["earnings"][1]["date"]
        assert data["earnings"][0]["ticker"] == "AAPL"
        assert data["earnings"][0]["name"] == "Apple Inc."

        # The future event should have eps_estimate but no reported_eps
        future = next(e for e in data["earnings"] if e["is_future"])
        assert future["eps_estimate"] == 1.62
        assert future["reported_eps"] is None

        # The past event should have reported_eps and surprise
        past = next(e for e in data["earnings"] if not e["is_future"])
        assert past["reported_eps"] == 2.40
        assert past["surprise_pct"] == 2.13


class TestCalendarWithDateRange:
    @pytest.mark.asyncio
    @patch("dashboard.routes.calendar._get_economic_events")
    async def test_calendar_with_date_range(self, mock_econ_events, client):
        """With start/end dates, economic events are returned for that range."""
        mock_econ_events.return_value = [
            EconomicEvent(
                date="2026-03-18",
                event="FOMC Rate Decision",
                importance="high",
                expected="",
                actual="",
                previous="",
            ),
            EconomicEvent(
                date="2026-03-13",
                event="CPI Release (YoY)",
                importance="high",
                expected="2.5%",
                actual="",
                previous="2.4%",
            ),
        ]

        resp = await client.get(
            "/api/calendar?start_date=2026-03-01&end_date=2026-03-31"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["economic"]) == 2
        events_by_name = {e["event"]: e for e in data["economic"]}
        assert "FOMC Rate Decision" in events_by_name
        assert "CPI Release (YoY)" in events_by_name

        cpi = events_by_name["CPI Release (YoY)"]
        assert cpi["date"] == "2026-03-13"
        assert cpi["expected"] == "2.5%"
        assert cpi["previous"] == "2.4%"

        # Verify mock was called with the date range params
        mock_econ_events.assert_called_once_with("2026-03-01", "2026-03-31")


# ============================================================================
# News feed routes
# ============================================================================


class TestNewsFeedBasic:
    @pytest.mark.asyncio
    @patch("news.scraper.scrape_all_feeds")
    async def test_news_feed_basic(self, mock_scrape, client):
        """Returns news stories from mocked RSS scraper."""
        mock_scrape.return_value = [
            RawArticle(
                headline="Fed Holds Rates Steady",
                excerpt="The Federal Reserve kept interest rates unchanged.",
                url="https://example.com/fed-rates",
                pub_date=datetime(2026, 3, 20, 14, 0, 0),
                source="Reuters Business",
            ),
            RawArticle(
                headline="Tech Stocks Rally",
                excerpt="Major tech indices surged on positive earnings.",
                url="https://example.com/tech-rally",
                pub_date=datetime(2026, 3, 19, 10, 30, 0),
                source="CNBC Top News",
            ),
        ]

        resp = await client.get("/api/news/feed")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data) == 2
        assert data[0]["headline"] == "Fed Holds Rates Steady"
        assert data[0]["excerpt"] == "The Federal Reserve kept interest rates unchanged."
        assert data[0]["url"] == "https://example.com/fed-rates"
        assert data[0]["source"] == "Reuters Business"
        assert data[0]["pub_date"] != ""

        assert data[1]["headline"] == "Tech Stocks Rally"
        assert data[1]["source"] == "CNBC Top News"

        mock_scrape.assert_called_once()


class TestNewsFeedEmpty:
    @pytest.mark.asyncio
    @patch("news.scraper.scrape_all_feeds")
    async def test_news_feed_empty(self, mock_scrape, client):
        """No news available — returns empty list."""
        mock_scrape.return_value = []

        resp = await client.get("/api/news/feed")
        assert resp.status_code == 200
        data = resp.json()

        assert data == []
        mock_scrape.assert_called_once()
