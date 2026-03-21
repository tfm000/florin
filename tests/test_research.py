"""Tests for Research API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database


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

    # Mock yfinance provider
    yf_mock = AsyncMock()
    yf_mock.search.return_value = [
        {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "type": "EQUITY"},
        {"ticker": "AAPD", "name": "Direxion AAPL Bear", "exchange": "NYSE", "type": "ETF"},
    ]
    yf_mock.get_info.return_value = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "market_cap": 3000000000000,
        "pe_ratio": 28.5,
        "forward_pe": 25.0,
        "short_interest": 0.007,
        "exchange": "NASDAQ",
        "shares_outstanding": 15000000000,
        "current_price": 195.50,
        "previous_close": 194.00,
        "fifty_two_week_high": 199.62,
        "fifty_two_week_low": 164.08,
        "dividend_yield": 0.005,
        "beta": 1.24,
        "currency": "USD",
        "quote_type": "EQUITY",
    }
    yf_mock.get_performance_metrics.return_value = {
        "sharpe_ratio": 1.42,
        "max_drawdown_pct": 12.5,
        "return_1m": 3.2,
        "return_6m": 15.8,
        "return_1y": 28.4,
        "return_3y": 45.2,
    }
    yf_mock.get_history.return_value = [
        {"date": "2024-01-01", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.5, "volume": 50000000},
        {"date": "2024-01-02", "open": 191.5, "high": 193.0, "low": 191.0, "close": 192.8, "volume": 48000000},
    ]
    yf_mock.get_news.return_value = [
        {"title": "Apple Q4 Earnings Beat", "publisher": "Reuters", "url": "https://example.com", "published_at": "2024-01-01", "summary": "Strong results"},
    ]
    yf_mock.get_yield_curve.return_value = {
        "region": "US",
        "curve": {"3M": 5.35, "2Y": 4.62, "5Y": 4.15, "10Y": 4.25, "30Y": 4.45},
    }
    yf_mock.get_g10_rates.return_value = [
        {"country": "United States", "central_bank": "Federal Reserve", "rate": 4.50, "currency": "USD"},
        {"country": "Eurozone", "central_bank": "ECB", "rate": 2.65, "currency": "EUR"},
    ]
    yf_mock.get_macro_summary.return_value = {
        "VIX": {"price": 15.2, "change_pct": -2.1},
        "S&P 500": {"price": 5150.0, "change_pct": 0.8},
    }
    yf_mock.get_yield_curve_history.return_value = {
        "dates": ["2024-01-02", "2024-06-01", "2024-12-01"],
        "tenors": {
            "3M": [5.35, 5.25, 4.50],
            "2Y": [4.40, 4.60, 4.20],
            "5Y": [3.90, 4.10, 3.80],
            "10Y": [3.95, 4.30, 4.25],
            "30Y": [4.10, 4.50, 4.45],
        },
    }

    app = create_app(settings, db, event_bus)
    set_state("yfinance_provider", yf_mock)
    yield app
    await db.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, client):
        resp = await client.get("/api/research/search?q=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["ticker"] == "AAPL"
        assert data[0]["name"] == "Apple Inc."

    @pytest.mark.asyncio
    async def test_search_requires_query(self, client):
        resp = await client.get("/api/research/search")
        assert resp.status_code == 422


class TestAssetInfo:
    @pytest.mark.asyncio
    async def test_get_asset_info(self, client):
        resp = await client.get("/api/research/asset/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["market_cap"] == 3000000000000
        assert data["sharpe_ratio"] == 1.42
        assert data["return_1y"] == 28.4


class TestHistory:
    @pytest.mark.asyncio
    async def test_get_history(self, client):
        resp = await client.get("/api/research/asset/AAPL/history?period=1y&interval=1d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["close"] == 191.5

    @pytest.mark.asyncio
    async def test_invalid_period_rejected(self, client):
        resp = await client.get("/api/research/asset/AAPL/history?period=invalid")
        assert resp.status_code == 422


class TestNews:
    @pytest.mark.asyncio
    async def test_get_ticker_news(self, client):
        resp = await client.get("/api/research/news?ticker=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Apple Q4 Earnings Beat"

    @pytest.mark.asyncio
    async def test_get_general_news(self, client):
        resp = await client.get("/api/research/news")
        assert resp.status_code == 200


class TestYieldCurve:
    @pytest.mark.asyncio
    async def test_get_yield_curve(self, client):
        resp = await client.get("/api/research/yield-curve?region=US")
        assert resp.status_code == 200
        data = resp.json()
        assert data["region"] == "US"
        assert "10Y" in data["curve"]
        assert data["curve"]["10Y"] == 4.25

    @pytest.mark.asyncio
    async def test_non_us_region_returns_us_data(self, client):
        """Non-US regions are not supported; endpoint always returns US data."""
        resp = await client.get("/api/research/yield-curve?region=UK")
        assert resp.status_code == 200
        assert resp.json()["region"] == "US"


class TestYieldCurveHistory:
    @pytest.mark.asyncio
    async def test_get_yield_curve_history(self, client):
        resp = await client.get("/api/research/yield-curve/history?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["dates"]) == 3
        assert "10Y" in data["tenors"]
        assert len(data["tenors"]["10Y"]) == 3
        assert data["tenors"]["10Y"][0] == 3.95

    @pytest.mark.asyncio
    async def test_invalid_period_rejected(self, client):
        resp = await client.get("/api/research/yield-curve/history?period=invalid")
        assert resp.status_code == 422


class TestPolicyRates:
    @pytest.mark.asyncio
    async def test_get_policy_rates(self, client):
        resp = await client.get("/api/research/policy-rates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["country"] == "United States"
        assert data[0]["rate"] == 4.50


class TestMacro:
    @pytest.mark.asyncio
    async def test_get_macro_summary(self, client):
        resp = await client.get("/api/research/macro")
        assert resp.status_code == 200
        data = resp.json()
        assert "VIX" in data["indicators"]
        assert data["indicators"]["VIX"]["price"] == 15.2


class TestHolders:
    @pytest.mark.asyncio
    async def test_get_holders(self, client, app):
        # Configure mock holders response
        yf_mock = app.state.__dict__.get("yfinance_provider", None)
        # Access the mock through deps
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        yf_mock.get_holders.return_value = {
            "breakdown": {
                "insiders_pct": 0.07,
                "institutions_pct": 0.61,
                "institutions_float_pct": 0.65,
                "institutions_count": 5200,
            },
            "institutional": [
                {
                    "holder": "Vanguard Group",
                    "shares": 1300000000,
                    "value": 254150000000,
                    "pct_held": 0.087,
                    "pct_change": 0.01,
                    "date_reported": "2024-09-30",
                },
            ],
            "mutual_fund": [
                {
                    "holder": "Vanguard Total Stock Mkt Idx",
                    "shares": 400000000,
                    "value": 78200000000,
                    "pct_held": 0.027,
                    "pct_change": -0.005,
                    "date_reported": "2024-09-30",
                },
            ],
        }

        resp = await client.get("/api/research/holders/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert len(data["institutional"]) == 1
        assert data["institutional"][0]["holder"] == "Vanguard Group"
        assert len(data["mutual_fund"]) == 1
        assert data["mutual_fund"][0]["holder"] == "Vanguard Total Stock Mkt Idx"


class TestAnalyse:
    @pytest.mark.asyncio
    async def test_analyse_returns_error_without_llm(self, client):
        """POST analyse should return 503 when no LLM analysers are configured."""
        set_state("analysers", {})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse")
        # Without any analysers, the endpoint raises ServiceUnavailableError (503)
        assert resp.status_code == 503
        data = resp.json()
        assert "detail" in data or "error" in data


class TestIVSpread:
    @pytest.mark.asyncio
    async def test_get_iv_spread(self, client):
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        yf_mock.get_put_call_iv_spread.return_value = {
            "ticker": "SPY",
            "spot": 515.0,
            "skew_expiry": "2024-03-15",
            "available_expiries": ["2024-03-15", "2024-04-19", "2024-06-21"],
            "skew": [
                {
                    "strike": 510.0,
                    "moneyness": -0.97,
                    "call_iv": 0.15,
                    "put_iv": 0.18,
                    "vol": 0.165,
                    "spread": 0.03,
                },
                {
                    "strike": 515.0,
                    "moneyness": 0.0,
                    "call_iv": 0.13,
                    "put_iv": 0.14,
                    "vol": 0.135,
                    "spread": 0.01,
                },
            ],
            "term_structure": [
                {"expiry": "2024-03-15", "call_iv": 0.13, "put_iv": 0.15, "spread": 0.02},
                {"expiry": "2024-04-19", "call_iv": 0.14, "put_iv": 0.16, "spread": 0.02},
            ],
        }

        resp = await client.get("/api/research/iv-spread?ticker=SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "SPY"
        assert data["spot"] == 515.0
        assert len(data["skew"]) == 2
        assert data["skew"][0]["strike"] == 510.0
        assert data["skew"][0]["spread"] == 0.03
        assert len(data["term_structure"]) == 2
        assert data["term_structure"][0]["expiry"] == "2024-03-15"
        assert len(data["available_expiries"]) == 3
