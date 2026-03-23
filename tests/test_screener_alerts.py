"""Tests for Phase 7: Screener Alert Service, API endpoints, and Telegram formatting."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus, EventType
from dashboard.app import create_app
from dashboard.deps import set_state
from dashboard.services.screener_engine import (
    ScreenerResult,
    parse_filters_to_kwargs,
)
from db.database import Database
from db.models import SavedScreenerORM, ScreenerAlertLogORM
from scanner.screener_alert_service import ScreenerAlertService
from telegram_bot.formatters import format_screener_alert_message


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def db():
    """In-memory SQLite database for tests."""
    database = Database("sqlite+aiosqlite://")
    await database.init()
    await database.run_migrations()
    yield database
    await database.close()


@pytest.fixture
async def app(db):
    """Create a test app with in-memory database."""
    settings = Settings(
        alpaca_api_key="test", alpaca_api_secret="test",
        database_url="sqlite+aiosqlite://",
    )
    event_bus = EventBus()
    set_state("db", db)
    set_state("event_bus", event_bus)
    set_state("settings", settings)
    set_state("screener_alert_service", None)

    app = create_app(settings, db, event_bus)
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def seed_screener(db):
    """Seed a saved screener and return its ID."""
    async with db.session() as session:
        now = datetime.now(UTC)
        orm = SavedScreenerORM(
            id="test_screener1",
            name="Test Screener",
            filters_json=json.dumps({"price_min": 10, "sector": "Technology"}),
            sort_by="intradaymarketcap",
            sort_asc=False,
            is_alert_active=True,
            max_alerts_per_day=5,
            run_interval_seconds=300,
            created_at=now,
            updated_at=now,
        )
        session.add(orm)
        await session.commit()
    return "test_screener1"


# =============================================================================
# parse_filters_to_kwargs tests
# =============================================================================


class TestParseFilters:
    def test_empty_filters(self):
        result = parse_filters_to_kwargs({})
        assert result["price_min"] == 0
        assert result["price_max"] == 0
        assert result["sector"] == ""

    def test_full_filters(self):
        filters = {
            "price_min": "10",
            "price_max": "500",
            "market_cap_min": "1000000",
            "sector": "Technology",
            "exchange": "NMS,NGM",
            "asset_type": "EQUITY",
        }
        result = parse_filters_to_kwargs(filters)
        assert result["price_min"] == 10.0
        assert result["price_max"] == 500.0
        assert result["market_cap_min"] == 1_000_000.0
        assert result["sector"] == "Technology"
        assert result["exchange"] == "NMS,NGM"
        assert result["asset_type"] == "EQUITY"

    def test_handles_none_values(self):
        filters = {"price_min": None, "price_max": None, "sector": None}
        result = parse_filters_to_kwargs(filters)
        assert result["price_min"] == 0
        assert result["price_max"] == 0
        assert result["sector"] == ""

    def test_handles_empty_strings(self):
        filters = {"price_min": "", "sector": ""}
        result = parse_filters_to_kwargs(filters)
        assert result["price_min"] == 0
        assert result["sector"] == ""


# =============================================================================
# ScreenerAlertService tests
# =============================================================================


class TestScreenerAlertService:
    @pytest.mark.asyncio
    async def test_should_run_first_time(self, db):
        """Screener that has never run should be eligible."""
        svc = ScreenerAlertService(db, EventBus())
        screener = MagicMock()
        screener.last_run_at = None
        screener.run_interval_seconds = 300
        assert svc._should_run(screener) is True

    @pytest.mark.asyncio
    async def test_should_run_after_interval(self, db):
        """Screener should run if enough time has passed."""
        svc = ScreenerAlertService(db, EventBus())
        screener = MagicMock()
        screener.last_run_at = datetime.now(UTC) - timedelta(seconds=600)
        screener.run_interval_seconds = 300
        assert svc._should_run(screener) is True

    @pytest.mark.asyncio
    async def test_should_not_run_too_soon(self, db):
        """Screener should not run if interval hasn't elapsed."""
        svc = ScreenerAlertService(db, EventBus())
        screener = MagicMock()
        screener.last_run_at = datetime.now(UTC) - timedelta(seconds=100)
        screener.run_interval_seconds = 300
        assert svc._should_run(screener) is False

    @pytest.mark.asyncio
    async def test_deduplication(self, db, seed_screener):
        """Should not re-alert tickers already alerted today."""
        svc = ScreenerAlertService(db, EventBus())

        # Log an alert for AAPL today
        async with db.session() as session:
            session.add(ScreenerAlertLogORM(
                screener_id=seed_screener,
                ticker="AAPL",
                price=150.0,
                sent_at=datetime.now(UTC),
            ))
            await session.commit()

        alerted = await svc._get_alerted_tickers_today(seed_screener)
        assert "AAPL" in alerted
        assert "TSLA" not in alerted

    @pytest.mark.asyncio
    async def test_daily_counter_reset(self, db, seed_screener):
        """Daily counter reset should zero alerts_sent_today."""
        # Set a non-zero counter
        async with db.session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(SavedScreenerORM).where(SavedScreenerORM.id == seed_screener)
            )
            orm = result.scalar()
            orm.alerts_sent_today = 5
            await session.commit()

        svc = ScreenerAlertService(db, EventBus())
        svc._last_reset_date = None  # Force reset
        await svc._maybe_reset_daily_counters()

        async with db.session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(SavedScreenerORM).where(SavedScreenerORM.id == seed_screener)
            )
            orm = result.scalar()
            assert orm.alerts_sent_today == 0

    @pytest.mark.asyncio
    async def test_log_alert(self, db, seed_screener):
        """Should persist alert to screener_alert_log."""
        svc = ScreenerAlertService(db, EventBus())
        result = ScreenerResult(
            ticker="MSFT", name="Microsoft", price=400.0,
            change_pct=2.5, sector="Technology",
        )
        await svc._log_alert(seed_screener, result)

        async with db.session() as session:
            from sqlalchemy import select
            res = await session.execute(
                select(ScreenerAlertLogORM).where(
                    ScreenerAlertLogORM.screener_id == seed_screener
                )
            )
            logs = res.scalars().all()
            assert len(logs) == 1
            assert logs[0].ticker == "MSFT"
            assert logs[0].price == 400.0

    @pytest.mark.asyncio
    async def test_run_screener_publishes_events(self, db, seed_screener):
        """Should publish SCREENER_ALERT events for new matches."""
        event_bus = EventBus()
        svc = ScreenerAlertService(db, event_bus)

        mock_results = [
            ScreenerResult(ticker="NVDA", name="NVIDIA", price=800.0, change_pct=3.0),
            ScreenerResult(ticker="AAPL", name="Apple", price=180.0, change_pct=1.5),
        ]

        with patch("scanner.screener_alert_service.run_screen", return_value=(mock_results, len(mock_results))):
            # Subscribe before running
            events = []

            async def collect():
                async for event in event_bus.subscribe(EventType.SCREENER_ALERT):
                    events.append(event)
                    if len(events) >= 2:
                        break

            import asyncio
            # Load the screener ORM
            async with db.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(SavedScreenerORM).where(SavedScreenerORM.id == seed_screener)
                )
                screener = result.scalar()

            collector = asyncio.create_task(collect())
            await svc._run_screener(screener)

            # Give collector a moment to process
            await asyncio.sleep(0.1)
            collector.cancel()

            assert len(events) == 2
            assert events[0].data["ticker"] == "NVDA"
            assert events[1].data["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_max_alerts_per_day_enforcement(self, db, seed_screener):
        """Should not exceed max_alerts_per_day."""
        event_bus = EventBus()
        svc = ScreenerAlertService(db, event_bus)

        # Set alerts_sent_today to max_alerts_per_day - 1
        async with db.session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(SavedScreenerORM).where(SavedScreenerORM.id == seed_screener)
            )
            orm = result.scalar()
            orm.alerts_sent_today = 4  # max is 5, so only 1 more allowed
            await session.commit()

        mock_results = [
            ScreenerResult(ticker="NVDA", name="NVIDIA", price=800.0),
            ScreenerResult(ticker="AAPL", name="Apple", price=180.0),
            ScreenerResult(ticker="MSFT", name="Microsoft", price=400.0),
        ]

        with patch("scanner.screener_alert_service.run_screen", return_value=(mock_results, len(mock_results))):
            async with db.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(SavedScreenerORM).where(SavedScreenerORM.id == seed_screener)
                )
                screener = result.scalar()

            await svc._run_screener(screener)

        # Should have logged only 1 alert (5 - 4 = 1 remaining)
        async with db.session() as session:
            from sqlalchemy import select
            logs = await session.execute(
                select(ScreenerAlertLogORM).where(
                    ScreenerAlertLogORM.screener_id == seed_screener
                )
            )
            assert len(logs.scalars().all()) == 1

    def test_summarize_filters(self):
        svc = ScreenerAlertService.__new__(ScreenerAlertService)
        assert "Technology" in svc._summarize_filters({"sector": "Technology"})
        assert "All US assets" == svc._summarize_filters({})
        summary = svc._summarize_filters({"price_min": 10, "price_max": 500})
        assert "$10" in summary
        assert "$500" in summary


