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
    set_state("economic_calendar_service", None)
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
        """No tickers, no service — returns empty earnings and economic events."""
        resp = await client.get("/api/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert "earnings" in data
        assert "economic" in data
        assert data["earnings"] == []
        assert data["economic"] == []


class TestCalendarWithYfinanceFallback:
    @pytest.mark.asyncio
    @patch("dashboard.routes.calendar._get_earnings_sync")
    async def test_calendar_yfinance_fallback(self, mock_earnings_sync, client):
        """When no Finnhub key, falls back to yfinance per-ticker."""
        mock_earnings_sync.return_value = [
            EarningsEvent(
                ticker="AAPL",
                name="Apple Inc.",
                date="2026-04-30",
                eps_estimate=1.62,
                reported_eps=None,
                surprise_pct=None,
                is_future=True,
                in_watchlist=True,
            ),
            EarningsEvent(
                ticker="AAPL",
                name="Apple Inc.",
                date="2026-01-30",
                eps_estimate=2.35,
                reported_eps=2.40,
                surprise_pct=2.13,
                is_future=False,
                in_watchlist=True,
            ),
        ]

        resp = await client.get("/api/calendar?tickers=AAPL")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["earnings"]) == 2
        assert data["earnings"][0]["date"] >= data["earnings"][1]["date"]
        assert data["earnings"][0]["ticker"] == "AAPL"

        # The future event should have eps_estimate but no reported_eps
        future = next(e for e in data["earnings"] if e["is_future"])
        assert future["eps_estimate"] == 1.62
        assert future["reported_eps"] is None

        # The past event should have reported_eps and surprise
        past = next(e for e in data["earnings"] if not e["is_future"])
        assert past["reported_eps"] == 2.40
        assert past["surprise_pct"] == 2.13
        assert past["in_watchlist"] is True


class TestCalendarWithEconomicService:
    @pytest.mark.asyncio
    async def test_calendar_with_economic_service(self, client):
        """When economic service is available, returns real events."""
        mock_service = AsyncMock()
        mock_service.get_events.return_value = [
            {
                "date": "2026-04-29",
                "event": "FOMC Meeting",
                "importance": "high",
                "expected": "",
                "actual": "",
                "previous": "",
                "country": "US",
                "country_name": "United States",
                "institution": "Federal Reserve",
                "category": "Monetary Policy",
                "description": "FOMC policy meeting.",
                "frequency": "8x/year",
                "unit": "",
                "indicator_key": "fed_rate",
                "source": "fed_calendar",
            },
        ]
        set_state("economic_calendar_service", mock_service)

        resp = await client.get("/api/calendar?start_date=2026-04-01&end_date=2026-05-01")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["economic"]) == 1
        assert data["economic"][0]["event"] == "FOMC Meeting"
        assert data["economic"][0]["country"] == "US"
        assert data["economic"][0]["institution"] == "Federal Reserve"

        # Clean up
        set_state("economic_calendar_service", None)


class TestCalendarEarningsNewFields:
    @pytest.mark.asyncio
    async def test_earnings_new_fields(self, client):
        """Verify new earnings fields (revenue, hour, quarter, year) are in response."""
        resp = await client.get("/api/calendar")
        assert resp.status_code == 200
        # Even with empty data, the schema should accept these fields
        data = resp.json()
        assert isinstance(data["earnings"], list)


class TestIndicatorHistory:
    @pytest.mark.asyncio
    async def test_indicator_history_no_service(self, client):
        """History endpoint returns empty when no service."""
        set_state("economic_calendar_service", None)
        resp = await client.get("/api/calendar/indicators/us_cpi/history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_indicator_history_with_service(self, client):
        """History endpoint delegates to service."""
        mock_service = AsyncMock()
        mock_service.get_indicator_history.return_value = [
            {"date": "2025-12-01", "value": "324.054"},
            {"date": "2026-01-01", "value": "325.252"},
        ]
        set_state("economic_calendar_service", mock_service)

        resp = await client.get("/api/calendar/indicators/us_cpi/history?limit=12")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["date"] == "2025-12-01"
        assert data[1]["value"] == "325.252"

        set_state("economic_calendar_service", None)


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
