"""
Options / RND surface routes.

Endpoints (all prefixed with ``/api`` at app registration time):

    GET  /options/surface            single-expiry SSVI|SABR + GP + RND fit
    GET  /options/surface/multi      assembled multi-expiry IV + RND surface
    GET  /options/spread-curve       per-expiry ATM put-call IV spread

The previous ``/options/rate-curve`` endpoint has been removed — the
chain-implied rate was too noisy to render usefully (sub-cent bid-ask
noise amplified by short ``T`` produced double-digit rate errors on
zero-DTE expiries). The pipeline now prices every fit against the
external SOFR rate; the chain-implied value remains on
``SurfaceFitResponse.parity.r_implied_raw`` as a diagnostic.

The service layer (``dashboard/services/option_surface.py``) does the
heavy lifting; this module is a thin Pydantic / FastAPI translation
layer.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from stats.options.types import VolModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["options"])


# ----------------------------------------------------------------------
# Pydantic schemas
# ----------------------------------------------------------------------


class IVPoint(BaseModel):
    strike: float
    moneyness: float  # log(K / F)
    iv_market: float | None = None  # observed (None on grid points without a quote)
    iv_parametric: float  # SSVI or SABR raw fit
    iv_hybrid: float  # parametric + GP mean
    iv_lo68: float | None = None
    iv_hi68: float | None = None
    iv_lo90: float | None = None
    iv_hi90: float | None = None


class RNDPoint(BaseModel):
    strike: float
    density_median: float
    density_lo68: float
    density_hi68: float
    density_lo90: float
    density_hi90: float


class ParityDiagnostics(BaseModel):
    """Parity-regression diagnostics for one expiry.

    ``r`` on the parent ``SurfaceFitResponse`` is always the external
    SOFR rate — the chain-implied value preserved here as
    ``r_implied_raw`` is informational only (handy for quants curious
    how far the chain drifts from the true rate, but never used for
    pricing).
    """

    r2: float
    residual_std: float
    n_strikes: int
    n_iterations: int
    # Raw parity-regression annualised rate (the unconstrained
    # two-parameter slope/intercept fit). Often unreliable on
    # short-DTE / illiquid chains — reported purely as a diagnostic.
    r_implied_raw: float = 0.0


class SSVIParamsModel(BaseModel):
    theta_T: float
    rho: float
    eta: float
    gamma: float
    rmse_iv: float
    n_obs: int
    butterfly_margin: float
    param_cov: list[list[float]]


class SABRParamsModel(BaseModel):
    alpha: float
    beta: float
    rho: float
    nu: float
    rmse_iv: float
    n_obs: int
    param_cov: list[list[float]]


class ArbDiagnosticsModel(BaseModel):
    durrleman_min: float
    lee_left: float
    lee_right: float
    n_neg_clipped: int
    integral_q: float
    mean_recovery_pct: float


class SurfaceFitResponse(BaseModel):
    ticker: str
    spot: float
    expiry: str
    T: float
    F: float
    D: float
    r: float
    model: Literal["ssvi", "sabr"]
    parity: ParityDiagnostics
    ssvi: SSVIParamsModel | None = None
    sabr: SABRParamsModel | None = None
    iv_curve: list[IVPoint]
    rnd: list[RNDPoint]
    arbitrage: ArbDiagnosticsModel
    available_expiries: list[str] = Field(default_factory=list)
    # Off-hours staleness: ``stale_fraction`` is the share of underlying
    # quotes that fell back to lastPrice (no live two-sided bid/ask).
    # ``is_stale`` is True when ≥ 50 %; the UI surfaces an amber banner
    # explaining the degraded mode.
    is_stale: bool = False
    stale_fraction: float = 0.0


class CalendarDiagnostics(BaseModel):
    """Calendar-arbitrage diagnostic across an assembled multi-expiry
    surface. ``n_violations`` is the count of (k, T) cells where the
    Gatheral 2014 calendar condition ``∂_T w(k, T) ≥ 0`` fails between
    adjacent expiries; ``worst_violation`` is the largest absolute
    total-variance drop in pp² across those cells. Zero on both is the
    clean signal."""

    n_violations: int
    worst_violation: float


class MultiSurfaceFitResponse(BaseModel):
    ticker: str
    spot: float
    expiries: list[str]
    T_values: list[float]
    moneyness_grid: list[float]
    iv_surface: list[list[float]]
    iv_lo68: list[list[float]]
    iv_hi68: list[list[float]]
    rnd_surface: list[list[float]]
    rnd_lo68: list[list[float]]
    rnd_hi68: list[list[float]]
    F: list[float]
    r: list[float]
    calendar: CalendarDiagnostics


class SpreadPoint(BaseModel):
    expiry: str
    T: float
    put_iv: float
    call_iv: float
    spread: float


class SpreadCurveResponse(BaseModel):
    ticker: str
    spread_curve: list[SpreadPoint]


# ----------------------------------------------------------------------
# Adapters: SurfaceFit -> SurfaceFitResponse
# ----------------------------------------------------------------------


def _surface_fit_to_response(fit) -> SurfaceFitResponse:
    import numpy as np

    K_grid = fit.gp_band.K_grid
    F = fit.F
    moneyness = np.log(K_grid / F)
    parametric_iv = fit.iv_fit.iv_grid
    iv_mean = fit.gp_band.iv_mean
    iv_std = fit.gp_band.iv_std

    # 68 % and 90 % bands around the hybrid mean (Gaussian z = 1.0, 1.645).
    iv_lo68 = iv_mean - iv_std
    iv_hi68 = iv_mean + iv_std
    iv_lo90 = iv_mean - 1.645 * iv_std
    iv_hi90 = iv_mean + 1.645 * iv_std

    # Market IVs from observed quotes — set to None on grid points without
    # a market observation. For payload simplicity we leave iv_market = None
    # everywhere on the dense grid; the UI overlays the market scatter
    # from a separate market_quotes payload (future extension), but for
    # this PR we attach the market IV to the *nearest* grid point only
    # so the client can render the scatter without a second endpoint.
    iv_market_grid: list[float | None] = [None] * len(K_grid)
    if "iv" in fit.market_quotes.columns:
        for _, row in fit.market_quotes.iterrows():
            idx = int(np.argmin(np.abs(K_grid - float(row["strike"]))))
            iv_market_grid[idx] = float(row["iv"])

    iv_curve = [
        IVPoint(
            strike=float(K_grid[i]),
            moneyness=float(moneyness[i]),
            iv_market=iv_market_grid[i],
            iv_parametric=float(parametric_iv[i]),
            iv_hybrid=float(iv_mean[i]),
            iv_lo68=float(iv_lo68[i]),
            iv_hi68=float(iv_hi68[i]),
            iv_lo90=float(iv_lo90[i]),
            iv_hi90=float(iv_hi90[i]),
        )
        for i in range(len(K_grid))
    ]

    K_rnd = fit.rnd_band.K_grid
    rnd_points = [
        RNDPoint(
            strike=float(K_rnd[i]),
            density_median=float(fit.rnd_band.density_median[i]),
            density_lo68=float(fit.rnd_band.density_lo68[i]),
            density_hi68=float(fit.rnd_band.density_hi68[i]),
            density_lo90=float(fit.rnd_band.density_lo90[i]),
            density_hi90=float(fit.rnd_band.density_hi90[i]),
        )
        for i in range(len(K_rnd))
    ]

    ssvi = None
    sabr = None
    if fit.iv_fit.ssvi is not None:
        p = fit.iv_fit.ssvi
        ssvi = SSVIParamsModel(
            theta_T=p.theta_T,
            rho=p.rho,
            eta=p.eta,
            gamma=p.gamma,
            rmse_iv=p.rmse_iv,
            n_obs=p.n_obs,
            butterfly_margin=p.butterfly_margin,
            param_cov=p.param_cov.tolist(),
        )
    if fit.iv_fit.sabr is not None:
        s = fit.iv_fit.sabr
        sabr = SABRParamsModel(
            alpha=s.alpha,
            beta=s.beta,
            rho=s.rho,
            nu=s.nu,
            rmse_iv=s.rmse_iv,
            n_obs=s.n_obs,
            param_cov=s.param_cov.tolist(),
        )

    return SurfaceFitResponse(
        ticker=fit.ticker,
        spot=fit.spot,
        expiry=fit.expiry,
        T=fit.T,
        F=fit.F,
        D=fit.D,
        r=fit.r,
        model=fit.model.value,
        parity=ParityDiagnostics(
            r2=fit.parity.r2,
            residual_std=fit.parity.residual_std,
            n_strikes=fit.parity.n_strikes,
            n_iterations=fit.parity.n_iterations,
            r_implied_raw=fit.r_implied_raw,
        ),
        ssvi=ssvi,
        sabr=sabr,
        iv_curve=iv_curve,
        rnd=rnd_points,
        arbitrage=ArbDiagnosticsModel(
            durrleman_min=fit.arbitrage.durrleman_min,
            lee_left=fit.arbitrage.lee_left,
            lee_right=fit.arbitrage.lee_right,
            n_neg_clipped=fit.arbitrage.n_neg_clipped,
            integral_q=fit.arbitrage.integral_q,
            mean_recovery_pct=fit.arbitrage.mean_recovery_pct,
        ),
        available_expiries=fit.available_expiries,
        is_stale=fit.is_stale,
        stale_fraction=fit.stale_fraction,
    )


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


def _service():
    from dashboard.deps import get_state_value

    svc = get_state_value("option_surface_service")
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="OptionSurfaceService not initialised on this app instance",
        )
    return svc


@router.get("/options/surface", response_model=SurfaceFitResponse)
async def get_options_surface(
    ticker: str = Query(default="SPY"),
    expiry: str = Query(default="", description="YYYY-MM-DD; blank for auto"),
    model: Literal["ssvi", "sabr"] = Query(default="ssvi"),
    n_grid: int = Query(default=200, ge=20, le=1000),
    gp_samples: int = Query(default=500, ge=10, le=5000),
) -> SurfaceFitResponse:
    """Single-expiry RND + hybrid IV fit."""
    svc = _service()
    try:
        fit = await svc.get_single_expiry_fit(
            ticker,
            expiry=expiry or None,
            model=VolModel(model),
            n_grid=n_grid,
            gp_samples=gp_samples,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _surface_fit_to_response(fit)


@router.get("/options/surface/multi", response_model=MultiSurfaceFitResponse)
async def get_options_surface_multi(
    ticker: str = Query(default="SPY"),
    n_expiries: int = Query(default=8, ge=1, le=20),
    model: Literal["ssvi", "sabr"] = Query(default="ssvi"),
    n_grid: int = Query(default=120, ge=20, le=500),
) -> MultiSurfaceFitResponse:
    """Multi-expiry IV + RND surface on a shared log-moneyness grid."""
    svc = _service()
    try:
        payload = await svc.get_multi_expiry_fit(
            ticker,
            n_expiries=n_expiries,
            model=VolModel(model),
            n_grid=n_grid,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MultiSurfaceFitResponse(**payload)


@router.get("/options/spread-curve", response_model=SpreadCurveResponse)
async def get_options_spread_curve(
    ticker: str = Query(default="SPY"),
    n_expiries: int = Query(default=12, ge=1, le=24),
) -> SpreadCurveResponse:
    """Per-expiry ATM put-call IV spread (decimal IV; spread = put − call)."""
    svc = _service()
    try:
        payload = await svc.get_spread_curve(ticker, n_expiries=n_expiries)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SpreadCurveResponse(**payload)
