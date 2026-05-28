"""
SSVI parametric volatility curve — Gatheral & Jacquier 2014.

SSVI ("Surface SVI") parameterises total implied variance per slice with
three free parameters (ρ, η, γ) anchored on the ATM total variance θ_T.
Under the parameter constraints in Theorem 4.2 of Gatheral & Jacquier
(2014) the slice is butterfly-arbitrage-free *by construction* — the
property the raw SABR fit lacks.

Curve formula (log-moneyness ``k = log(K/F)``)::

    φ      = η · θ_T^{-γ}              (power-law ATM-skew scaling)
    u(k)   = φ·k + ρ
    h(k)   = √(u² + 1 − ρ²)
    w(k)   = (θ_T / 2) · [ 1 + ρ·φ·k + h ]
    σ(k)   = √(w(k) / T)

Analytic derivatives (consumed by the Gatheral closed-form RND)::

    w'(k)   = (θ_T / 2) · φ · [ρ + u/h]
    w''(k)  = (θ_T / 2) · φ² · (1 − ρ²) / h³
    σ'(k)   = w'(k) / (2 · T · σ(k))
    σ''(k)  = w''(k) / (2 · T · σ(k))  −  (σ'(k))² / σ(k)

(Derivations: dh/dk = uφ/h ⇒ d(u/h)/dk = φ(h² − u²)/h³ = φ(1−ρ²)/h³.
Second σ derivative from differentiating 2T·σ·σ' = w' twice.)

No-arbitrage (butterfly, sufficient conditions, G-J Thm 4.2)::

    θ_T · φ · (1 + |ρ|)  ≤ 4                                  (B-1)
    θ_T · φ² · (1 + |ρ|) ≤ 4                                  (B-2)

The minimum slack to (B-1) and (B-2) is reported as
``butterfly_margin`` and hard-enforced during calibration via a
quadratic penalty added to the residual vector.

Reference:
    Gatheral, J. & Jacquier, A. (2014). Arbitrage-Free SVI Volatility
        Surfaces. Quantitative Finance 14 (1), 59–71.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from core.exceptions import ValidationError
from stats.options.types import SSVIParams

# Parameter box.
_RHO_BOUNDS = (-0.999, 0.999)
_ETA_BOUNDS = (1e-4, 10.0)
_GAMMA_BOUNDS = (0.0, 0.5)

# Calibration knobs.
_BUTTERFLY_BOUND = 4.0
_PENALTY_LAMBDA = 1e4
_MIN_OBS_FOR_FIT = 4
_ATM_BAND_FOR_THETA = 0.10  # |k| ≤ this defines the ATM parabola support
_DEFAULT_INIT = (-0.5, 0.5, 0.4)  # (ρ₀, η₀, γ₀) equity-typical

# Numerical guards.
_SIGMA_FLOOR = 1e-12


def ssvi_phi(theta_T: float, eta: float, gamma: float) -> float:
    """ATM-skew scaling factor φ = η · θ^{-γ} (Gatheral-Jacquier §4.2)."""
    return float(eta * theta_T ** (-gamma))


def _ssvi_uh(k: np.ndarray, rho: float, phi: float) -> tuple[np.ndarray, np.ndarray]:
    """Helpers ``u(k) = φ·k + ρ`` and ``h(k) = √(u² + 1 − ρ²)``."""
    u = phi * k + rho
    h = np.sqrt(u * u + 1.0 - rho * rho)
    return u, h


def ssvi_total_variance(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
) -> np.ndarray:
    """SSVI total implied variance ``w(k; θ_T, ρ, η, γ)``."""
    k_arr = np.asarray(k, dtype=float)
    phi = ssvi_phi(theta_T, eta, gamma)
    _, h = _ssvi_uh(k_arr, rho, phi)
    return 0.5 * theta_T * (1.0 + rho * phi * k_arr + h)


def ssvi_iv(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
    T: float,
) -> np.ndarray:
    """SSVI implied volatility σ(k) = √(w(k) / T)."""
    w = ssvi_total_variance(k, theta_T, rho, eta, gamma)
    return np.sqrt(np.maximum(w, 0.0) / T)


def ssvi_dw_dk(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
) -> np.ndarray:
    """w'(k) = (θ_T / 2) · φ · [ρ + u / h]."""
    k_arr = np.asarray(k, dtype=float)
    phi = ssvi_phi(theta_T, eta, gamma)
    u, h = _ssvi_uh(k_arr, rho, phi)
    return 0.5 * theta_T * phi * (rho + u / h)


def ssvi_d2w_dk2(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
) -> np.ndarray:
    """w''(k) = (θ_T / 2) · φ² · (1 − ρ²) / h³."""
    k_arr = np.asarray(k, dtype=float)
    phi = ssvi_phi(theta_T, eta, gamma)
    _, h = _ssvi_uh(k_arr, rho, phi)
    return 0.5 * theta_T * phi * phi * (1.0 - rho * rho) / (h**3)


