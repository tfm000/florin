"""Contract test for the shared period vocabulary.

REQ TEST-03 / BUG-03 / D-16.4: every period token in the canonical
vocabulary MUST be accepted by every period-validating endpoint, and
known-invalid tokens MUST be rejected with 422. This test is the
regression net for the bug class where PeriodSelector.jsx and
dashboard/routes/research.py drift apart.

The per-endpoint subset Literals (YieldCurvePeriod, SectorPeriod) are
honored: yield-curve and sectors test against their narrower vocabulary,
not the full HISTORICAL_PERIODS, because those routes legitimately
serve fewer tokens.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from config.periods import HISTORICAL_PERIODS, SECTOR_PERIODS, YIELD_CURVE_PERIODS
from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database


@pytest.fixture
async def client():
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()

    yf_mock = AsyncMock()
    # Contract test cares about status codes (422 vs not-422), not data shape.
    yf_mock.get_history.return_value = []
    yf_mock.get_quotes.return_value = []
    yf_mock.get_yield_curve_history.return_value = {"dates": [], "tenors": {}}
    yf_mock.get_sectors_history.return_value = {"dates": [], "series": {}}

    event_bus = EventBus()
    app = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    set_state("event_bus", event_bus)
    set_state("rf_fetcher", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await db.close()


@pytest.mark.parametrize("period", HISTORICAL_PERIODS)
async def test_asset_history_accepts_every_canonical_period(client, period):
    """/research/asset/{ticker}/history MUST accept every canonical period token."""
    resp = await client.get(
        f"/api/research/asset/AAPL/history?period={period}&interval=1d",
    )
    assert resp.status_code != 422, (
        f"period={period!r} was rejected by /research/asset/{{ticker}}/history — "
        f"vocabulary drift between config/periods.json and dashboard/routes/research.py"
    )


@pytest.mark.parametrize("period", HISTORICAL_PERIODS)
async def test_asset_quotes_accepts_every_canonical_period(client, period):
    """/research/asset/{ticker}/quotes MUST accept every canonical period token."""
    resp = await client.get(
        f"/api/research/asset/AAPL/quotes?period={period}&interval=1d",
    )
    assert resp.status_code != 422, (
        f"period={period!r} was rejected by /research/asset/{{ticker}}/quotes"
    )


@pytest.mark.parametrize("period", YIELD_CURVE_PERIODS)
async def test_yield_curve_history_accepts_subset(client, period):
    """/research/yield-curve/history MUST accept every period in the YieldCurvePeriod subset."""
    resp = await client.get(f"/api/research/yield-curve/history?period={period}")
    assert resp.status_code != 422, (
        f"period={period!r} was rejected by /research/yield-curve/history (YieldCurvePeriod subset)"
    )


@pytest.mark.parametrize("period", SECTOR_PERIODS)
async def test_sectors_history_accepts_subset(client, period):
    """/research/sectors/history MUST accept every period in the SectorPeriod subset."""
    resp = await client.get(f"/api/research/sectors/history?period={period}")
    assert resp.status_code != 422, (
        f"period={period!r} was rejected by /research/sectors/history (SectorPeriod subset)"
    )


# ---------------------------------------------------------------------------
# Negative tests — known-invalid tokens MUST 422. Proves the Literal is
# actually validating, not silently accepting everything.
# ---------------------------------------------------------------------------


async def test_asset_history_rejects_unknown_period(client):
    """A period not in the canonical vocabulary MUST be rejected with 422."""
    resp = await client.get(
        "/api/research/asset/AAPL/history?period=4y&interval=1d",
    )
    assert resp.status_code == 422, (
        f"period=4y should have been rejected by /history but got {resp.status_code}"
    )


async def test_yield_curve_history_rejects_token_outside_subset(client):
    """A period valid in HISTORICAL but outside YieldCurvePeriod MUST be rejected."""
    # 10y is in HISTORICAL_PERIODS but NOT in YIELD_CURVE_PERIODS
    assert "10y" in HISTORICAL_PERIODS
    assert "10y" not in YIELD_CURVE_PERIODS
    resp = await client.get("/api/research/yield-curve/history?period=10y")
    assert resp.status_code == 422, (
        f"period=10y should have been rejected by yield-curve "
        f"(subset enforces narrower vocabulary) but got {resp.status_code}"
    )
