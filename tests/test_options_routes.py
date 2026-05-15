"""Route-level integration tests for /api/options/*."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import Settings
from core.events import EventBus
from dashboard.app import create_app
from dashboard.deps import set_state
from db.database import Database
from stats.options.types import (
    ArbDiagnostics,
    GPBand,
    IVFit,
    ParityFit,
    RNDBand,
    SABRParams,
    SSVIParams,
    SurfaceFit,
    VolModel,
)


def _make_dummy_fit(model: VolModel, *, is_stale: bool = False) -> SurfaceFit:
    """Construct a SurfaceFit-shaped object for adapter tests."""
    n_grid = 30
    K_grid = np.linspace(80.0, 120.0, n_grid)
    iv_grid = np.full(n_grid, 0.22)
    F = 100.0
    D = math.exp(-0.04 * 0.5)
    band = GPBand(
        K_grid=K_grid,
        iv_mean=iv_grid,
        iv_std=np.full(n_grid, 0.005),
        iv_samples=np.tile(iv_grid, (10, 1)),
        kernel_repr="dummy",
    )
    rnd_band = RNDBand(
        K_grid=K_grid,
        density_median=np.full(n_grid, 0.01),
        density_lo68=np.full(n_grid, 0.009),
        density_hi68=np.full(n_grid, 0.011),
        density_lo90=np.full(n_grid, 0.008),
        density_hi90=np.full(n_grid, 0.012),
        n_samples=10,
        method="gatheral" if model == VolModel.SSVI else "shimko",
        diagnostics={"n_neg_clipped": 0, "median_integral": 1.0, "mean_recovery_pct": 0.0},
    )
    iv_fit = IVFit(
        model=model,
        K_grid=K_grid,
        iv_grid=iv_grid,
        F=F,
        D=D,
        T=0.5,
        rmse_iv=2e-4,
        n_obs=18,
    )
    if model == VolModel.SSVI:
        iv_fit.ssvi = SSVIParams(
            theta_T=0.04,
            rho=-0.4,
            eta=0.5,
            gamma=0.3,
            rmse_iv=2e-4,
            n_obs=18,
            butterfly_margin=1.5,
            param_cov=np.eye(3) * 1e-6,
        )
    else:
        iv_fit.sabr = SABRParams(
            alpha=0.22,
            beta=1.0,
            rho=-0.4,
            nu=0.6,
            rmse_iv=2e-4,
            n_obs=18,
            param_cov=np.eye(4) * 1e-6,
        )

    parity = ParityFit(
        D=D,
        F=F,
        r=0.04,
        r2=0.9999,
        residual_std=0.001,
        n_strikes=18,
        n_iterations=2,
    )
    arb = ArbDiagnostics(
        durrleman_min=0.5,
        lee_left=0.2,
        lee_right=0.3,
        n_neg_clipped=0,
        integral_q=1.0,
        mean_recovery_pct=0.01,
    )
    market_quotes = pd.DataFrame(
        {
            "strike": K_grid[::5],
            "iv": iv_grid[::5],
        }
    )

    return SurfaceFit(
        ticker="TST",
        spot=100.0,
        expiry="2026-06-20",
        T=0.5,
        F=F,
        D=D,
        r=0.045,  # external SOFR
        r_implied_raw=0.038,  # chain-implied diagnostic (drifts from truth)
        model=model,
        parity=parity,
        iv_fit=iv_fit,
        gp_band=band,
        rnd_band=rnd_band,
        arbitrage=arb,
        market_quotes=market_quotes,
        available_expiries=["2026-06-20", "2026-09-19"],
        is_stale=is_stale,
        stale_fraction=0.92 if is_stale else 0.0,
    )


@pytest.fixture
async def app_with_mock_service():
    """Build an app with a mocked OptionSurfaceService injected."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()

    app = create_app(settings, db, event_bus)

    svc = AsyncMock()

    async def _get_single(ticker, expiry=None, model=VolModel.SSVI, **kw):
        if not ticker or ticker == "BAD":
            raise ValueError("no chain")
        return _make_dummy_fit(model, is_stale=(ticker == "STALE"))

    svc.get_single_expiry_fit.side_effect = _get_single
    svc.get_multi_expiry_fit.return_value = {
        "ticker": "TST",
        "spot": 100.0,
        "expiries": ["2026-06-20", "2026-09-19"],
        "T_values": [0.5, 0.75],
        "moneyness_grid": [0.6, 0.8, 1.0, 1.2, 1.4],
        "iv_surface": [[0.25, 0.22, 0.20, 0.22, 0.25], [0.27, 0.24, 0.21, 0.23, 0.26]],
        "iv_lo68": [[0.24, 0.21, 0.19, 0.21, 0.24], [0.26, 0.23, 0.20, 0.22, 0.25]],
        "iv_hi68": [[0.26, 0.23, 0.21, 0.23, 0.26], [0.28, 0.25, 0.22, 0.24, 0.27]],
        "rnd_surface": [[0.005, 0.01, 0.02, 0.01, 0.005]] * 2,
        "rnd_lo68": [[0.004, 0.009, 0.018, 0.009, 0.004]] * 2,
        "rnd_hi68": [[0.006, 0.011, 0.022, 0.011, 0.006]] * 2,
        "F": [100.0, 100.5],
        "r": [0.04, 0.042],
        "calendar": {"n_violations": 0, "worst_violation": 0.0},
    }
    svc.get_spread_curve.return_value = {
        "ticker": "TST",
        "spread_curve": [
            {
                "expiry": "2026-06-20",
                "T": 0.5,
                "call_iv": 0.22,
                "put_iv": 0.24,
                "spread": 0.02,
            }
        ],
    }
    set_state("option_surface_service", svc)
    yield app
    await db.close()