def ssvi_dsigma_dk(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
    T: float,
) -> np.ndarray:
    """σ'(k) = w'(k) / (2·T·σ(k))."""
    sigma = ssvi_iv(k, theta_T, rho, eta, gamma, T)
    return ssvi_dw_dk(k, theta_T, rho, eta, gamma) / (2.0 * T * np.maximum(sigma, _SIGMA_FLOOR))


def ssvi_d2sigma_dk2(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
    T: float,
) -> np.ndarray:
    """σ''(k) = w''(k)/(2·T·σ) − (σ'(k))² / σ."""
    sigma = ssvi_iv(k, theta_T, rho, eta, gamma, T)
    sig_safe = np.maximum(sigma, _SIGMA_FLOOR)
    s_prime = ssvi_dsigma_dk(k, theta_T, rho, eta, gamma, T)
    w_pp = ssvi_d2w_dk2(k, theta_T, rho, eta, gamma)
    return w_pp / (2.0 * T * sig_safe) - (s_prime * s_prime) / sig_safe


def durrleman_g_ssvi(
    k,
    theta_T: float,
    rho: float,
    eta: float,
    gamma: float,
) -> np.ndarray:
    """Durrleman butterfly indicator on the analytic SSVI curve.

    ``g(k) = (1 − k·w'/(2·w))² − (w')²/4·(1/w + 1/4) + w''/2``

    g(k) ≥ 0 everywhere is the necessary-and-sufficient condition for a
    smile to be butterfly-arb-free (Gatheral 2014). The Gatheral RND
    factor is the same g(k), so this also serves as the density factor
    in the closed-form RND.
    """
    k_arr = np.asarray(k, dtype=float)
    w = ssvi_total_variance(k_arr, theta_T, rho, eta, gamma)
    wp = ssvi_dw_dk(k_arr, theta_T, rho, eta, gamma)
    wpp = ssvi_d2w_dk2(k_arr, theta_T, rho, eta, gamma)
    safe_w = np.maximum(w, _SIGMA_FLOOR)
    term_1 = (1.0 - k_arr * wp / (2.0 * safe_w)) ** 2
    term_2 = (wp * wp) / 4.0 * (1.0 / safe_w + 0.25)
    return term_1 - term_2 + wpp / 2.0


def butterfly_margin(theta_T: float, rho: float, eta: float, gamma: float) -> float:
    """Slack to the Gatheral-Jacquier Thm 4.2 butterfly bound.

    Positive ⇒ inside the arbitrage-free interior. Negative ⇒
    butterfly arbitrage is admissible somewhere on the slice.
    """
    phi = ssvi_phi(theta_T, eta, gamma)
    rho_factor = 1.0 + abs(rho)
    margin_1 = _BUTTERFLY_BOUND - theta_T * phi * rho_factor
    margin_2 = _BUTTERFLY_BOUND - theta_T * phi * phi * rho_factor
    return float(min(margin_1, margin_2))


def _atm_theta_T(k: np.ndarray, sigma: np.ndarray, T: float) -> float:
    """Estimate θ_T = σ²_ATM · T by parabolic fit near k = 0.

    Fits ``σ² ≈ a + b·k + c·k²`` on |k| ≤ 0.10 and evaluates at k = 0.
    Falls back to the global ``mean(σ²)·T`` if too few points lie in the
    ATM band.
    """
    mask = np.abs(k) <= _ATM_BAND_FOR_THETA
    if mask.sum() < 3:
        return float(np.mean(sigma * sigma)) * T
    A = np.column_stack([np.ones(mask.sum()), k[mask], k[mask] ** 2])
    coefs, *_ = np.linalg.lstsq(A, sigma[mask] ** 2, rcond=None)
    sigma2_atm = float(coefs[0])
    if sigma2_atm <= 0:
        return float(np.mean(sigma * sigma)) * T
    return sigma2_atm * T


