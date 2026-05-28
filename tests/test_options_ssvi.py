"""Unit tests for the SSVI parametric volatility curve."""

from __future__ import annotations

import math

import numpy as np

from stats.options.ssvi import (
    butterfly_margin,
    calibrate_ssvi,
    durrleman_g_ssvi,
    ssvi_d2sigma_dk2,
    ssvi_d2w_dk2,
    ssvi_dsigma_dk,
    ssvi_dw_dk,
    ssvi_iv,
    ssvi_iv_curve,
    ssvi_phi,
    ssvi_total_variance,
)

# A clean, butterfly-arb-free seed.
TRUE_PARAMS = dict(theta_T=0.04, rho=-0.4, eta=0.5, gamma=0.3)
TRUE_T = 0.5


def test_total_variance_formula() -> None:
    """w(k) matches the hand-computed formula at sample log-moneyness points."""
    for k in (-0.2, 0.0, 0.15):
        theta = TRUE_PARAMS["theta_T"]
        rho = TRUE_PARAMS["rho"]
        eta = TRUE_PARAMS["eta"]
        gamma = TRUE_PARAMS["gamma"]
        phi = ssvi_phi(theta, eta, gamma)
        u = phi * k + rho
        h = math.sqrt(u * u + 1.0 - rho * rho)
        expected = 0.5 * theta * (1.0 + rho * phi * k + h)
        got = float(ssvi_total_variance(k, theta, rho, eta, gamma))
        assert math.isclose(got, expected, rel_tol=1e-12, abs_tol=1e-14)


def test_atm_anchor() -> None:
    """w(0) = θ_T exactly (the SSVI ATM anchor identity)."""
    w0 = float(
        ssvi_total_variance(
            0.0,
            TRUE_PARAMS["theta_T"],
            TRUE_PARAMS["rho"],
            TRUE_PARAMS["eta"],
            TRUE_PARAMS["gamma"],
        )
    )
    assert math.isclose(w0, TRUE_PARAMS["theta_T"], rel_tol=1e-14)


def test_derivative_finite_diff() -> None:
    """Analytic w', w'', σ', σ'' match high-order FD."""
    theta = TRUE_PARAMS["theta_T"]
    rho = TRUE_PARAMS["rho"]
    eta = TRUE_PARAMS["eta"]
    gamma = TRUE_PARAMS["gamma"]
    T = TRUE_T
    k_grid = np.linspace(-0.3, 0.3, 31)
    h = 1e-5

    # 5-point stencils for first and second derivatives.
    def w(k):
        return ssvi_total_variance(k, theta, rho, eta, gamma)

    def sig(k):
        return ssvi_iv(k, theta, rho, eta, gamma, T)

    fd_w_prime = (8 * (w(k_grid + h) - w(k_grid - h)) - (w(k_grid + 2 * h) - w(k_grid - 2 * h))) / (
        12 * h
    )
    fd_w_pp = (
        -w(k_grid + 2 * h)
        + 16 * w(k_grid + h)
        - 30 * w(k_grid)
        + 16 * w(k_grid - h)
        - w(k_grid - 2 * h)
    ) / (12 * h * h)
    fd_sig_prime = (
        8 * (sig(k_grid + h) - sig(k_grid - h)) - (sig(k_grid + 2 * h) - sig(k_grid - 2 * h))
    ) / (12 * h)
    fd_sig_pp = (
        -sig(k_grid + 2 * h)
        + 16 * sig(k_grid + h)
        - 30 * sig(k_grid)
        + 16 * sig(k_grid - h)
        - sig(k_grid - 2 * h)
    ) / (12 * h * h)

    np.testing.assert_allclose(ssvi_dw_dk(k_grid, theta, rho, eta, gamma), fd_w_prime, atol=1e-8)
    np.testing.assert_allclose(ssvi_d2w_dk2(k_grid, theta, rho, eta, gamma), fd_w_pp, atol=1e-6)
    np.testing.assert_allclose(
        ssvi_dsigma_dk(k_grid, theta, rho, eta, gamma, T), fd_sig_prime, atol=1e-7
    )
    np.testing.assert_allclose(
        ssvi_d2sigma_dk2(k_grid, theta, rho, eta, gamma, T), fd_sig_pp, atol=1e-5
    )