@pytest.fixture
async def client(app_with_mock_service):
    transport = ASGITransport(app=app_with_mock_service)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_surface_endpoint_ssvi(client) -> None:
    res = await client.get("/api/options/surface?ticker=TST&model=ssvi")
    assert res.status_code == 200
    body = res.json()
    assert body["ticker"] == "TST"
    assert body["model"] == "ssvi"
    assert body["ssvi"] is not None
    assert body["sabr"] is None
    # ``r`` is always the external SOFR; chain-implied value is the diagnostic.
    assert body["r"] == pytest.approx(0.045)
    assert body["parity"]["r_implied_raw"] == pytest.approx(0.038)
    # Removed in this PR — old schema had ``rate_quality`` here.
    assert "rate_quality" not in body["parity"]
    assert len(body["iv_curve"]) == 30
    assert len(body["rnd"]) == 30
    assert body["arbitrage"]["n_neg_clipped"] == 0


async def test_surface_endpoint_sabr(client) -> None:
    res = await client.get("/api/options/surface?ticker=TST&model=sabr")
    assert res.status_code == 200
    body = res.json()
    assert body["model"] == "sabr"
    assert body["sabr"] is not None
    assert body["ssvi"] is None
    assert math.isclose(body["sabr"]["beta"], 1.0)


async def test_surface_endpoint_empty_chain(client) -> None:
    res = await client.get("/api/options/surface?ticker=BAD")
    assert res.status_code == 404


async def test_surface_response_carries_stale_flag(client) -> None:
    """When the underlying SurfaceFit is marked stale, the API response
    surfaces ``is_stale=True`` and a positive ``stale_fraction`` so the
    UI can render the off-hours banner. Live fits return ``is_stale=False``."""
    live = await client.get("/api/options/surface?ticker=TST")
    assert live.status_code == 200
    live_body = live.json()
    assert live_body["is_stale"] is False
    assert live_body["stale_fraction"] == 0.0

    stale = await client.get("/api/options/surface?ticker=STALE")
    assert stale.status_code == 200
    stale_body = stale.json()
    assert stale_body["is_stale"] is True
    assert stale_body["stale_fraction"] > 0.5


async def test_multi_endpoint(client) -> None:
    res = await client.get("/api/options/surface/multi?ticker=TST&n_expiries=2")
    assert res.status_code == 200
    body = res.json()
    assert len(body["expiries"]) == 2
    assert len(body["iv_surface"]) == 2
    assert len(body["iv_surface"][0]) == 5
    assert len(body["F"]) == 2


async def test_rate_curve_endpoint_removed(client) -> None:
    """The /options/rate-curve route was removed when we switched to
    SOFR for all options pricing. Verify it's gone from the OpenAPI
    schema — a raw HTTP probe would hit the SPA catch-all and yield a
    200 with the index.html, which is the correct production
    behaviour but isn't a useful assertion here."""
    schema = (await client.get("/openapi.json")).json()
    paths = schema.get("paths", {})
    assert "/api/options/rate-curve" not in paths
    # The remaining options routes are still present.
    assert "/api/options/surface" in paths
    assert "/api/options/surface/multi" in paths
    assert "/api/options/spread-curve" in paths


async def test_spread_curve_endpoint(client) -> None:
    res = await client.get("/api/options/spread-curve?ticker=TST")
    assert res.status_code == 200
    body = res.json()
    assert len(body["spread_curve"]) == 1
    sp = body["spread_curve"][0]
    assert math.isclose(sp["spread"], sp["put_iv"] - sp["call_iv"], abs_tol=1e-12)


async def test_service_missing_503() -> None:
    """No service registered → 503 with a clear error."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        t212_api_key="",
        t212_api_secret="",
    )
    db = Database(settings.database_url)
    await db.init()
    await db.create_tables()
    event_bus = EventBus()
    app = create_app(settings, db, event_bus)
    set_state("option_surface_service", None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/options/surface?ticker=TST")
    assert res.status_code == 503
    await db.close()