def calibrate_ssvi(
    strikes: np.ndarray,
    iv_market: np.ndarray,
    F: float,
    T: float,
    *,
    vega: np.ndarray | None = None,
    theta_T_hint: float | None = None,
    n_starts: int = 5,
    seed: int = 0,
) -> SSVIParams:
    """Fit (ρ, η, γ) at fixed θ_T to market IVs.

    Objective::

        min Σ_i  w_i · (w_SSVI(k_i; ρ, η, γ) − w_mkt(k_i))²
              + λ · [max(0, θ·φ·(1+|ρ|) − 4)²
                   + max(0, θ·φ²·(1+|ρ|) − 4)²]

    where w_i = vega_i² (scales the IV residual into total-variance
    units) and the penalty enforces the Gatheral-Jacquier butterfly
    bound. λ = 10⁴ is large enough to push optima into the arb-free
    interior but small enough to leave the interior fully visible to
    the optimiser.

    Args:
        strikes:       market strike grid for the slice.
        iv_market:     corresponding market mid IVs (decimal form).
        F:             parity-implied forward.
        T:             time to expiry in years.
        vega:          optional vega weights; defaults to all-ones.
        theta_T_hint:  override the parabolic ATM-anchor estimate of
                       θ_T. Useful when the caller has a stronger ATM
                       reading (e.g. from a tighter-band parabola).
        n_starts:      1 deterministic start (LFK) + n_starts−1 random
                       restarts inside the parameter box.
        seed:          RNG seed for the random restarts.

    Returns:
        Calibrated ``SSVIParams`` including IV-space RMSE, butterfly
        margin, and the 3×3 covariance over (ρ, η, γ) at the optimum.

    Raises:
        ValueError:    fewer than ``_MIN_OBS_FOR_FIT`` valid IV points.
        RuntimeError:  all random restarts failed.
    """
    if F <= 0:
        raise ValidationError(f"SSVI calibration needs F > 0 (got {F}).")
    if T <= 0:
        raise ValidationError(f"SSVI calibration needs T > 0 (got {T}).")
    K = np.asarray(strikes, dtype=float)
    iv = np.asarray(iv_market, dtype=float)
    valid = np.isfinite(iv) & (iv > 0.0)
    K, iv = K[valid], iv[valid]
    vega_v = np.ones_like(iv) if vega is None else np.asarray(vega, dtype=float)[valid]

    if len(K) < _MIN_OBS_FOR_FIT:
        raise ValueError(
            f"SSVI calibration needs ≥ {_MIN_OBS_FOR_FIT} valid IV observations (got {len(K)})"
        )

    k = np.log(K / F)
    w_mkt = (iv * iv) * T
    weights = np.maximum(vega_v * vega_v, 1e-12)
    sqrt_w = np.sqrt(weights)
    sqrt_lambda = np.sqrt(_PENALTY_LAMBDA)

    theta_T = float(theta_T_hint) if theta_T_hint is not None else _atm_theta_T(k, iv, T)

    bounds_lo = (_RHO_BOUNDS[0], _ETA_BOUNDS[0], _GAMMA_BOUNDS[0])
    bounds_hi = (_RHO_BOUNDS[1], _ETA_BOUNDS[1], _GAMMA_BOUNDS[1])

    def residuals(x: np.ndarray) -> np.ndarray:
        rho_v, eta_v, gamma_v = float(x[0]), float(x[1]), float(x[2])
        w_model = ssvi_total_variance(k, theta_T, rho_v, eta_v, gamma_v)
        r_fit = sqrt_w * (w_model - w_mkt)
        phi_v = ssvi_phi(theta_T, eta_v, gamma_v)
        rho_factor = 1.0 + abs(rho_v)
        excess_1 = max(0.0, theta_T * phi_v * rho_factor - _BUTTERFLY_BOUND)
        excess_2 = max(0.0, theta_T * phi_v * phi_v * rho_factor - _BUTTERFLY_BOUND)
        r_pen = sqrt_lambda * np.array([excess_1, excess_2])
        return np.concatenate([r_fit, r_pen])

    rng = np.random.default_rng(seed)
    starts: list[np.ndarray] = [np.array(_DEFAULT_INIT)]
    for _ in range(max(n_starts - 1, 0)):
        starts.append(
            np.array(
                [
                    rng.uniform(-0.9, 0.0),
                    rng.uniform(0.1, 1.5),
                    rng.uniform(0.1, 0.45),
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
                x_scale=[0.5, 0.5, 0.2],
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
        raise RuntimeError("SSVI calibration failed across all starts")

    rho, eta, gamma = (
        float(best_res.x[0]),
        float(best_res.x[1]),
        float(best_res.x[2]),
    )

    iv_model = ssvi_iv(k, theta_T, rho, eta, gamma, T)
    rmse_iv = float(np.sqrt(np.mean((iv_model - iv) ** 2)))

    # 3×3 covariance from (JᵀJ)⁻¹ at optimum. ``best_res.jac`` is the
    # full Jacobian — including the penalty rows. When the penalty is
    # inactive (interior optimum) the penalty rows are zero and don't
    # contribute, which is the regime we want covariance reported in.
    J = best_res.jac
    try:
        cov = np.linalg.inv(J.T @ J)
    except np.linalg.LinAlgError:
        cov = np.full((3, 3), np.nan)

    return SSVIParams(
        theta_T=float(theta_T),
        rho=rho,
        eta=eta,
        gamma=gamma,
        rmse_iv=rmse_iv,
        n_obs=int(len(K)),
        butterfly_margin=butterfly_margin(theta_T, rho, eta, gamma),
        param_cov=cov,
    )


def ssvi_iv_curve(K_grid: np.ndarray, F: float, T: float, params: SSVIParams) -> np.ndarray:
    """Evaluate σ(K) on an arbitrary strike grid using fitted parameters."""
    k = np.log(np.asarray(K_grid, dtype=float) / F)
    return ssvi_iv(k, params.theta_T, params.rho, params.eta, params.gamma, T)
