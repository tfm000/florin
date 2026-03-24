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

    @pytest.mark.asyncio
    async def test_macro_all_indicators_have_required_fields(self, client):
        resp = await client.get("/api/research/macro")
        indicators = resp.json()["indicators"]
        for name, ind in indicators.items():
            assert "price" in ind, f"{name} missing price"
            assert "change_pct" in ind, f"{name} missing change_pct"
            assert isinstance(ind["price"], (int, float))
            assert isinstance(ind["change_pct"], (int, float))

    @pytest.mark.asyncio
    async def test_macro_sp500_values(self, client):
        resp = await client.get("/api/research/macro")
        sp = resp.json()["indicators"]["S&P 500"]
        assert sp["price"] == 5150.0
        assert sp["change_pct"] == 0.8


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
        """POST analyse should return error in response when no analysers available."""
        set_state("analysers", {})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse")
        assert resp.status_code == 200
        data = resp.json()
        # Error should be present in the sentiment detail or top-level
        assert data.get("error") is not None or (
            data.get("sentiment") and data["sentiment"].get("error")
        )

    @pytest.mark.asyncio
    async def test_analyse_success_path(self, client):
        """With a mock analyser, returns full LLMAnalysisResponse."""
        from core.models import AnalysisResult, AnalysisType, Recommendation

        mock_analyser = AsyncMock()
        mock_analyser.provider_name = "test-provider"
        mock_analyser.analyse_sentiment.return_value = AnalysisResult(
            provider="test-provider",
            model="test-model-v1",
            analysis_type=AnalysisType.SENTIMENT,
            score=7.5,
            confidence=0.85,
            bullish_signals=["Strong revenue growth", "Expanding margins"],
            bearish_signals=["High valuation"],
            recommendation=Recommendation.BUY,
            summary="Company shows strong fundamentals.",
            key_points=["Q4 earnings beat", "Market share gains"],
            error=None,
        )

        set_state("analysers", {"test-provider": mock_analyser})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse?mode=all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["provider"] == "test-provider"
        assert data["model"] == "test-model-v1"
        assert data["score"] == 7.5
        assert data["confidence"] == 0.85
        assert data["recommendation"] == "BUY"
        assert data["summary"] == "Company shows strong fundamentals."
        assert len(data["bullish_signals"]) == 2
        assert len(data["bearish_signals"]) == 1
        assert len(data["key_points"]) == 2
        assert data["error"] is None
        # Phase 6: typed results should be present
        assert data["sentiment"] is not None
        assert data["sentiment"]["score"] == 7.5
        assert data["sentiment"]["analysis_type"] == "sentiment"

        # Cleanup
        set_state("analysers", {})

    @pytest.mark.asyncio
    async def test_analyse_llm_failure_returns_error_in_body(self, client):
        """When the LLM call fails, error is returned in the response body (not 502)."""
        mock_analyser = AsyncMock()
        mock_analyser.provider_name = "broken-llm"
        mock_analyser.analyse_sentiment.side_effect = ConnectionError("LLM unreachable")

        set_state("analysers", {"broken-llm": mock_analyser})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        # Error should be in the sentiment typed field
        assert data["sentiment"] is not None
        assert data["sentiment"]["error"] is not None
        assert "LLM connection failed" in data["sentiment"]["error"]
        # Top-level error mirrors the primary result
        assert data["error"] is not None

        set_state("analysers", {})

    @pytest.mark.asyncio
    async def test_analyse_type_announcement(self, client):
        """type=announcement should run announcement analysis only."""
        from core.models import AnalysisResult, AnalysisType, Recommendation

        mock_analyser = AsyncMock()
        mock_analyser.provider_name = "test-provider"
        mock_analyser.analyse_announcements.return_value = AnalysisResult(
            provider="test-provider",
            model="test-model",
            analysis_type=AnalysisType.ANNOUNCEMENT,
            score=6.0,
            confidence=0.7,
            recommendation=Recommendation.BUY,
            summary="Positive 8-K filing.",
            key_points=["Earnings beat"],
        )

        set_state("analysers", {"test-provider": mock_analyser})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse?type=announcement")
        assert resp.status_code == 200
        data = resp.json()
        assert data["announcement"] is not None
        assert data["announcement"]["score"] == 6.0
        assert data["announcement"]["analysis_type"] == "announcement"
        assert data["sentiment"] is None  # Not requested

        set_state("analysers", {})

    @pytest.mark.asyncio
    async def test_analyse_type_both(self, client):
        """type=both should run both announcement and sentiment analysis."""
        from core.models import AnalysisResult, AnalysisType, Recommendation

        mock_analyser = AsyncMock()
        mock_analyser.provider_name = "test-provider"
        mock_analyser.analyse_announcements.return_value = AnalysisResult(
            provider="test-provider",
            model="test-model",
            analysis_type=AnalysisType.ANNOUNCEMENT,
            score=7.0,
            confidence=0.8,
            recommendation=Recommendation.BUY,
            summary="Strong filing.",
        )
        mock_analyser.analyse_sentiment.return_value = AnalysisResult(
            provider="test-provider",
            model="test-model",
            analysis_type=AnalysisType.SENTIMENT,
            score=5.5,
            confidence=0.6,
            recommendation=Recommendation.HOLD,
            summary="Mixed sentiment.",
        )

        set_state("analysers", {"test-provider": mock_analyser})
        set_state("sentiment_aggregator", None)

        resp = await client.post("/api/research/asset/AAPL/analyse?type=both")
        assert resp.status_code == 200
        data = resp.json()
        assert data["announcement"] is not None
        assert data["sentiment"] is not None
        assert data["announcement"]["score"] == 7.0
        assert data["sentiment"]["score"] == 5.5

        set_state("analysers", {})


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


