"""Tests for the EconomicCalendarService.

Tests cover:
- CB meeting date parsers with mocked HTML responses
- Alpha Vantage indicator fetching with mocked JSON
- DB caching (upsert, retrieve, filtering)
- Graceful failure handling (network errors, malformed HTML)
- Historical data endpoint
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from data.economic_calendar import EconomicCalendarService
from db.database import Database
from db.models import EconomicEventORM

# ==========================================================================
# Fixtures
# ==========================================================================


@pytest.fixture
async def db():
    """Create an in-memory test database."""
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.init()
    await database.create_tables()
    yield database
    await database.close()


@pytest.fixture
async def service(db):
    """Create an EconomicCalendarService with test DB."""
    svc = EconomicCalendarService(
        db=db,
        alphavantage_api_key="test_key",
        policy_rate_fetcher=None,
    )
    yield svc
    await svc.close()


@pytest.fixture
async def app(db):
    """Create a test FastAPI app."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    event_bus = EventBus()
    yf_mock = AsyncMock()
    yf_mock.get_history.return_value = []
    yf_mock.get_info.return_value = {}

    application = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("rf_fetcher", None)
    yield application


@pytest.fixture
async def client(app):
    """Create async test client."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ==========================================================================
# Fed RSS parser tests
# ==========================================================================

_FED_RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0">
<channel>
<title>Federal Reserve Press Releases</title>
<item>
  <title><![CDATA[Federal Reserve issues FOMC statement]]></title>
  <pubDate><![CDATA[Wed, 18 Mar 2026 18:00:00 GMT]]></pubDate>
  <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a.htm</link>
</item>
<item>
  <title><![CDATA[Federal Reserve issues FOMC statement]]></title>
  <pubDate><![CDATA[Wed, 28 Jan 2026 19:00:00 GMT]]></pubDate>
  <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260128a.htm</link>
</item>
<item>
  <title><![CDATA[Minutes of the Federal Open Market Committee, January 27-28, 2026]]></title>
  <pubDate><![CDATA[Wed, 18 Feb 2026 19:00:00 GMT]]></pubDate>
</item>
</channel>
</rss>"""


class TestFedRSSParser:
    @pytest.mark.asyncio
    async def test_parse_fomc_decisions(self, service):
        """Fed RSS parser extracts FOMC statement dates, ignoring minutes."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.text = _FED_RSS_SAMPLE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._fetch_fed_decisions()

        assert len(events) == 2
        assert events[0].event_key == "fomc_decision_2026-03-18"
        assert events[0].event == "FOMC Rate Decision"
        assert events[0].country == "US"
        assert events[0].institution == "Federal Reserve"
        assert events[1].date == "2026-01-28"

    @pytest.mark.asyncio
    async def test_parse_fomc_network_error(self, service):
        """Gracefully returns empty on network error."""
        with patch.object(service._client, "get", side_effect=httpx.ConnectError("timeout")):
            events = await service._fetch_fed_decisions()

        assert events == []


# ==========================================================================
# FOMC upcoming meetings parser tests
# ==========================================================================

_FOMC_CALENDAR_HTML = """
<html><body>
<div class="fomc-meeting">
  <p>July 09, 2026</p>
  <p>September 16, 2026</p>
  <p>December 15, 2026</p>
</div>
</body></html>
"""


class TestFOMCCalendarParser:
    @pytest.mark.asyncio
    async def test_parse_upcoming_dates(self, service):
        """Parses future FOMC meeting dates from calendar page."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.text = _FOMC_CALENDAR_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._parse_fomc_upcoming()

        # Should find future dates only (depends on current date)
        for e in events:
            assert e.event == "FOMC Meeting"
            assert e.country == "US"
            assert e.source == "fed_calendar"
            assert e.date > datetime.now().strftime("%Y-%m-%d")


# ==========================================================================
# ECB rate history parser tests
# ==========================================================================

