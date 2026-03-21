"""Tests for Screener, Regime, and Correlation API endpoints."""

import sys
import types

import numpy as np
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database


def _generate_history(days: int, start_price: float = 100.0, seed: int = 42) -> list[dict]:
    """Generate synthetic OHLCV history with mild random-walk drift."""
    rng = np.random.default_rng(seed)
    history = []
    price = start_price
    for i in range(days):
        ret = rng.normal(0.0005, 0.015)
        price *= 1 + ret
        high = price * (1 + abs(rng.normal(0, 0.005)))
        low = price * (1 - abs(rng.normal(0, 0.005)))
        history.append({
            "date": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "open": round(price * 0.999, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(price, 2),
            "volume": 50_000_000 + rng.integers(-5_000_000, 5_000_000),
        })
    return history


def _ensure_yfinance_module():
    """Ensure a mock yfinance module exists in sys.modules for patching."""
    if "yfinance" not in sys.modules:
        mod = types.ModuleType("yfinance")
        mod.EquityQuery = MagicMock()
        mod.screen = MagicMock()
        sys.modules["yfinance"] = mod


def _ensure_statsmodels_modules():
    """Ensure mock statsmodels module hierarchy exists in sys.modules for patching."""
    modules = [
        "statsmodels",
        "statsmodels.tsa",
        "statsmodels.tsa.regime_switching",
        "statsmodels.tsa.regime_switching.markov_regression",
    ]
    for name in modules:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
    # Wire up the parent-child attributes
    sys.modules["statsmodels"].tsa = sys.modules["statsmodels.tsa"]
    sys.modules["statsmodels.tsa"].regime_switching = sys.modules["statsmodels.tsa.regime_switching"]
    mreg = sys.modules["statsmodels.tsa.regime_switching.markov_regression"]
    sys.modules["statsmodels.tsa.regime_switching"].markov_regression = mreg
    mreg.MarkovRegression = MagicMock()


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
    yf_mock.get_history.return_value = _generate_history(60)
    yf_mock.get_info.return_value = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "currency": "USD",
        "current_price": 195.50,
    }

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


# ---------------------------------------------------------------------------
# Screener routes
# ---------------------------------------------------------------------------

