"""
SABR — Hagan 2002 lognormal stochastic volatility model.

SABR (Stochastic Alpha Beta Rho) dynamics under the T-forward measure:

    dF_t = σ_t · F_t^β · dW_t,    F_0 = f
    dσ_t = ν · σ_t · dZ_t,        σ_0 = α
    d⟨W, Z⟩_t = ρ · dt

with parameters (α, β, ρ, ν). Hagan, Kumar, Lesniewski & Woodward 2002
derived the closed-form asymptotic expansion for the Black-76 implied
volatility::

    σ_B(K, F) = α / { (FK)^((1−β)/2) · ξ(ln F/K) }
              · z / x(z)
              · { 1 + 𝒞 · T }

with

    z       = (ν / α) · (FK)^((1−β)/2) · ln(F/K)
    x(z)    = ln( [ √(1 − 2ρz + z²) + z − ρ ] / (1 − ρ) )
    ξ(L)    = 1 + ((1−β)² / 24)·L²  +  ((1−β)⁴ / 1920)·L⁴
    𝒞       = ((1−β)² / 24) · α² / (FK)^(1−β)
            + (ρ β ν α) / (4 · (FK)^((1−β)/2))
            + ((2 − 3ρ²) / 24) · ν²

ATM limit: ``z / x(z) → 1`` as ``K → F``.

β is **fixed by asset class** (β and α are near-collinear when fit to a
single smile, so β is conventionally pinned — see ``types.AssetClass``
and ``BETA_BY_ASSET_CLASS``). Only (α, ρ, ν) are calibrated.

Reference:
    Hagan, P. S., Kumar, D., Lesniewski, A. S., Woodward, D. E. (2002).
        "Managing Smile Risk". Wilmott Magazine.
    Le Floc'h, F. & Kennedy, G. (2014). "Explicit SABR Calibration
        Through Simple Expansions" (SSRN 2467231) — for the initial-
        guess heuristics used here.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from core.exceptions import ValidationError
from stats.options.types import SABRParams

# Parameter box for (α, ρ, ν).
_ALPHA_BOUNDS = (1e-4, 5.0)
_RHO_BOUNDS = (-0.999, 0.999)
_NU_BOUNDS = (1e-4, 5.0)

# Calibration knobs.
_MIN_OBS_FOR_FIT = 4
_ATM_EPS = 1e-7  # |log(F/K)| below which we switch to the ATM-limit branch
_DEFAULT_RHO_INIT = -0.3  # equity-typical mild negative skew


def hagan_lognormal_iv(
    F: float,
    K,
    T: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> np.ndarray:
    """Black-76 implied vol for SABR (Hagan 2002, eq. 2.17a).

    Vectorised over ``K``. ATM strikes use the K → F limit (z/x(z) = 1)
    to avoid the 0/0 singularity in the general form.
    """
    K_arr = np.asarray(K, dtype=float)
    out = np.empty_like(K_arr)

    abs_log = np.abs(np.log(F / K_arr))
    atm_mask = abs_log < _ATM_EPS

    # ATM branch: z / x(z) → 1, so the formula collapses.
    if atm_mask.any():
        FK_beta = F ** (1.0 - beta)
        sigma_atm = (alpha / FK_beta) * (
            1.0
            + (
                ((1.0 - beta) ** 2 / 24.0) * alpha * alpha / (FK_beta * FK_beta)
                + 0.25 * rho * beta * nu * alpha / FK_beta
                + ((2.0 - 3.0 * rho * rho) / 24.0) * nu * nu
            )
            * T
        )
        out[atm_mask] = sigma_atm

    # Non-ATM general branch.
    nm = ~atm_mask
    if nm.any():
        Knm = K_arr[nm]
        FK = F * Knm
        FK_pow = FK ** ((1.0 - beta) / 2.0)
        log_FK = np.log(F / Knm)

        z = (nu / alpha) * FK_pow * log_FK
        sqrt_term = np.sqrt(1.0 - 2.0 * rho * z + z * z)
        x_z = np.log((sqrt_term + z - rho) / (1.0 - rho))

        xi = (
            1.0
            + ((1.0 - beta) ** 2 / 24.0) * log_FK * log_FK
            + ((1.0 - beta) ** 4 / 1920.0) * log_FK**4
        )
        prefactor = alpha / (FK_pow * xi)

        zx = np.where(np.abs(z) < 1e-12, 1.0, z / x_z)

        correction = (
            1.0
            + (
                ((1.0 - beta) ** 2 / 24.0) * (alpha * alpha) / (FK ** (1.0 - beta))
                + 0.25 * rho * beta * nu * alpha / FK_pow
                + ((2.0 - 3.0 * rho * rho) / 24.0) * nu * nu
            )
            * T
        )

        out[nm] = prefactor * zx * correction

    return out


def sabr_iv_curve(K_grid: np.ndarray, F: float, T: float, params: SABRParams) -> np.ndarray:
    """Evaluate the calibrated SABR σ(K) on an arbitrary strike grid."""
    return hagan_lognormal_iv(F, K_grid, T, params.alpha, params.beta, params.rho, params.nu)


def _initial_guesses(
    k: np.ndarray, iv: np.ndarray, F: float, T: float, beta: float
) -> tuple[float, float, float]:
    """Le Floc'h–Kennedy initial guesses (α₀, ρ₀, ν₀).

    α₀ comes from the ATM SABR cubic with ν = 0:
            σ_ATM ≈ α / F^(1-β)  ⇒  α₀ = σ_ATM · F^(1-β).

    ρ₀ comes from the sign of the local skew at ATM (linear coefficient
    of a 3-term parabola fit around k = 0): equity-typical negative skew
    gives ρ₀ < 0.

    ν₀ comes from the quadratic skew coefficient s:
            ν₀ ≈ √(24·s) / (3·√T).
    """
    atm_idx = int(np.argmin(np.abs(k)))
    sigma_atm = float(iv[atm_idx])
    alpha_0 = sigma_atm * F ** (1.0 - beta)

    # Local 3-term parabola for skew (linear) and curvature (quadratic).
    mask = np.abs(k) <= 0.15
    if mask.sum() >= 3:
        A = np.column_stack([np.ones(mask.sum()), k[mask], k[mask] ** 2])
        coefs, *_ = np.linalg.lstsq(A, iv[mask], rcond=None)
        skew_slope = float(coefs[1])
        skew_quad = float(coefs[2])
    else:
        skew_slope = 0.0
        skew_quad = 0.0

    rho_0 = (
        -abs(_DEFAULT_RHO_INIT)
        if skew_slope < 0
        else (abs(_DEFAULT_RHO_INIT) if skew_slope > 0 else _DEFAULT_RHO_INIT)
    )

    if skew_quad > 0 and T > 0:
        nu_0 = float(np.sqrt(24.0 * skew_quad) / (3.0 * np.sqrt(T)))
        nu_0 = float(np.clip(nu_0, 0.05, 3.0))
    else:
        nu_0 = 0.5

    return alpha_0, rho_0, nu_0


def calibrate_sabr(
    strikes: np.ndarray,
    iv_market: np.ndarray,
    F: float,
    T: float,
    beta: float,
    *,
    vega: np.ndarray | None = None,
    n_starts: int = 5,
    seed: int = 0,
) -> SABRParams:
    """Fit (α, ρ, ν) at fixed β to market OTM IVs.

    Objective::

        min Σ_i  vega_i · (σ_B(K_i; α, β, ρ, ν) − σ_i^mkt)²

    via ``scipy.optimize.least_squares`` (trust-region reflective,
    soft-L1 loss). 5 starts: Le Floc'h–Kennedy default plus 4 random
    restarts.

    Args:
        strikes:      market strike grid.
        iv_market:    corresponding market mid IVs (decimal).
        F:            parity-implied forward.
        T:            time to expiry (years).
        beta:         CEV elasticity, fixed by asset class.
        vega:         optional vega weights; defaults to all-ones.
        n_starts:     1 LFK start + (n_starts−1) random restarts.
        seed:         RNG seed for the random restarts.

    Returns:
        Calibrated ``SABRParams`` with IV-space RMSE and the 4×4
        covariance over (α, β, ρ, ν) at the optimum. β row / col are
        zero since β is held fixed.

    Raises:
        ValueError:    fewer than ``_MIN_OBS_FOR_FIT`` valid IV points.
        RuntimeError:  all starts failed.
    """
    if F <= 0:
        raise ValidationError(f"SABR calibration needs F > 0 (got {F}).")
    if T <= 0:
        raise ValidationError(f"SABR calibration needs T > 0 (got {T}).")
    K = np.asarray(strikes, dtype=float)
    iv = np.asarray(iv_market, dtype=float)
    valid = np.isfinite(iv) & (iv > 0.0)
    K, iv = K[valid], iv[valid]
    vega_v = np.ones_like(iv) if vega is None else np.asarray(vega, dtype=float)[valid]

    if len(K) < _MIN_OBS_FOR_FIT:
        raise ValueError(
            f"SABR calibration needs ≥ {_MIN_OBS_FOR_FIT} valid IV observations (got {len(K)})"
        )

    k = np.log(K / F)
    sqrt_w = np.sqrt(np.maximum(vega_v, 1e-12))

    alpha_0, rho_0, nu_0 = _initial_guesses(k, iv, F, T, beta)

    def residuals(x: np.ndarray) -> np.ndarray:
        a, r, n = float(x[0]), float(x[1]), float(x[2])
        try:
            iv_model = hagan_lognormal_iv(F, K, T, a, beta, r, n)
        except (ValueError, ArithmeticError, OverflowError):
            # Hagan formula can blow up for ν / α near zero or
            # ρ very close to ±1. Return a large residual so the
            # optimiser steps away from this corner.
            return np.full_like(iv, 1e3)
        return sqrt_w * (iv_model - iv)

    bounds_lo = (_ALPHA_BOUNDS[0], _RHO_BOUNDS[0], _NU_BOUNDS[0])
    bounds_hi = (_ALPHA_BOUNDS[1], _RHO_BOUNDS[1], _NU_BOUNDS[1])

    rng = np.random.default_rng(seed)
    starts: list[np.ndarray] = [np.array([alpha_0, rho_0, nu_0])]
    for _ in range(max(n_starts - 1, 0)):
        starts.append(
            np.array(
                [
                    float(rng.uniform(0.05, 1.0) * max(F ** (1.0 - beta), 0.1)),
                    float(rng.uniform(-0.8, 0.0)),
                    float(rng.uniform(0.1, 1.5)),
                ]
            )
        )

    best_cost = np.inf
    best_res = None
    for x0 in starts:
        x0_clip = np.clip(x0, bounds_lo, bounds_hi)
        try:
            res = least_squares(
                residuals,
                x0=x0_clip,
                bounds=(bounds_lo, bounds_hi),
                method="trf",
                loss="soft_l1",
                x_scale=[0.1, 0.5, 0.5],
                max_nfev=400,
            )
        except (ValueError, RuntimeError, np.linalg.LinAlgError, OverflowError):
            # least_squares can fail with ValueError on bad bounds or
            # RuntimeError if it can't converge. Skip this start and try
            # the next one.
            continue
        if res.cost < best_cost:
            best_cost = float(res.cost)
            best_res = res

    if best_res is None:
        raise RuntimeError("SABR calibration failed across all starts")

    alpha = float(best_res.x[0])
    rho = float(best_res.x[1])
    nu = float(best_res.x[2])

    iv_model = hagan_lognormal_iv(F, K, T, alpha, beta, rho, nu)
    rmse_iv = float(np.sqrt(np.mean((iv_model - iv) ** 2)))

    # 3×3 covariance from (JᵀJ)⁻¹, padded to 4×4 with β zeroed.
    J = best_res.jac
    try:
        cov_3 = np.linalg.inv(J.T @ J)
    except np.linalg.LinAlgError:
        cov_3 = np.full((3, 3), np.nan)
    cov_4 = np.zeros((4, 4))
    # ordering: (α, β, ρ, ν) — β at index 1 is the fixed dim.
    indices = (0, 2, 3)
    for i_dst, i_src in enumerate(indices):
        for j_dst, j_src in enumerate(indices):
            cov_4[i_src, j_src] = cov_3[i_dst, j_dst]

    return SABRParams(
        alpha=alpha,
        beta=float(beta),
        rho=rho,
        nu=nu,
        rmse_iv=rmse_iv,
        n_obs=int(len(K)),
        param_cov=cov_4,
    )