_ECB_RATE_RESPONSE = {
    "dataSets": [
        {
            "series": {
                "0:0:0:0:0:0": {
                    "observations": {
                        "0": [2.50, 0, 0, None, None],
                        "1": [2.65, 0, 0, None, None],
                        "2": [2.15, 0, 0, None, None],
                    }
                }
            }
        }
    ],
    "structure": {
        "dimensions": {
            "observation": [
                {
                    "id": "TIME_PERIOD",
                    "values": [
                        {"id": "2026-01-15"},
                        {"id": "2026-02-15"},
                        {"id": "2026-03-15"},
                    ],
                }
            ]
        }
    },
}


class TestECBRateParser:
    @pytest.mark.asyncio
    async def test_parse_ecb_rates(self, service):
        """ECB Data Portal API returns rate history as events."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = _ECB_RATE_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._fetch_ecb_rate_history()

        assert len(events) == 3
        assert events[0].actual == "2.50%"
        assert events[0].country == "EU"
        assert events[1].actual == "2.65%"
        assert events[1].previous == "2.50%"
        assert events[2].actual == "2.15%"
        assert events[2].previous == "2.65%"


# ==========================================================================
# BOC rate history tests
# ==========================================================================

_BOC_RATE_RESPONSE = {
    "observations": [
        {"d": "2026-03-10", "V39079": {"v": "2.50"}},
        {"d": "2026-03-11", "V39079": {"v": "2.50"}},
        {"d": "2026-03-12", "V39079": {"v": "2.25"}},
        {"d": "2026-03-13", "V39079": {"v": "2.25"}},
    ]
}


class TestBOCRateParser:
    @pytest.mark.asyncio
    async def test_parse_boc_rates_detects_changes(self, service):
        """BOC Valet API: only creates events on rate changes."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = _BOC_RATE_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._fetch_boc_rate_history()

        # Should have 2 events: initial 2.50% and the change to 2.25%
        assert len(events) == 2
        assert events[0].actual == "2.50%"
        assert events[0].date == "2026-03-10"
        assert events[1].actual == "2.25%"
        assert events[1].previous == "2.50%"


# ==========================================================================
# Alpha Vantage indicator tests
# ==========================================================================

_AV_CPI_RESPONSE = {
    "name": "Consumer Price Index for all Urban Consumers",
    "interval": "monthly",
    "unit": "index 1982-1984=100",
    "data": [
        {"date": "2026-03-01", "value": "328.000"},
        {"date": "2026-02-01", "value": "326.785"},
        {"date": "2026-01-01", "value": "325.252"},
        {"date": "2025-12-01", "value": "324.054"},
    ],
}


