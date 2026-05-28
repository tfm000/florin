"""
Slice orchestrator — assembles every stage of the pipeline.

Public entry points:
    fit_expiry(quotes, ticker, expiry, T, spot, model=SSVI, asset_class=EQUITY)
        Full per-expiry SurfaceFit (parity, IV inversion, parametric fit,
        GP residual, RND with bands, arbitrage diagnostics).

Higher-level multi-expiry orchestration lives in the service layer
(``dashboard/services/option_surface.py``) so that we can fan out via
``asyncio.gather``; the pipeline itself is pure-synchronous.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.exceptions import ValidationError
from stats.options.clean import otm_filter, quality_filter, restrict_log_moneyness
from stats.options.diagnostics import durrleman_g, lee_wing_slopes
from stats.options.gp import fit_gp_residual_with_derivatives
from stats.options.ivinvert import invert_chain
from stats.options.parity import fit_forward_at_rate, fit_parity
from stats.options.pricing import bs_vega
from stats.options.rnd import rnd_with_uncertainty
from stats.options.sabr import (
    calibrate_sabr,
    hagan_lognormal_iv,
)
from stats.options.ssvi import (
    calibrate_ssvi,
    ssvi_d2sigma_dk2,
    ssvi_dsigma_dk,
    ssvi_iv,
)
from stats.options.types import (
    BETA_BY_ASSET_CLASS,
    ArbDiagnostics,
    AssetClass,
    ExpiryChain,
    FilterConfig,
    IVFit,
    SurfaceFit,
    VolModel,
)


def _ensure_mid_spread(quotes: pd.DataFrame) -> pd.DataFrame:
    """Compute mid, spread, and an is_stale default from bid/ask if missing.

    ``is_stale`` is the per-row last-price fallback flag set in
    ``data/yfinance_provider.py::_serialize``. Synthetic test chains
    typically don't carry it; default to False so the pipeline can
    still process them.
    """
    out = quotes.copy()
    if "mid" not in out.columns:
        out["mid"] = 0.5 * (out["bid"] + out["ask"])
    if "spread" not in out.columns:
        out["spread"] = out["ask"] - out["bid"]
    if "is_stale" not in out.columns:
        out["is_stale"] = False
    return out


def _adaptive_k_grid(
    F: float,
    K_lo_mult: float,
    K_hi_mult: float,
    n_grid: int,
    *,
    concentration: float = 2.5,
) -> np.ndarray:
    """Non-uniform K-grid clustered near the forward F.

    The risk-neutral density of an option chain has compact support
    centred near F (typically within a few σ√T). A uniform K-grid
    over ``[K_lo_mult·F, K_hi_mult·F]`` wastes resolution on the
    flat-zero tails. We instead map a uniform ``u ∈ [-1, 1]`` through
    ``sinh(u·c) / sinh(c)`` so grid spacing at the centre is roughly
    ``cosh(c)`` times tighter than at the endpoints — for the default
    ``c = 2.5`` that's a ~6× density gain at the peak with the same
    total point count.

    Why sinh and not, say, arctanh or tan: ``sinh`` is monotone and
    smooth on all of ℝ (so the warp doesn't introduce kinks),
    symmetric about zero, and ``cosh(c)`` is finite (no singularity
    at the endpoints — important for the integration sanity gates).

    Trapezoidal integration on the resulting non-uniform grid is
    still exact for piecewise-linear functions; integration error
    scales with the local spacing squared, so the peak gets *better*
    accuracy than under a uniform grid, while the near-zero tails
    contribute a vanishing amount to ∫q regardless of spacing.

    Args:
        F:                 forward (used to set the grid centre).
        K_lo_mult, K_hi_mult: range as multiples of F (e.g. 0.5, 1.5).
        n_grid:            total point count.
        concentration:     sinh stretch factor; higher → tighter
                           clustering at the centre. Default 2.5
                           gives ~6× density gain at F.

    Returns:
        Strictly increasing 1D array of strikes with length ``n_grid``.
    """
    u = np.linspace(-1.0, 1.0, n_grid)
    warp = np.sinh(u * concentration) / np.sinh(concentration)
    k_lo = K_lo_mult * F
    k_hi = K_hi_mult * F
    return 0.5 * (k_lo + k_hi) + 0.5 * (k_hi - k_lo) * warp


def _sabr_derivs_k_space(
    K_grid: np.ndarray,
    F: float,
    T: float,
    params,
    h: float = 1e-3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """5-point central FD on the analytic SABR curve in log-moneyness k.

    SABR's ``σ(K)`` is analytic in K, so FD on the smooth curve is
    machine-precision (the inputs are not noisy market quotes). Returns
    ``(σ, σ_k, σ_kk)`` on ``K_grid``, with derivatives wrt
    ``k = log(K/F)``.
    """
    k = np.log(K_grid / F)

    def sigma_k(kk: np.ndarray) -> np.ndarray:
        return hagan_lognormal_iv(
            F, F * np.exp(kk), T, params.alpha, params.beta, params.rho, params.nu
        )

    sig = sigma_k(k)
    sig_p = sigma_k(k + h)
    sig_m = sigma_k(k - h)
    sig_pp = sigma_k(k + 2 * h)
    sig_mm = sigma_k(k - 2 * h)
    sig_prime = (8.0 * (sig_p - sig_m) - (sig_pp - sig_mm)) / (12.0 * h)
    sig_double = (-sig_pp + 16.0 * sig_p - 30.0 * sig + 16.0 * sig_m - sig_mm) / (12.0 * h * h)
    return sig, sig_prime, sig_double


def fit_expiry(
    quotes: pd.DataFrame,
    *,
    ticker: str,
    expiry: str,
    T: float,
    spot: float,
    r_external: float,
    model: VolModel = VolModel.SSVI,
    asset_class: AssetClass = AssetClass.EQUITY,
    n_grid: int = 200,
    gp_samples: int = 500,
    seed: int = 0,
    filter_config: FilterConfig | None = None,
    K_lo_mult: float = 0.5,
    K_hi_mult: float = 1.5,
    available_expiries: list[str] | None = None,
) -> SurfaceFit:
    """Full slice fit — see module docstring.

    Pipeline stages mirror ``stats/options/__init__.py`` exactly: clean
    → parity → OTM → IV inversion → vega → parametric → GP residual →
    RND-with-uncertainty → arbitrage diagnostics.

    Raises:
        ValidationError: ``T <= 0``, ``spot <= 0``, or empty quote frame
            (caller-side input bug — surfaces as HTTP 400 via the
            FlorinError handler).
        ValueError: a downstream stage (filter / parity / IV inversion)
            drops all remaining rows. Surfaces as HTTP 404 — the data
            was there but didn't pass cleaning.
    """
    if T <= 0:
        raise ValidationError(f"fit_expiry needs T > 0 (got {T:.6f} years). Expired chain?")
    if spot <= 0:
        raise ValidationError(f"fit_expiry needs spot > 0 (got {spot}).")
    if len(quotes) == 0:
        raise ValidationError(f"fit_expiry got an empty quote frame for {ticker} {expiry}.")
    quotes = _ensure_mid_spread(quotes)
    chain = ExpiryChain(ticker=ticker, spot=spot, expiry=expiry, T=T, quotes=quotes)

    # Stage 1 — quality filter.
    chain = quality_filter(chain, filter_config)
    if len(chain.quotes) == 0:
        raise ValueError(f"All quotes filtered out for {ticker} expiry {expiry} at quality stage")

    # Stage 2 — parity. We use ``r_external`` (SOFR) for pricing and
    # extract only ``F`` from the chain via the fixed-rate one-parameter
    # estimator. The unconstrained two-parameter regression is still
    # called separately to populate ``r_implied_raw`` as a diagnostic
    # (so quants can see how far the chain drifts from the true rate)
    # but its rate output is never used downstream.
    parity = fit_forward_at_rate(chain.quotes, spot=spot, T=T, r=r_external)
    try:
        parity_diag = fit_parity(chain.quotes, spot=spot, T=T)
        r_implied_raw = parity_diag.r
    except (ValueError, ValidationError):
        r_implied_raw = float("nan")
    F = parity.F
    D = parity.D
    # ``r_external`` is the rate used throughout the rest of the
    # pipeline; we expose it on ``SurfaceFit.r`` below. The chain-
    # implied diagnostic lives on ``r_implied_raw``.

    # Stage 3 — OTM-only filter & log-moneyness restriction.
    chain = otm_filter(chain, F)
    chain = restrict_log_moneyness(chain, F, filter_config)
    if len(chain.quotes) == 0:
        raise ValueError(f"No OTM quotes survived for {ticker} expiry {expiry}")

    # Stage 4 — IV inversion at each OTM mid.
    iv_df = invert_chain(chain.quotes, F, D, T)
    if len(iv_df) < 6:
        raise ValueError(
            f"Insufficient OTM IVs after inversion for {ticker} expiry {expiry} (got {len(iv_df)})"
        )
    K_obs = iv_df["strike"].to_numpy(dtype=float)
    iv_obs = iv_df["iv"].to_numpy(dtype=float)
    spread_obs = iv_df["spread"].to_numpy(dtype=float)
    vega_obs = np.asarray(bs_vega(F, K_obs, T, iv_obs, D), dtype=float)

    # Stage 5 — parametric fit (SSVI default, SABR optional).
    if model == VolModel.SSVI:
        ssvi_params = calibrate_ssvi(K_obs, iv_obs, F, T, vega=vega_obs, n_starts=5, seed=seed)
        iv_fit = IVFit(
            model=model,
            K_grid=np.array([]),  # populated below
            iv_grid=np.array([]),
            F=F,
            D=D,
            T=T,
            rmse_iv=ssvi_params.rmse_iv,
            n_obs=ssvi_params.n_obs,
            ssvi=ssvi_params,
        )
    else:
        beta = BETA_BY_ASSET_CLASS[asset_class]
        sabr_params = calibrate_sabr(
            K_obs, iv_obs, F, T, beta=beta, vega=vega_obs, n_starts=5, seed=seed
        )
        iv_fit = IVFit(
            model=model,
            K_grid=np.array([]),
            iv_grid=np.array([]),
            F=F,
            D=D,
            T=T,
            rmse_iv=sabr_params.rmse_iv,
            n_obs=sabr_params.n_obs,
            sabr=sabr_params,
        )

    # Stage 6 — output strike grid (adaptive: dense near F, sparse
    # in the tails; see ``_adaptive_k_grid`` docstring).
    K_grid = _adaptive_k_grid(F, K_lo_mult, K_hi_mult, n_grid)
    k_grid = np.log(K_grid / F)

    # Parametric IV and its k-derivatives on the output grid.
    if model == VolModel.SSVI:
        p = iv_fit.ssvi
        assert p is not None  # SSVI branch always populates iv_fit.ssvi
        theta_T, rho, eta, gamma = p.theta_T, p.rho, p.eta, p.gamma
        param_iv_grid = ssvi_iv(k_grid, theta_T, rho, eta, gamma, T)
        param_sp_k = ssvi_dsigma_dk(k_grid, theta_T, rho, eta, gamma, T)
        param_spp_k = ssvi_d2sigma_dk2(k_grid, theta_T, rho, eta, gamma, T)

        def parametric_iv_fn(K_arr: np.ndarray) -> np.ndarray:
            kk = np.log(np.asarray(K_arr, dtype=float) / F)
            return ssvi_iv(kk, theta_T, rho, eta, gamma, T)

    else:
        param_iv_grid, param_sp_k, param_spp_k = _sabr_derivs_k_space(K_grid, F, T, iv_fit.sabr)
        p_sabr = iv_fit.sabr
        assert p_sabr is not None  # SABR branch always populates iv_fit.sabr
        alpha, beta_s, rho_s, nu = p_sabr.alpha, p_sabr.beta, p_sabr.rho, p_sabr.nu

        def parametric_iv_fn(K_arr: np.ndarray) -> np.ndarray:
            return hagan_lognormal_iv(
                F,
                np.asarray(K_arr, dtype=float),
                T,
                alpha,
                beta_s,
                rho_s,
                nu,
            )

    iv_fit.K_grid = K_grid
    iv_fit.iv_grid = param_iv_grid

    # Stage 7 — GP residual fit with joint (r, r', r'') posterior samples.
    band, r_samples, rp_samples, rpp_samples = fit_gp_residual_with_derivatives(
        K_obs,
        iv_obs,
        F,
        T,
        parametric_iv_fn,
        param_iv_grid,
        K_grid,
        spread=spread_obs,
        vega=vega_obs,
        n_samples=gp_samples,
        seed=seed,
    )

    # Stage 8 — per-sample hybrid σ and its k-derivatives.
    sigma_samples = band.iv_samples  # (n_samples, n_grid), already parametric+r
    sigma_prime_samples = param_sp_k[None, :] + rp_samples
    sigma_double_samples = param_spp_k[None, :] + rpp_samples

    # Stage 9 — RND median + credible bands.
    rnd_band = rnd_with_uncertainty(
        K_grid,
        sigma_samples,
        sigma_prime_samples,
        sigma_double_samples,
        F,
        T,
        model,
        derivative_space="k",
    )

    # Stage 10 — diagnostics on the hybrid mean σ.
    hybrid_mean_sigma = band.iv_mean
    hybrid_mean_sp_k = param_sp_k + rp_samples.mean(axis=0)
    hybrid_mean_spp_k = param_spp_k + rpp_samples.mean(axis=0)
    w_mean = T * hybrid_mean_sigma * hybrid_mean_sigma
    wp_mean = 2.0 * T * hybrid_mean_sigma * hybrid_mean_sp_k
    wpp_mean = (
        2.0 * T * (hybrid_mean_sp_k * hybrid_mean_sp_k + hybrid_mean_sigma * hybrid_mean_spp_k)
    )
    g_mean = durrleman_g(k_grid, w_mean, wp_mean, wpp_mean)
    b_left, b_right = lee_wing_slopes(K_grid, hybrid_mean_sigma, T, F)

    arb = ArbDiagnostics(
        durrleman_min=float(np.min(g_mean)),
        lee_left=b_left,
        lee_right=b_right,
        n_neg_clipped=int(rnd_band.diagnostics.get("n_neg_clipped", 0)),
        integral_q=float(rnd_band.diagnostics.get("median_integral", float("nan"))),
        mean_recovery_pct=float(rnd_band.diagnostics.get("mean_recovery_pct", float("nan"))),
    )

    # Slice-level staleness diagnostic — share of underlying quotes
    # that fell back to lastPrice (no live bid/ask). When the slice is
    # ≥ 50 % stale we set the boolean for the UI to flag a degraded
    # fit; downstream parity-implied r will typically also be marked
    # ``fallback_sofr`` because R² collapses on stale chains.
    n_total = int(len(iv_df))
    if n_total > 0 and "is_stale" in iv_df.columns:
        n_stale = int(iv_df["is_stale"].sum())
        stale_fraction = n_stale / n_total
    else:
        stale_fraction = 0.0
    is_stale_slice = stale_fraction >= 0.5

    return SurfaceFit(
        ticker=ticker,
        spot=spot,
        expiry=expiry,
        T=T,
        F=F,
        D=D,
        # ``r`` is always the externally-provided SOFR. The chain-
        # implied rate (from the unconstrained two-parameter regression)
        # is preserved as ``r_implied_raw`` for diagnostic transparency.
        r=r_external,
        r_implied_raw=r_implied_raw,
        model=model,
        parity=parity,
        iv_fit=iv_fit,
        gp_band=band,
        rnd_band=rnd_band,
        arbitrage=arb,
        market_quotes=iv_df,
        available_expiries=list(available_expiries or []),
        stale_fraction=stale_fraction,
        is_stale=is_stale_slice,
    )