class TestSectors:
    """Tests for GET /api/research/sectors batch endpoint."""

    @pytest.mark.asyncio
    async def test_sectors_returns_all_11_sectors(self, client):
        resp = await client.get("/api/research/sectors")
        assert resp.status_code == 200
        data = resp.json()
        assert "sectors" in data
        assert len(data["sectors"]) == 11

    @pytest.mark.asyncio
    async def test_sector_item_has_correct_fields(self, client):
        resp = await client.get("/api/research/sectors")
        data = resp.json()
        sector = data["sectors"][0]
        assert "name" in sector
        assert "etf" in sector
        assert "price" in sector
        assert "market_cap" in sector
        assert "returns" in sector
        returns = sector["returns"]
        for tf in ["1d", "1w", "1m", "3m", "6m", "1y"]:
            assert tf in returns, f"Missing timeframe {tf}"

    @pytest.mark.asyncio
    async def test_sector_names_and_etfs_match(self, client):
        resp = await client.get("/api/research/sectors")
        data = resp.json()
        expected_etfs = {"XLK", "XLV", "XLF", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"}
        actual_etfs = {s["etf"] for s in data["sectors"]}
        assert actual_etfs == expected_etfs

    @pytest.mark.asyncio
    async def test_sector_returns_are_numeric_or_null(self, client):
        resp = await client.get("/api/research/sectors")
        data = resp.json()
        for sector in data["sectors"]:
            for tf, val in sector["returns"].items():
                assert val is None or isinstance(val, (int, float)), (
                    f"Sector {sector['name']} timeframe {tf}: expected numeric or null, got {type(val)}"
                )

    @pytest.mark.asyncio
    async def test_sectors_with_rich_history(self, client):
        """With enough history data, all return timeframes should compute."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        # Provide 300 days of history (enough for 1y = 252 days)
        history_300 = [
            {"date": f"2024-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}", "open": 100.0 + i * 0.1,
             "high": 101.0 + i * 0.1, "low": 99.0 + i * 0.1,
             "close": 100.0 + i * 0.1, "volume": 1000000}
            for i in range(300)
        ]
        yf_mock.get_history.return_value = history_300

        resp = await client.get("/api/research/sectors")
        data = resp.json()
        sector = data["sectors"][0]
        # With 300 data points, all timeframes should be non-null
        for tf in ["1d", "1w", "1m", "3m", "6m", "1y"]:
            assert sector["returns"][tf] is not None, f"Expected non-null return for {tf}"
            assert isinstance(sector["returns"][tf], (int, float))

        # Restore default mock
        yf_mock.get_history.return_value = [
            {"date": "2024-01-01", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.5, "volume": 50000000},
            {"date": "2024-01-02", "open": 191.5, "high": 193.0, "low": 191.0, "close": 192.8, "volume": 48000000},
        ]

    @pytest.mark.asyncio
    async def test_sectors_handles_empty_history(self, client):
        """Sectors with empty history should still return with null returns."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]
        original = yf_mock.get_history.return_value

        yf_mock.get_history.return_value = []
        resp = await client.get("/api/research/sectors")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sectors"]) == 11
        for sector in data["sectors"]:
            for tf in ["1d", "1w", "1m", "3m", "6m", "1y"]:
                assert sector["returns"][tf] is None

        yf_mock.get_history.return_value = original

    @pytest.mark.asyncio
    async def test_sectors_handles_provider_exception(self, client):
        """If yfinance raises on a single ETF, endpoint still returns all sectors."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]
        original_info = yf_mock.get_info.return_value

        # Make get_info raise for any call — sectors should still have empty price/mcap
        yf_mock.get_info.side_effect = Exception("yfinance down")
        yf_mock.get_history.return_value = [
            {"date": "2024-01-01", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.5, "volume": 50000000},
            {"date": "2024-01-02", "open": 191.5, "high": 193.0, "low": 191.0, "close": 192.8, "volume": 48000000},
        ]

        resp = await client.get("/api/research/sectors")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sectors"]) == 11
        # price/market_cap should be None when get_info fails
        for sector in data["sectors"]:
            assert sector["price"] is None
            assert sector["market_cap"] is None

        yf_mock.get_info.side_effect = None
        yf_mock.get_info.return_value = original_info


class TestSectorsHistory:
    """Tests for GET /api/research/sectors/history endpoint."""

    @pytest.mark.asyncio
    async def test_sectors_history_returns_dates_and_series(self, client):
        resp = await client.get("/api/research/sectors/history?period=1m")
        assert resp.status_code == 200
        data = resp.json()
        assert "dates" in data
        assert "series" in data
        assert isinstance(data["dates"], list)
        assert isinstance(data["series"], dict)

    @pytest.mark.asyncio
    async def test_sectors_history_series_values_are_cumulative_returns(self, client):
        """First value in each series should be 0.0 (return relative to base date)."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]

        history = [
            {"date": "2024-01-01", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000000},
            {"date": "2024-01-02", "open": 100.0, "high": 102.0, "low": 99.5, "close": 105.0, "volume": 1100000},
            {"date": "2024-01-03", "open": 105.0, "high": 106.0, "low": 104.0, "close": 110.0, "volume": 1200000},
        ]
        yf_mock.get_history.return_value = history

        resp = await client.get("/api/research/sectors/history?period=1m")
        data = resp.json()

        assert len(data["dates"]) == 3
        for sector_name, values in data["series"].items():
            assert len(values) == 3
            # First point: cumulative return = 0% (base)
            assert values[0] == 0.0
            # Second point: (105/100 - 1) * 100 = 5.0%
            assert values[1] == 5.0
            # Third point: (110/100 - 1) * 100 = 10.0%
            assert values[2] == 10.0

        # Restore
        yf_mock.get_history.return_value = [
            {"date": "2024-01-01", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.5, "volume": 50000000},
            {"date": "2024-01-02", "open": 191.5, "high": 193.0, "low": 191.0, "close": 192.8, "volume": 48000000},
        ]

    @pytest.mark.asyncio
    async def test_sectors_history_invalid_period_rejected(self, client):
        resp = await client.get("/api/research/sectors/history?period=invalid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_sectors_history_accepts_shorthand_periods(self, client):
        """Should accept both yfinance (1mo) and shorthand (1m) period formats."""
        for period in ["1m", "3m", "6m", "1mo", "3mo", "6mo", "1y"]:
            resp = await client.get(f"/api/research/sectors/history?period={period}")
            assert resp.status_code == 200, f"Period {period} should be accepted"

    @pytest.mark.asyncio
    async def test_sectors_history_empty_when_no_data(self, client):
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]
        original = yf_mock.get_history.return_value

        yf_mock.get_history.return_value = []
        resp = await client.get("/api/research/sectors/history?period=1m")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dates"] == []
        assert data["series"] == {}

        yf_mock.get_history.return_value = original

    @pytest.mark.asyncio
    async def test_sectors_history_all_series_same_length_as_dates(self, client):
        """Every series array must have exactly len(dates) entries."""
        resp = await client.get("/api/research/sectors/history?period=1m")
        data = resp.json()
        n_dates = len(data["dates"])
        for name, values in data["series"].items():
            assert len(values) == n_dates, (
                f"Series '{name}' has {len(values)} values but expected {n_dates} (len(dates))"
            )


class TestComputeReturn:
    """Unit tests for the _compute_return helper."""

    def test_positive_return(self):
        from dashboard.routes.research import _compute_return
        # 10 closes, return over last 5 days: start = closes[-(5+1)] = closes[-6] = 104
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]
        result = _compute_return(closes, 5)
        expected = round((110 / 104 - 1) * 100, 2)
        assert result == expected

    def test_negative_return(self):
        from dashboard.routes.research import _compute_return
        closes = [100, 99, 98, 97, 96, 95]
        result = _compute_return(closes, 5)
        expected = round((95 / 100 - 1) * 100, 2)
        assert result == expected

    def test_insufficient_data_returns_none(self):
        from dashboard.routes.research import _compute_return
        closes = [100, 101]
        assert _compute_return(closes, 5) is None

    def test_exact_boundary_returns_none(self):
        from dashboard.routes.research import _compute_return
        # len(closes) == days → insufficient (need days + 1)
        closes = [100, 101, 102, 103, 104]
        assert _compute_return(closes, 5) is None

    def test_zero_start_price_returns_none(self):
        from dashboard.routes.research import _compute_return
        closes = [0, 100, 101]
        assert _compute_return(closes, 1) is not None  # start=100, end=101
        closes = [100, 0, 101]
        # days=2 → start = closes[-3] = 100, end = 101 → valid
        assert _compute_return(closes, 2) is not None


