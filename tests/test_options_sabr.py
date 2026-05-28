"""Unit tests for the SABR fitter (Hagan 2002 lognormal)."""

from __future__ import annotations

import math

import numpy as np

from stats.options.sabr import calibrate_sabr, hagan_lognormal_iv, sabr_iv_curve


def test_atm_limit() -> None:
    """At K = F the z/x(z) factor is exactly 1; formula collapses to the
    ATM cubic."""
    F = 100.0
    T = 0.5
    alpha = 0.20
    beta = 1.0
    rho = -0.3
    nu = 0.4

    # Direct ATM formula.
    FK_beta = F ** (1.0 - beta)
    expected_atm = (alpha / FK_beta) * (
        1.0
        + (
            ((1.0 - beta) ** 2 / 24.0) * alpha**2 / FK_beta**2
            + 0.25 * rho * beta * nu * alpha / FK_beta
            + ((2.0 - 3.0 * rho**2) / 24.0) * nu**2
        )
        * T
    )

    got = float(hagan_lognormal_iv(F, F, T, alpha, beta, rho, nu))
    assert math.isclose(got, expected_atm, rel_tol=1e-10)


def test_atm_continuity() -> None:
    """σ_B is continuous through K = F (no ATM jump)."""
    F = 100.0
    T = 0.5
    alpha, beta, rho, nu = 0.20, 1.0, -0.3, 0.4
    Ks = F + np.array([-1e-3, 0.0, 1e-3])
    sigmas = hagan_lognormal_iv(F, Ks, T, alpha, beta, rho, nu)
    assert math.isclose(float(sigmas[0]), float(sigmas[1]), rel_tol=1e-5)
    assert math.isclose(float(sigmas[1]), float(sigmas[2]), rel_tol=1e-5)


def _generate_smile(F: float, T: float, params: dict, K: np.ndarray) -> np.ndarray:
    return hagan_lognormal_iv(F, K, T, **params)


def test_recovery_beta1() -> None:
    """Synthetic β=1 SABR smile is recovered within IV tolerance 5e-3."""
    F = 100.0
    T = 0.5
    true = dict(alpha=0.22, beta=1.0, rho=-0.5, nu=0.6)
    K = np.linspace(70.0, 130.0, 31)
    iv = _generate_smile(F, T, true, K)
    fit = calibrate_sabr(K, iv, F, T, beta=true["beta"], n_starts=5)
    assert math.isclose(fit.beta, true["beta"], abs_tol=1e-12)
    # α, ρ, ν all recover tightly.
    assert math.isclose(fit.alpha, true["alpha"], abs_tol=5e-3)
    assert math.isclose(fit.rho, true["rho"], abs_tol=5e-3)
    assert math.isclose(fit.nu, true["nu"], abs_tol=5e-3)
    assert fit.rmse_iv < 1e-4


def test_recovery_beta_half() -> None:
    """Synthetic β=0.5 SABR smile is recovered — proves the β
    parameterisation is wired through (the fitter is not silently
    pinning β=1)."""
    F = 100.0
    T = 0.5
    true = dict(alpha=0.20 * F**0.5, beta=0.5, rho=-0.4, nu=0.5)
    K = np.linspace(70.0, 130.0, 31)
    iv = _generate_smile(F, T, true, K)
    fit = calibrate_sabr(K, iv, F, T, beta=true["beta"], n_starts=5)
    assert math.isclose(fit.beta, 0.5, abs_tol=1e-12)
    # α scale shifts with β so use a slightly looser tolerance.
    assert math.isclose(fit.alpha, true["alpha"], rel_tol=2e-2)
    assert math.isclose(fit.rho, true["rho"], abs_tol=1e-2)
    assert math.isclose(fit.nu, true["nu"], abs_tol=1e-2)
    assert fit.rmse_iv < 1e-4


def test_iv_curve_helper() -> None:
    """sabr_iv_curve evaluates the calibrated curve on an arbitrary K grid."""
    F = 100.0
    T = 0.5
    true = dict(alpha=0.22, beta=1.0, rho=-0.5, nu=0.6)
    K = np.linspace(70.0, 130.0, 31)
    iv = _generate_smile(F, T, true, K)
    fit = calibrate_sabr(K, iv, F, T, beta=true["beta"])

    K_grid = np.linspace(80.0, 120.0, 17)
    iv_curve = sabr_iv_curve(K_grid, F, T, fit)
    iv_direct = hagan_lognormal_iv(F, K_grid, T, fit.alpha, fit.beta, fit.rho, fit.nu)
    np.testing.assert_allclose(iv_curve, iv_direct, atol=1e-12)


def test_param_covariance_shape() -> None:
    """4×4 covariance returned; β row/col are zero (β is fixed)."""
    F = 100.0
    T = 0.5
    true = dict(alpha=0.22, beta=1.0, rho=-0.5, nu=0.6)
    K = np.linspace(70.0, 130.0, 31)
    iv = _generate_smile(F, T, true, K)
    fit = calibrate_sabr(K, iv, F, T, beta=true["beta"])
    assert fit.param_cov.shape == (4, 4)
    # β is at index 1; both row 1 and column 1 must be all-zero.
    np.testing.assert_allclose(fit.param_cov[1, :], 0.0, atol=1e-12)
    np.testing.assert_allclose(fit.param_cov[:, 1], 0.0, atol=1e-12)