# =============================================================================
# API endpoint tests
# =============================================================================


class TestScreenerAlertEndpoints:
    @pytest.mark.asyncio
    async def test_update_alert_settings(self, client, seed_screener):
        """PUT /api/screener/saved/{id}/alerts should update alert fields."""
        resp = await client.put(
            f"/api/screener/saved/{seed_screener}/alerts",
            json={
                "is_alert_active": False,
                "max_alerts_per_day": 20,
                "run_interval_seconds": 900,
                "include_llm_report": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_alert_active"] is False
        assert data["max_alerts_per_day"] == 20
        assert data["run_interval_seconds"] == 900
        assert data["include_llm_report"] is True

    @pytest.mark.asyncio
    async def test_update_alert_settings_partial(self, client, seed_screener):
        """Should allow partial updates."""
        resp = await client.put(
            f"/api/screener/saved/{seed_screener}/alerts",
            json={"max_alerts_per_day": 50},
        )
        assert resp.status_code == 200
        assert resp.json()["max_alerts_per_day"] == 50
        assert resp.json()["is_alert_active"] is True  # unchanged

    @pytest.mark.asyncio
    async def test_update_alert_settings_not_found(self, client):
        """Should 404 for nonexistent screener."""
        resp = await client.put(
            "/api/screener/saved/nonexistent/alerts",
            json={"is_alert_active": True},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_alert_log_empty(self, client, seed_screener):
        """GET /api/screener/saved/{id}/alerts should return empty list initially."""
        resp = await client.get(f"/api/screener/saved/{seed_screener}/alerts")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_alert_log_with_entries(self, client, db, seed_screener):
        """Should return alert log entries."""
        async with db.session() as session:
            for ticker in ["AAPL", "MSFT", "NVDA"]:
                session.add(ScreenerAlertLogORM(
                    screener_id=seed_screener,
                    ticker=ticker,
                    price=100.0,
                    change_pct=1.5,
                    sent_at=datetime.now(UTC),
                ))
            await session.commit()

        resp = await client.get(f"/api/screener/saved/{seed_screener}/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # Should be ordered by sent_at desc
        tickers = [a["ticker"] for a in data]
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "NVDA" in tickers

    @pytest.mark.asyncio
    async def test_get_alert_log_not_found(self, client):
        """Should 404 for nonexistent screener."""
        resp = await client.get("/api/screener/saved/nonexistent/alerts")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_saved_screener_response_includes_alert_fields(self, client, seed_screener):
        """GET /api/screener/saved should include run_interval_seconds and last_run_at."""
        resp = await client.get("/api/screener/saved")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        s = data[0]
        assert "run_interval_seconds" in s
        assert "last_run_at" in s
        assert s["run_interval_seconds"] == 300
        assert s["last_run_at"] is None


# =============================================================================
# Telegram formatter tests
# =============================================================================


class TestScreenerAlertFormatter:
    def test_basic_formatting(self):
        msg = format_screener_alert_message({
            "screener_name": "High Cap Tech",
            "ticker": "AAPL",
            "name": "Apple Inc",
            "price": 180.50,
            "change_pct": 2.35,
            "market_cap": 2800000000000,
            "volume": 45000000,
            "sector": "Technology",
            "exchange": "NMS",
            "filters_summary": "Price: $100-$500 | Technology",
        })
        assert "AAPL" in msg
        assert "Apple" in msg
        assert "High Cap Tech" in msg
        assert "180\\.50" in msg  # escaped for MarkdownV2
        assert "Technology" in msg

    def test_negative_change(self):
        msg = format_screener_alert_message({
            "ticker": "TSLA",
            "change_pct": -3.5,
        })
        assert "TSLA" in msg
        assert "\\-3\\.50" in msg

    def test_missing_fields(self):
        """Should not crash with minimal data."""
        msg = format_screener_alert_message({"ticker": "XYZ"})
        assert "XYZ" in msg

    def test_large_market_cap_formatting(self):
        msg = format_screener_alert_message({
            "ticker": "AAPL",
            "market_cap": 2_800_000_000_000,
        })
        assert "2\\.8T" in msg

    def test_billion_market_cap_formatting(self):
        msg = format_screener_alert_message({
            "ticker": "XYZ",
            "market_cap": 50_000_000_000,
        })
        assert "50\\.0B" in msg

    def test_million_market_cap_formatting(self):
        msg = format_screener_alert_message({
            "ticker": "XYZ",
            "market_cap": 500_000_000,
        })
        assert "500M" in msg
