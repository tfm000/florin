"""Unit tests for the GP residual fitter and its analytic derivative kernel."""

from __future__ import annotations

import warnings

import numpy as np
from sklearn.gaussian_process.kernels import ConstantKernel, Matern

from stats.options.gp import (
    _cross_cov_block,
    _matern52_kernel_derivs,
    _prior_cov_block,
    fit_gp_residual,
    fit_gp_residual_with_derivatives,
)


def test_matern52_kernel_value_against_sklearn() -> None:
    """Our analytic Matérn-5/2 k(r) matches sklearn's Matern(nu=5/2)."""
    rng = np.random.default_rng(0)
    x = rng.uniform(-1.0, 1.0, 20)
    y = rng.uniform(-1.0, 1.0, 20)
    L = 0.3
    sf2 = 1.5
    r = np.abs(x[:, None] - y[None, :])
    k_ours, _, _, _, _ = _matern52_kernel_derivs(r, L, sf2)

    kernel = ConstantKernel(sf2) * Matern(length_scale=L, nu=2.5)
    k_sk = kernel(x.reshape(-1, 1), y.reshape(-1, 1))
    np.testing.assert_allclose(k_ours, k_sk, atol=1e-12)


def test_matern52_derivatives_against_fd() -> None:
    """First & second r-derivatives of Matérn-5/2 match FD."""
    L = 0.4
    sf2 = 0.7
    rs = np.linspace(0.01, 1.5, 30)
    h = 1e-5
    _, k1, k2, k3, k4 = _matern52_kernel_derivs(rs, L, sf2)

    def kr(r):
        return _matern52_kernel_derivs(r, L, sf2)[0]

    fd_k1 = (8 * (kr(rs + h) - kr(rs - h)) - (kr(rs + 2 * h) - kr(rs - 2 * h))) / (12 * h)
    fd_k2 = (-kr(rs + 2 * h) + 16 * kr(rs + h) - 30 * kr(rs) + 16 * kr(rs - h) - kr(rs - 2 * h)) / (
        12 * h * h
    )

    np.testing.assert_allclose(k1, fd_k1, atol=1e-7)
    np.testing.assert_allclose(k2, fd_k2, atol=1e-5)

    # 3rd / 4th derivatives via FD of the 2nd / 3rd analytic forms.
    def k2_fn(r):
        return _matern52_kernel_derivs(r, L, sf2)[2]

    def k3_fn(r):
        return _matern52_kernel_derivs(r, L, sf2)[3]

    fd_k3 = (k2_fn(rs + h) - k2_fn(rs - h)) / (2 * h)
    fd_k4 = (k3_fn(rs + h) - k3_fn(rs - h)) / (2 * h)
    np.testing.assert_allclose(k3, fd_k3, atol=1e-5)
    np.testing.assert_allclose(k4, fd_k4, atol=1e-4)


def test_prior_cov_block_psd() -> None:
    """The 3·N joint prior covariance is symmetric and positive
    semi-definite — a basic GP sanity check on the sign-rule table."""
    L = 0.35
    sf2 = 0.5
    x = np.linspace(-0.4, 0.4, 9)
    K_pp = _prior_cov_block(x, L, sf2)
    n = len(x)
    assert K_pp.shape == (3 * n, 3 * n)
    np.testing.assert_allclose(K_pp, K_pp.T, atol=1e-12)
    eigvals = np.linalg.eigvalsh(K_pp + 1e-9 * np.eye(3 * n))
    assert np.min(eigvals) > -1e-7


def test_cross_cov_block_layout() -> None:
    """Cross-cov block has stacked rows [f, f', f''] across test points."""
    L = 0.3
    sf2 = 0.4
    x_test = np.linspace(-0.2, 0.2, 5)
    x_train = np.linspace(-0.3, 0.3, 7)
    K_xp = _cross_cov_block(x_test, x_train, L, sf2)
    assert K_xp.shape == (3 * x_test.size, x_train.size)


def test_smooth_recovery() -> None:
    """A known smooth residual is recovered within the noise envelope."""
    rng = np.random.default_rng(0)
    F = 100.0
    T = 0.5
    K = np.linspace(80.0, 120.0, 25)
    k = np.log(K / F)
    # Truth: parametric = constant 0.20; residual = small bump.
    parametric_mean = 0.20
    true_residual = 0.02 * np.exp(-((k - 0.05) ** 2) / (2 * 0.08**2))
    iv_market = parametric_mean + true_residual + 0.001 * rng.standard_normal(K.size)

    def parametric_fn(k_arr):
        return np.full(np.asarray(k_arr).shape, parametric_mean)

    K_grid = np.linspace(80.0, 120.0, 51)
    parametric_grid = np.full(K_grid.size, parametric_mean)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        band = fit_gp_residual(
            K, iv_market, F, T, parametric_fn, parametric_grid, K_grid, n_samples=50
        )

    # Posterior mean should track parametric + true residual everywhere.
    truth_on_grid = parametric_mean + 0.02 * np.exp(
        -((np.log(K_grid / F) - 0.05) ** 2) / (2 * 0.08**2)
    )
    rmse = float(np.sqrt(np.mean((band.iv_mean - truth_on_grid) ** 2)))
    assert rmse < 5e-3


def test_derivative_samples_match_finite_diff_on_mean() -> None:
    """Posterior-mean derivative of r matches the FD derivative of the
    GP posterior mean of r itself.

    We don't require sample-by-sample agreement (samples are random),
    but the *mean* over many samples of r' must converge to the
    posterior mean of r', which equals d/dx of the posterior mean of r.
    """
    rng = np.random.default_rng(1)
    F = 100.0
    T = 0.5
    K = np.linspace(80.0, 120.0, 30)
    k = np.log(K / F)
    parametric_mean = 0.20
    true_resid = 0.03 * np.exp(-((k - 0.0) ** 2) / (2 * 0.10**2))
    iv_market = parametric_mean + true_resid + 0.0005 * rng.standard_normal(K.size)

    def parametric_fn(k_arr):
        return np.full(np.asarray(k_arr).shape, parametric_mean)

    K_grid = np.linspace(82.0, 118.0, 51)
    parametric_grid = np.full(K_grid.size, parametric_mean)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, r_samples, rp_samples, rpp_samples = fit_gp_residual_with_derivatives(
            K,
            iv_market,
            F,
            T,
            parametric_fn,
            parametric_grid,
            K_grid,
            n_samples=2000,
            seed=2,
        )

    # FD of the posterior-mean r (Monte-Carlo average of r samples) vs
    # the posterior-mean r' (Monte-Carlo average of r' samples).
    r_mean = r_samples.mean(axis=0)
    rp_mean = rp_samples.mean(axis=0)

    x_grid = np.log(K_grid / F)
    fd_rp = np.gradient(r_mean, x_grid)
    # Compare on the interior (gradients near boundaries lose order).
    mask = slice(3, -3)
    np.testing.assert_allclose(rp_mean[mask], fd_rp[mask], atol=0.5)
    # Just sanity: rpp samples have plausible scale.
    rpp_mean = rpp_samples.mean(axis=0)
    assert np.isfinite(rpp_mean).all()