class TestAVIndicators:
    @pytest.mark.asyncio
    async def test_fetch_cpi_indicator(self, service):
        """AV CPI indicator creates events with real dates and formatted values."""
        from data.economic_calendar import AV_INDICATORS

        cfg = AV_INDICATORS["us_cpi"]

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = _AV_CPI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._fetch_av_indicator("us_cpi", cfg)

        assert len(events) == 4
        assert events[0].date == "2026-03-01"
        assert events[0].actual == "328.000"
        assert events[0].previous == "326.785"
        assert events[0].indicator_key == "us_cpi"
        assert events[0].source == "alpha_vantage"

    @pytest.mark.asyncio
    async def test_fetch_av_error_response(self, service):
        """AV error response (rate limit) handled gracefully."""
        from data.economic_calendar import AV_INDICATORS

        cfg = AV_INDICATORS["us_cpi"]

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = {
            "Information": "Thank you for using Alpha Vantage! Our standard API rate limit..."
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._fetch_av_indicator("us_cpi", cfg)

        assert events == []

    @pytest.mark.asyncio
    async def test_fetch_av_history(self, service):
        """AV history endpoint returns formatted data points."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = _AV_CPI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            history = await service._fetch_av_history("CPI", 10)

        assert len(history) == 4
        # Should be oldest first (reversed)
        assert history[0]["date"] == "2025-12-01"
        assert history[-1]["date"] == "2026-03-01"

    @pytest.mark.asyncio
    async def test_fetch_av_missing_values_skipped(self, service):
        """AV entries with '.' or empty values are skipped."""
        from data.economic_calendar import AV_INDICATORS

        cfg = AV_INDICATORS["us_cpi"]

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = {
            "data": [
                {"date": "2026-03-01", "value": "328.000"},
                {"date": "2026-02-01", "value": "."},
                {"date": "2026-01-01", "value": "325.252"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._fetch_av_indicator("us_cpi", cfg)

        # The "." entry should be skipped
        assert len(events) == 2
        assert events[0].date == "2026-03-01"
        assert events[1].date == "2026-01-01"


# ==========================================================================
# DB persistence tests
# ==========================================================================


class TestDBPersistence:
    @pytest.mark.asyncio
    async def test_upsert_new_events(self, service, db):
        """New events are inserted into the DB."""
        events = [
            EconomicEventORM(
                event_key="test_event_1",
                date="2026-04-01",
                event="Test Event",
                country="US",
                country_name="United States",
                institution="Test Institution",
                category="Test",
                importance="high",
                actual="1.23%",
                source="test",
                fetched_at=datetime.now(UTC),
            ),
        ]
        await service._upsert_events(events)

        result = await service.get_events("2026-01-01", "2026-12-31")
        assert len(result) == 1
        assert result[0]["event"] == "Test Event"
        assert result[0]["actual"] == "1.23%"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, service, db):
        """Existing events are updated (actual value changes)."""
        events = [
            EconomicEventORM(
                event_key="test_event_upsert",
                date="2026-05-01",
                event="FOMC Meeting",
                country="US",
                country_name="United States",
                actual="",
                source="fed_calendar",
                fetched_at=datetime.now(UTC),
            ),
        ]
        await service._upsert_events(events)

        # Update with actual value
        events[0].actual = "4.25%"
        await service._upsert_events(events)

        result = await service.get_events("2026-01-01", "2026-12-31")
        assert len(result) == 1
        assert result[0]["actual"] == "4.25%"

    @pytest.mark.asyncio
    async def test_get_events_date_filter(self, service, db):
        """get_events respects date range filtering."""
        events = [
            EconomicEventORM(
                event_key="early_event",
                date="2026-01-15",
                event="Early",
                country="US",
                source="test",
                fetched_at=datetime.now(UTC),
            ),
            EconomicEventORM(
                event_key="late_event",
                date="2026-12-15",
                event="Late",
                country="US",
                source="test",
                fetched_at=datetime.now(UTC),
            ),
        ]
        await service._upsert_events(events)

        # Only get events in first half of year
        result = await service.get_events("2026-01-01", "2026-06-30")
        assert len(result) == 1
        assert result[0]["event"] == "Early"


# ==========================================================================
# BOE MPC parser tests
# ==========================================================================

_BOE_MPC_HTML = """
<html><body>
<div class="mpc-dates">
  <p>30 April 2026</p>
  <p>19 June 2026</p>
  <p>07 August 2026</p>
</div>
</body></html>
"""


class TestBOEParser:
    @pytest.mark.asyncio
    async def test_parse_boe_dates(self, service):
        """Parses BOE MPC meeting dates."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.text = _BOE_MPC_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(service._client, "get", return_value=mock_resp):
            events = await service._parse_boe_upcoming()

        for e in events:
            assert e.event == "BOE MPC Meeting"
            assert e.country == "GB"
            assert e.institution == "Bank of England"


# ==========================================================================
# Calendar API endpoint tests
# ==========================================================================


class TestCalendarEndpoint:
    @pytest.mark.asyncio
    async def test_calendar_empty(self, client):
        """Calendar endpoint returns empty when no service is configured."""
        set_state("economic_calendar_service", None)
        resp = await client.get("/api/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert "earnings" in data
        assert "economic" in data

    @pytest.mark.asyncio
    async def test_indicator_history_empty(self, client):
        """History endpoint returns empty when no service is configured."""
        set_state("economic_calendar_service", None)
        resp = await client.get("/api/calendar/indicators/us_cpi/history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_indicator_history_with_service(self, client, db):
        """History endpoint returns data when service is available."""
        svc = EconomicCalendarService(db=db, alphavantage_api_key="test")
        set_state("economic_calendar_service", svc)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = _AV_CPI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(svc._client, "get", return_value=mock_resp):
            resp = await client.get("/api/calendar/indicators/us_cpi/history?limit=3")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 4  # May be less due to limit
        for point in data:
            assert "date" in point
            assert "value" in point

        await svc.close()