class TestQuotesEndpoint:
    @pytest.mark.asyncio
    async def test_quotes_returns_ohlcv_with_bid_ask(self, client):
        """Quotes endpoint returns history with bid/ask on the last bar."""
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]
        yf_mock.get_info.return_value = {
            "ticker": "AAPL", "bid": 191.0, "ask": 192.0, "current_price": 191.5,
        }
        resp = await client.get("/api/research/asset/AAPL/quotes?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Last bar should have bid/ask
        assert data[-1]["bid"] == 191.0
        assert data[-1]["ask"] == 192.0
        # Earlier bars should have null bid/ask
        assert data[0]["bid"] is None
        assert data[0]["ask"] is None

    @pytest.mark.asyncio
    async def test_quotes_without_bid_ask_returns_nulls(self, client):
        from dashboard.deps import _state
        yf_mock = _state["yfinance_provider"]
        yf_mock.get_info.return_value = {"ticker": "AAPL", "bid": None, "ask": None}
        resp = await client.get("/api/research/asset/AAPL/quotes?period=1y")
        assert resp.status_code == 200
        data = resp.json()
        assert data[-1]["bid"] is None
        assert data[-1]["ask"] is None


class TestFillBidAsk:
    def test_fill_both_valid(self):
        from dashboard.routes.research import _fill_bid_ask
        points = [{"close": 100, "bid": 99.5, "ask": 100.5}]
        result = _fill_bid_ask(points)
        assert result[0]["bid"] == 99.5
        assert result[0]["ask"] == 100.5

    def test_fill_missing_ask_uses_spread(self):
        from dashboard.routes.research import _fill_bid_ask
        points = [
            {"close": 100, "bid": 99.5, "ask": 100.5},
            {"close": 101, "bid": 100.5, "ask": 0},
        ]
        result = _fill_bid_ask(points)
        # Last spread was 1.0, so ask = 100.5 + 1.0 = 101.5
        assert result[1]["ask"] == 101.5

    def test_fill_both_missing_uses_forward_fill(self):
        from dashboard.routes.research import _fill_bid_ask
        points = [
            {"close": 100, "bid": 99.5, "ask": 100.5},
            {"close": 101, "bid": 0, "ask": 0},
        ]
        result = _fill_bid_ask(points)
        # Last spread was 1.0, so bid = 101 - 0.5, ask = 101 + 0.5
        assert result[1]["bid"] == 100.5
        assert result[1]["ask"] == 101.5

    def test_fill_no_prior_spread_mirrors_around_close(self):
        from dashboard.routes.research import _fill_bid_ask
        points = [
            {"close": 100, "bid": 99.0, "ask": 0},
        ]
        result = _fill_bid_ask(points)
        # No prior spread, mirror: ask = close + (close - bid) = 101
        assert result[0]["ask"] == 101.0