class TestScreener:
    @pytest.mark.asyncio
    async def test_screener_basic(self, client):
        """Mock yfinance screen() returning 3 stocks, verify response."""
        _ensure_yfinance_module()

        mock_resp = {
            "total": 3,
            "quotes": [
                {
                    "symbol": "AAPL",
                    "shortName": "Apple Inc.",
                    "exchange": "NMS",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "marketCap": 3_000_000_000_000,
                    "regularMarketPrice": 195.50,
                    "trailingPE": 28.5,
                    "dividendYield": 0.005,
                    "averageDailyVolume3Month": 55_000_000,
                    "regularMarketChangePercent": 1.2,
                },
                {
                    "symbol": "MSFT",
                    "shortName": "Microsoft Corp",
                    "exchange": "NMS",
                    "sector": "Technology",
                    "industry": "Software",
                    "marketCap": 2_800_000_000_000,
                    "regularMarketPrice": 420.10,
                    "trailingPE": 35.0,
                    "dividendYield": 0.008,
                    "averageDailyVolume3Month": 22_000_000,
                    "regularMarketChangePercent": -0.3,
                },
                {
                    "symbol": "GOOG",
                    "shortName": "Alphabet Inc.",
                    "exchange": "NMS",
                    "sector": "Technology",
                    "industry": "Internet Content",
                    "marketCap": 2_000_000_000_000,
                    "regularMarketPrice": 170.00,
                    "trailingPE": 25.0,
                    "dividendYield": None,
                    "averageDailyVolume3Month": 30_000_000,
                    "regularMarketChangePercent": 0.8,
                },
            ],
        }

        with patch("yfinance.screen", return_value=mock_resp), \
             patch("yfinance.EquityQuery", MagicMock()):
            resp = await client.get("/api/screener")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["results"]) == 3
        tickers = [r["ticker"] for r in data["results"]]
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "GOOG" in tickers
        assert data["results"][0]["sector"] == "Technology"

    @pytest.mark.asyncio
    async def test_screener_with_filters(self, client):
        """Pass price_min, price_max, sector params and verify they reach screen()."""
        _ensure_yfinance_module()

        mock_resp = {
            "total": 1,
            "quotes": [
                {
                    "symbol": "AAPL",
                    "shortName": "Apple Inc.",
                    "exchange": "NMS",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "marketCap": 3_000_000_000_000,
                    "regularMarketPrice": 195.50,
                },
            ],
        }

        mock_eq = MagicMock()
        with patch("yfinance.screen", return_value=mock_resp) as mock_screen, \
             patch("yfinance.EquityQuery", mock_eq):
            resp = await client.get(
                "/api/screener?price_min=10&price_max=500&sector=Technology"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["ticker"] == "AAPL"
        # EquityQuery should have been called with sector filter among others
        eq_calls = mock_eq.call_args_list
        # Verify sector filter was constructed
        sector_calls = [c for c in eq_calls if len(c[0]) >= 2 and c[0][1] == ["sector", "Technology"]]
        assert len(sector_calls) > 0

    @pytest.mark.asyncio
    async def test_screener_empty_result(self, client):
        """screen() returns empty list."""
        _ensure_yfinance_module()

        mock_resp = {"total": 0, "quotes": []}

        with patch("yfinance.screen", return_value=mock_resp), \
             patch("yfinance.EquityQuery", MagicMock()):
            resp = await client.get("/api/screener")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["results"] == []


# ---------------------------------------------------------------------------
# Regime routes
# ---------------------------------------------------------------------------

class TestRegime:
    @pytest.mark.asyncio
    async def test_regime_basic(self, client):
        """With 200 days of mock history, verify response structure.

        We mock the MarkovRegression model since statsmodels may not be
        installed or may behave unpredictably with synthetic data.
        """
        _ensure_statsmodels_modules()
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        yf_mock.get_history.return_value = _generate_history(200)

        # Build a mock result that mimics MarkovRegression().fit()
        n_obs = 199  # 200 days -> 199 returns
        mock_probs = np.zeros((n_obs, 2))
        # Alternate regimes every ~50 days
        for i in range(n_obs):
            regime = 0 if (i // 50) % 2 == 0 else 1
            mock_probs[i, regime] = 0.95
            mock_probs[i, 1 - regime] = 0.05

        mock_result = MagicMock()
        mock_result.smoothed_marginal_probabilities = mock_probs

        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result

        with patch(
            "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
            return_value=mock_model,
        ):
            resp = await client.get("/api/regime/AAPL")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["source_ticker"] == "AAPL"
        assert data["n_regimes"] == 2
        assert isinstance(data["regimes"], list)
        assert isinstance(data["stats"], list)
        assert len(data["regimes"]) > 0
        # Verify structure of regime points
        r = data["regimes"][0]
        assert "date" in r
        assert "regime" in r
        assert "probability" in r
        # Verify structure of stats
        assert len(data["stats"]) == 2
        s = data["stats"][0]
        assert "regime" in s
        assert "mean_return" in s
        assert "volatility" in s
        assert "count" in s

        # Restore
        yf_mock.get_history.return_value = _generate_history(60)

    @pytest.mark.asyncio
    async def test_regime_insufficient_data(self, client):
        """Short history (< 30 points) returns empty regimes."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        yf_mock.get_history.return_value = _generate_history(10)

        resp = await client.get("/api/regime/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["regimes"] == []
        assert data["stats"] == []

        # Restore
        yf_mock.get_history.return_value = _generate_history(60)

    @pytest.mark.asyncio
    async def test_regime_custom_n_regimes(self, client):
        """Pass n_regimes=3 and verify it is reflected in the response."""
        _ensure_statsmodels_modules()
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]
        yf_mock.get_history.return_value = _generate_history(200)

        # Build mock with 3 regimes
        n_obs = 199
        mock_probs = np.zeros((n_obs, 3))
        for i in range(n_obs):
            regime = i % 3
            mock_probs[i, regime] = 0.90
            for j in range(3):
                if j != regime:
                    mock_probs[i, j] = 0.05

        mock_result = MagicMock()
        mock_result.smoothed_marginal_probabilities = mock_probs

        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result

        with patch(
            "statsmodels.tsa.regime_switching.markov_regression.MarkovRegression",
            return_value=mock_model,
        ):
            resp = await client.get("/api/regime/AAPL?n_regimes=3")

        assert resp.status_code == 200
        data = resp.json()
        assert data["n_regimes"] == 3
        assert isinstance(data["regimes"], list)
        assert isinstance(data["stats"], list)
        assert len(data["stats"]) == 3

        # Restore
        yf_mock.get_history.return_value = _generate_history(60)


# ---------------------------------------------------------------------------
# Correlation routes
# ---------------------------------------------------------------------------

class TestCorrelation:
    @pytest.mark.asyncio
    async def test_correlation_basic(self, client):
        """2 tickers with 30+ overlapping dates, verify matrix shape."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]

        # Return different histories for different tickers but with same dates
        aapl_hist = _generate_history(40, start_price=150.0, seed=42)
        msft_hist = _generate_history(40, start_price=400.0, seed=99)

        async def mock_get_history(ticker, **kwargs):
            if ticker == "AAPL":
                return aapl_hist
            elif ticker == "MSFT":
                return msft_hist
            return _generate_history(40, seed=7)

        yf_mock.get_history.side_effect = mock_get_history

        resp = await client.get("/api/correlation?tickers=AAPL,MSFT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == ["AAPL", "MSFT"]
        assert data["method"] == "pearson"
        matrix = data["matrix"]
        assert len(matrix) == 2
        assert len(matrix[0]) == 2
        # Diagonal should be 1.0 (self-correlation)
        assert matrix[0][0] == pytest.approx(1.0, abs=0.01)
        assert matrix[1][1] == pytest.approx(1.0, abs=0.01)
        # Off-diagonal should be between -1 and 1
        assert -1.0 <= matrix[0][1] <= 1.0
        assert -1.0 <= matrix[1][0] <= 1.0

        # Restore
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _generate_history(60)

    @pytest.mark.asyncio
    async def test_correlation_requires_two_tickers(self, client):
        """Single ticker returns trivial 1x1 matrix."""
        resp = await client.get("/api/correlation?tickers=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == ["AAPL"]
        assert data["matrix"] == [[1.0]]

    @pytest.mark.asyncio
    async def test_correlation_insufficient_data(self, client):
        """Short history returns identity-like matrix (fallback)."""
        from dashboard.deps import _state

        yf_mock = _state["yfinance_provider"]

        # Return very short histories with only 3 data points
        short_hist = _generate_history(3, start_price=100.0, seed=42)

        async def mock_get_history(ticker, **kwargs):
            return short_hist

        yf_mock.get_history.side_effect = mock_get_history

        resp = await client.get("/api/correlation?tickers=AAPL,MSFT")
        assert resp.status_code == 200
        data = resp.json()
        matrix = data["matrix"]
        assert len(matrix) == 2
        # With insufficient data, should return identity-like fallback
        assert matrix[0][0] == pytest.approx(1.0, abs=0.01)
        assert matrix[1][1] == pytest.approx(1.0, abs=0.01)
        assert matrix[0][1] == pytest.approx(0.0, abs=0.01)

        # Restore
        yf_mock.get_history.side_effect = None
        yf_mock.get_history.return_value = _generate_history(60)