def test_recovery_synthetic() -> None:
    """Generate IVs from known SSVI params; calibrator recovers the
    identifiable quantities.

    From a single slice (one θ_T) the pair (η, γ) is confounded along the
    curve ``η · θ^{-γ} = const = φ``; only φ is identifiable. The
    calibrator should still recover θ_T, ρ, φ, and produce an IV curve
    that matches the truth at every observation.
    """
    F = 100.0
    K = np.linspace(70.0, 130.0, 31)
    k = np.log(K / F)
    iv_true = ssvi_iv(
        k,
        TRUE_PARAMS["theta_T"],
        TRUE_PARAMS["rho"],
        TRUE_PARAMS["eta"],
        TRUE_PARAMS["gamma"],
        TRUE_T,
    )
    fit = calibrate_ssvi(K, np.asarray(iv_true), F=F, T=TRUE_T, n_starts=5)

    # Identifiable: θ_T (anchored at ATM), ρ (skew), φ = η·θ^{-γ}.
    assert math.isclose(fit.theta_T, TRUE_PARAMS["theta_T"], rel_tol=1e-3)
    assert math.isclose(fit.rho, TRUE_PARAMS["rho"], abs_tol=1e-2)
    phi_true = ssvi_phi(TRUE_PARAMS["theta_T"], TRUE_PARAMS["eta"], TRUE_PARAMS["gamma"])
    phi_fit = ssvi_phi(fit.theta_T, fit.eta, fit.gamma)
    assert math.isclose(phi_fit, phi_true, rel_tol=2e-2)

    # The IV curve must match the truth at every observation strike.
    iv_fit = ssvi_iv(k, fit.theta_T, fit.rho, fit.eta, fit.gamma, TRUE_T)
    np.testing.assert_allclose(iv_fit, iv_true, atol=1e-4)
    assert fit.rmse_iv < 1e-4
    assert fit.butterfly_margin > 0.0


def test_butterfly_bound_enforced() -> None:
    """Calibration of a smile that genuinely violates the G-J bound
    is pushed back into the arb-free interior by the penalty.

    The seed parameters here imply ``butterfly_margin ≪ 0`` — the
    smile contains butterfly arbitrage. The calibrator can never match
    these IVs while staying inside the arb-free interior, so it should
    sit on (or just barely outside) the bound rather than chase the
    arb-violating residuals into the deep interior of the negative
    margin region.
    """
    F = 100.0
    arb_seed = dict(theta_T=0.5, rho=-0.8, eta=4.5, gamma=0.1)
    seed_margin = butterfly_margin(**arb_seed)
    assert seed_margin < -0.1  # the seed is genuinely outside the bound
    K = np.linspace(60.0, 140.0, 41)
    k = np.log(K / F)
    iv = ssvi_iv(k, **arb_seed, T=0.25)
    fit = calibrate_ssvi(K, np.asarray(iv), F=F, T=0.25, n_starts=5)
    # Penalty is finite-λ, so small numerical violations are possible.
    # Anything within ~1 e−3 of the bound is considered "on" the bound.
    assert fit.butterfly_margin >= -1e-3
    # And it must be far better than the arb-violating seed.
    assert fit.butterfly_margin > seed_margin + 0.1


def test_durrleman_g_nonneg() -> None:
    """Durrleman g on the analytic SSVI curve is non-negative on a dense grid.

    SSVI within the G-J Thm 4.2 bound is butterfly-arb-free, so g(k) ≥ 0
    everywhere by construction.
    """
    k_dense = np.linspace(-1.0, 1.0, 401)
    g = durrleman_g_ssvi(
        k_dense,
        TRUE_PARAMS["theta_T"],
        TRUE_PARAMS["rho"],
        TRUE_PARAMS["eta"],
        TRUE_PARAMS["gamma"],
    )
    # Allow a tiny numerical floor — second derivatives in the deep
    # wings can return values like −1e-16.
    assert np.min(g) > -1e-10


def test_iv_curve_helper() -> None:
    """ssvi_iv_curve returns the same IVs as raw ssvi_iv via log-moneyness."""
    F = 100.0
    K_grid = np.linspace(70.0, 130.0, 25)
    params = calibrate_ssvi(
        K_grid,
        ssvi_iv(
            np.log(K_grid / F),
            TRUE_PARAMS["theta_T"],
            TRUE_PARAMS["rho"],
            TRUE_PARAMS["eta"],
            TRUE_PARAMS["gamma"],
            TRUE_T,
        ),
        F=F,
        T=TRUE_T,
    )
    iv_via_curve = ssvi_iv_curve(K_grid, F, TRUE_T, params)
    iv_direct = ssvi_iv(
        np.log(K_grid / F), params.theta_T, params.rho, params.eta, params.gamma, TRUE_T
    )
    np.testing.assert_allclose(iv_via_curve, iv_direct, atol=1e-12)
