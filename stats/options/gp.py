"""
Gaussian-process residual fit with analytic Matérn-5/2 derivative posterior.

The IV-residual between the parametric vol curve (SSVI or SABR) and the
observed market IVs is modelled as a zero-mean Gaussian process in
log-moneyness::

    y_i = σ_i^mkt − σ_parametric(K_i)
    y_i ~ GP(0, k(·, ·)) + ε_i,   ε_i ~ N(0, σ_n²(x_i))

Kernel ``k = ConstantKernel(σ_f²) × Matérn(ν=5/2, ℓ)``. **No
``WhiteKernel``** — heteroscedastic measurement noise is passed through
``alpha = σ_n²(x_i)`` as a per-sample array so it never competes with the
signal length-scale during marginal-likelihood maximisation.

Matérn-5/2 sample paths are ``C²``, so ``r_GP``, ``r_GP'``, ``r_GP''`` are
all well-defined. sklearn's ``GaussianProcessRegressor`` doesn't expose
derivative predictions natively, so this module computes the joint
posterior over ``[r, r', r'']`` at every output grid point analytically
and Cholesky-samples S draws.

Matérn-5/2 derivative kernel (1-D inputs). With ``t = √5·r/ℓ``::

    g(t)     = (1 + t + t²/3) · e^{−t}
    g'(t)    = −e^{−t} · t · (1 + t) / 3
    g''(t)   = −e^{−t} · (1 + t − t²) / 3
    g'''(t)  = −e^{−t} · t · (t − 3) / 3
    g''''(t) =  e^{−t} · (t² − 5t + 3) / 3

    k_r^(n)(r) = σ_f² · g^(n)(t) · (√5 / ℓ)^n

Sign rules at off-diagonal (τ = x − x', r = |τ|)::

    ∂k/∂x        =  sign(τ) · k_r'(r)
    ∂²k/∂x²      =  k_r''(r)
    ∂²k/∂x∂x'    = −k_r''(r)
    ∂³k/∂x²∂x'   = −sign(τ) · k_r'''(r)
    ∂³k/∂x∂x'²   =  sign(τ) · k_r'''(r)
    ∂⁴k/∂x²∂x'²  =  k_r''''(r)

Diagonal (τ = 0)::

    var(f)   = σ_f²
    var(f')  = −k_r''(0) = 5 σ_f² / (3 ℓ²)
    var(f'') =  k_r''''(0) = 25 σ_f² / ℓ⁴

Reference:
    Rasmussen & Williams (2006). *Gaussian Processes for Machine
        Learning*, §9.4 (derivative observations).
"""

from __future__ import annotations

import warnings

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern

from stats.options.types import GPBand

# Defaults and numerical guards.
_JITTER = 1e-10
_DEFAULT_LENGTH_SCALE = 0.2
# Lower bound 0.10 (≈ 10 % moneyness) — anything tighter lets the GP
# fit per-strike bid-ask noise as if it were real smile structure,
# and the second-derivative ``σ_KK`` carries those wiggles straight
# into the RND, producing visibly jagged density curves on
# illiquid-quote expiries. 0.10 is short enough to preserve true
# smile/wing structure (a typical OTM wing is wider than 10 %) but
# long enough to smooth out individual-quote artefacts.
_DEFAULT_LENGTH_SCALE_BOUNDS = (0.10, 1.0)
_DEFAULT_CONSTANT = 1e-3
# Upper bound on σ_f² — the *residual* (market σ − parametric σ)
# should be a few vol-points at worst; capping at 0.01 (i.e. σ_f ≤ 0.1
# in IV space) prevents the GP from "explaining" gross parametric
# misfit by ramping its own variance to 1 IV unit.
_DEFAULT_CONSTANT_BOUNDS = (1e-6, 1e-2)
_DEFAULT_N_RESTARTS = 5


def _matern52_g(t: np.ndarray) -> tuple[np.ndarray, ...]:
    """Return ``(g, g', g'', g''', g'''')`` of the Matérn-5/2 scalar function."""
    et = np.exp(-t)
    g_0 = (1.0 + t + t * t / 3.0) * et
    g_1 = -et * t * (1.0 + t) / 3.0
    g_2 = -et * (1.0 + t - t * t) / 3.0
    g_3 = -et * t * (t - 3.0) / 3.0
    g_4 = et * (t * t - 5.0 * t + 3.0) / 3.0
    return g_0, g_1, g_2, g_3, g_4


def _matern52_kernel_derivs(
    r: np.ndarray, length_scale: float, sigma_f_sq: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Analytic Matérn-5/2 kernel value and its 1st–4th r-derivatives.

    Returns ``(k_r, k_r', k_r'', k_r''', k_r'''')`` of shape ``r.shape``.
    """
    inv_l = 1.0 / length_scale
    t = np.sqrt(5.0) * r * inv_l
    g0, g1, g2, g3, g4 = _matern52_g(t)
    s5_over_l = np.sqrt(5.0) * inv_l
    return (
        sigma_f_sq * g0,
        sigma_f_sq * g1 * s5_over_l,
        sigma_f_sq * g2 * s5_over_l ** 2,
        sigma_f_sq * g3 * s5_over_l ** 3,
        sigma_f_sq * g4 * s5_over_l ** 4,
    )


def _cross_cov_block(
    x_test: np.ndarray, x_train: np.ndarray, length_scale: float, sigma_f_sq: float
) -> np.ndarray:
    """Cross-cov K_xx* shape ``(3·N_test, N_train)`` over outputs [f, f', f''].

    Rows are stacked: first N_test for ``f``, next N_test for ``f'``,
    last N_test for ``f''``.
    """
    tau = x_test[:, None] - x_train[None, :]  # (N_test, N_train)
    r = np.abs(tau)
    sign = np.sign(tau)
    k_r, k_r1, k_r2, _, _ = _matern52_kernel_derivs(r, length_scale, sigma_f_sq)

    n_test = x_test.shape[0]
    n_train = x_train.shape[0]
    out = np.empty((3 * n_test, n_train), dtype=float)
    # Block 0: ∂^0/∂x*^0 k = k_r
    out[:n_test] = k_r
    # Block 1: ∂/∂x* k = sign(τ) · k_r'
    out[n_test : 2 * n_test] = sign * k_r1
    # Block 2: ∂²/∂x*² k = k_r''
    out[2 * n_test :] = k_r2
    return out


def _prior_cov_block(
    x_test: np.ndarray, length_scale: float, sigma_f_sq: float
) -> np.ndarray:
    """Joint prior cov K_** shape ``(3·N_test, 3·N_test)`` over [f, f', f''].

    Uses the sign-rule table at the head of the module. The diagonal of
    block ``(a, a)`` is the variance of ``f^(a)``.
    """
    tau = x_test[:, None] - x_test[None, :]
    r = np.abs(tau)
    sign = np.sign(tau)
    k_r, k_r1, k_r2, k_r3, k_r4 = _matern52_kernel_derivs(
        r, length_scale, sigma_f_sq
    )

    n = x_test.shape[0]
    block = np.zeros((3 * n, 3 * n), dtype=float)

    # (0, 0): k(r)
    block[:n, :n] = k_r
    # (0, 1): ∂/∂x'* k = -sign(τ) · k_r'
    block[:n, n : 2 * n] = -sign * k_r1
    # (1, 0): ∂/∂x* k =  sign(τ) · k_r'
    block[n : 2 * n, :n] = sign * k_r1
    # (1, 1): ∂²/∂x* ∂x'* k = -k_r''
    block[n : 2 * n, n : 2 * n] = -k_r2
    # (0, 2): ∂²/∂x'*² k = k_r''
    block[:n, 2 * n :] = k_r2
    # (2, 0): ∂²/∂x*² k = k_r''
    block[2 * n :, :n] = k_r2
    # (1, 2): ∂³/∂x* ∂x'*² k = sign(τ) · k_r'''
    block[n : 2 * n, 2 * n :] = sign * k_r3
    # (2, 1): ∂³/∂x*² ∂x'* k = -sign(τ) · k_r'''
    block[2 * n :, n : 2 * n] = -sign * k_r3
    # (2, 2): ∂⁴/∂x*² ∂x'*² k = k_r''''
    block[2 * n :, 2 * n :] = k_r4

    # Fix the τ = 0 diagonal where sign(0) = 0 collapsed the odd-deriv
    # entries (the only ones affected by sign). The diagonal of (0, 1),
    # (1, 0), (1, 2), (2, 1) is 0 by symmetry of stationary kernels; the
    # current numerical value is already 0 since k_r1(0) = k_r3(0) = 0.
    return block


def fit_gp_residual(
    strikes: np.ndarray,
    iv_market: np.ndarray,
    F: float,
    T: float,
    parametric_iv_fn,
    parametric_iv_grid: np.ndarray,
    K_grid: np.ndarray,
    *,
    spread: np.ndarray | None = None,
    vega: np.ndarray | None = None,
    n_samples: int = 500,
    seed: int = 0,
    n_restarts_optimizer: int = _DEFAULT_N_RESTARTS,
) -> GPBand:
    """Fit a Matérn-5/2 GP to (market − parametric) IV residuals.

    The hybrid IV is ``σ_h(k) = σ_parametric(k) + r_GP(k)`` where
    ``r_GP`` is the GP posterior. Returns a ``GPBand`` with:

    - ``iv_mean(K_grid)`` = parametric IV + GP posterior mean.
    - ``iv_std(K_grid)``  = posterior std of σ at each grid point.
    - ``iv_samples`` shape ``(n_samples, n_grid)`` — full posterior IV
      sample paths. Note this is the **IV** sample matrix only; for the
      RND we need joint samples of (r, r', r''), produced by
      ``draw_derivative_samples`` below.

    Args:
        strikes:             market strike grid.
        iv_market:           market mid IVs (decimal).
        F:                   parity-implied forward.
        T:                   time to expiry (years) — unused except for
                             provenance / future extensions.
        parametric_iv_fn:    callable mapping ``K -> σ_parametric(K)``;
                             evaluated at the market strikes to form the
                             residual targets.
        parametric_iv_grid:  parametric IV evaluated at ``K_grid``
                             (recomputed by callers since they already
                             have it from the calibrated params).
        K_grid:              output strike grid.
        spread:              optional per-quote bid-ask spread (in
                             price units). When combined with ``vega``,
                             yields heteroscedastic IV-noise:
                             ``σ_n = spread / (2·vega)``.
        vega:                option Black-76 vega at each market strike.
        n_samples:           number of posterior IV draws.
        seed:                RNG seed.
        n_restarts_optimizer: marginal-likelihood restarts.
    """
    K = np.asarray(strikes, dtype=float)
    iv = np.asarray(iv_market, dtype=float)
    valid = np.isfinite(iv) & (iv > 0.0)
    K, iv = K[valid], iv[valid]

    n_obs = len(K)
    parametric_grid = np.asarray(parametric_iv_grid, dtype=float)
    K_out = np.asarray(K_grid, dtype=float)

    if n_obs < 8:
        # Too few observations to learn length-scale + signal-variance
        # reliably; degrade to a flat residual std and propagate the
        # parametric curve only.
        warnings.warn(
            f"Only {n_obs} valid IV observations; GP would overfit. "
            f"Returning a flat-residual band.",
            stacklevel=2,
        )
        resid_std = (
            float(np.std(iv - np.asarray(parametric_iv_fn(K)), ddof=1))
            if n_obs >= 2
            else 0.02
        )
        rng = np.random.default_rng(seed)
        samples = parametric_grid[None, :] + rng.normal(
            0.0, resid_std, size=(n_samples, K_out.size)
        )
        samples = np.maximum(samples, 1e-4)
        return GPBand(
            K_grid=K_out,
            iv_mean=parametric_grid,
            iv_std=np.full_like(K_out, resid_std),
            iv_samples=samples,
            kernel_repr="degenerate_flat_residual",
        )

    # Heteroscedastic noise variance per quote.
    if spread is not None and vega is not None:
        sp = np.asarray(spread, dtype=float)[valid]
        vg = np.asarray(vega, dtype=float)[valid]
        sigma_n = np.maximum(sp / 2.0, 1e-4) / np.maximum(vg, 1e-6)
        alpha_arr = np.clip(sigma_n * sigma_n, 1e-8, 1e-2)
    else:
        alpha_arr = np.full(n_obs, 1e-6)

    x_train = np.log(K / F).reshape(-1, 1)
    y_train = iv - np.asarray(parametric_iv_fn(K))

    kernel = ConstantKernel(
        _DEFAULT_CONSTANT, constant_value_bounds=_DEFAULT_CONSTANT_BOUNDS
    ) * Matern(
        length_scale=_DEFAULT_LENGTH_SCALE,
        length_scale_bounds=_DEFAULT_LENGTH_SCALE_BOUNDS,
        nu=2.5,
    )

    gpr = GaussianProcessRegressor(
        kernel=kernel,
        alpha=alpha_arr,
        n_restarts_optimizer=n_restarts_optimizer,
        normalize_y=False,
        random_state=seed,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gpr.fit(x_train, y_train)

    x_pred = np.log(K_out / F).reshape(-1, 1)
    y_mean, y_std = gpr.predict(x_pred, return_std=True)

    samples_resid = gpr.sample_y(x_pred, n_samples=n_samples, random_state=seed).T
    samples = parametric_grid[None, :] + samples_resid
    samples = np.maximum(samples, 1e-4)

    iv_mean = np.maximum(parametric_grid + y_mean, 1e-4)

    return GPBand(
        K_grid=K_out,
        iv_mean=iv_mean,
        iv_std=y_std,
        iv_samples=samples,
        kernel_repr=str(gpr.kernel_),
    )


def _extract_kernel_hyperparams(gpr: GaussianProcessRegressor) -> tuple[float, float]:
    """Pull (length_scale, σ_f²) out of a fitted Constant * Matérn kernel."""
    k = gpr.kernel_
    # The product structure: ConstantKernel × Matern. sklearn stores it
    # as k1 (Constant) * k2 (Matern) when built as Constant * Matern.
    if hasattr(k, "k1") and hasattr(k, "k2"):
        const = k.k1
        matern = k.k2
    else:
        # Unexpected — fall back to defaults.
        return _DEFAULT_LENGTH_SCALE, _DEFAULT_CONSTANT
    sigma_f_sq = float(const.constant_value)
    length_scale = float(matern.length_scale)
    return length_scale, sigma_f_sq


def draw_derivative_samples(
    gpr: GaussianProcessRegressor,
    x_train: np.ndarray,
    y_train: np.ndarray,
    alpha_arr: np.ndarray,
    x_test: np.ndarray,
    n_samples: int = 500,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Joint posterior samples of (r, r', r'') at ``x_test``.

    Returns three ``(n_samples, n_grid)`` arrays. Computed by:

    1. Building the analytic ``(3 N_grid, N_train)`` cross-covariance.
    2. Solving ``α = (K_train + diag(σ_n²))⁻¹ · y`` (sklearn already
       has this in ``gpr.alpha_`` for ``f``-only outputs; we reuse it).
    3. Computing posterior mean ``μ = K_xx* · α``.
    4. Computing posterior cov  ``Σ = K_** − K_xx* · K_xx_inv · K_xx*ᵀ``
       (Cholesky-solve via ``gpr.L_``).
    5. Cholesky-sampling ``μ + L · z`` with ``z ~ N(0, I_{3N})``.

    The 3·N output covariance matrix is then chunked into the three
    output blocks; the splits below match the row layout in
    ``_cross_cov_block``.
    """
    length_scale, sigma_f_sq = _extract_kernel_hyperparams(gpr)
    n_test = x_test.shape[0]

    # K_** prior over joint outputs at the test grid.
    K_pp = _prior_cov_block(x_test.ravel(), length_scale, sigma_f_sq)
    # K_xx* cross-cov between joint test and train.
    K_xp = _cross_cov_block(
        x_test.ravel(), x_train.ravel(), length_scale, sigma_f_sq
    )

    # Posterior mean = K_xp · α  where α = (K_train + diag(σ_n²))⁻¹ · y.
    # sklearn stores the Cholesky factor L_ of (K + Σ_n); reuse it.
    L = gpr.L_  # lower-triangular Cholesky of (K + Σ_n)
    # alpha_train = L⁻ᵀ L⁻¹ y  ≡  gpr.alpha_
    alpha_train = gpr.alpha_  # shape (n_train,) — sklearn pre-computes
    mu_joint = K_xp @ alpha_train

    # Posterior cov:  Σ = K_** − K_xp · (K + Σ_n)⁻¹ · K_xpᵀ
    # via two triangular solves.  v = L⁻¹·K_xpᵀ  →  K_xp(K+Σ_n)⁻¹K_xpᵀ = vᵀ·v
    from scipy.linalg import solve_triangular

    v = solve_triangular(L, K_xp.T, lower=True)
    cov_joint = K_pp - v.T @ v
    # Symmetrise to suppress floating point drift.
    cov_joint = 0.5 * (cov_joint + cov_joint.T)
    # Jitter for numerical PD.
    cov_joint = cov_joint + _JITTER * np.eye(3 * n_test)

    # Cholesky sample.
    try:
        L_cov = np.linalg.cholesky(cov_joint)
    except np.linalg.LinAlgError:
        # Fall back to larger jitter.
        cov_joint = cov_joint + 1e-6 * np.eye(3 * n_test)
        L_cov = np.linalg.cholesky(cov_joint)

    rng = np.random.default_rng(seed)
    z = rng.standard_normal((3 * n_test, n_samples))
    samples_flat = mu_joint[:, None] + L_cov @ z  # (3·N, n_samples)
    samples = samples_flat.T  # (n_samples, 3·N)

    r_samples = samples[:, :n_test]
    r_prime_samples = samples[:, n_test : 2 * n_test]
    r_double_samples = samples[:, 2 * n_test :]
    return r_samples, r_prime_samples, r_double_samples


def fit_gp_residual_with_derivatives(
    strikes: np.ndarray,
    iv_market: np.ndarray,
    F: float,
    T: float,
    parametric_iv_fn,
    parametric_iv_grid: np.ndarray,
    K_grid: np.ndarray,
    *,
    spread: np.ndarray | None = None,
    vega: np.ndarray | None = None,
    n_samples: int = 500,
    seed: int = 0,
    n_restarts_optimizer: int = _DEFAULT_N_RESTARTS,
) -> tuple[GPBand, np.ndarray, np.ndarray, np.ndarray]:
    """Same as ``fit_gp_residual``, but also returns joint (r, r', r'')
    posterior samples on ``K_grid``.

    Returns:
        (band, r_samples, r_prime_samples, r_double_samples)
        where each ``*_samples`` array has shape ``(n_samples, n_grid)``.
    """
    K = np.asarray(strikes, dtype=float)
    iv = np.asarray(iv_market, dtype=float)
    valid = np.isfinite(iv) & (iv > 0.0)
    K, iv = K[valid], iv[valid]
    n_obs = len(K)
    parametric_grid = np.asarray(parametric_iv_grid, dtype=float)
    K_out = np.asarray(K_grid, dtype=float)

    if n_obs < 8:
        band = fit_gp_residual(
            strikes,
            iv_market,
            F,
            T,
            parametric_iv_fn,
            parametric_iv_grid,
            K_grid,
            spread=spread,
            vega=vega,
            n_samples=n_samples,
            seed=seed,
            n_restarts_optimizer=n_restarts_optimizer,
        )
        # Without enough data to fit, derivative samples are also flat.
        zeros = np.zeros((n_samples, K_out.size))
        return band, zeros, zeros, zeros

    if spread is not None and vega is not None:
        sp = np.asarray(spread, dtype=float)[valid]
        vg = np.asarray(vega, dtype=float)[valid]
        sigma_n = np.maximum(sp / 2.0, 1e-4) / np.maximum(vg, 1e-6)
        alpha_arr = np.clip(sigma_n * sigma_n, 1e-8, 1e-2)
    else:
        alpha_arr = np.full(n_obs, 1e-6)

    x_train = np.log(K / F).reshape(-1, 1)
    y_train = iv - np.asarray(parametric_iv_fn(K))

    kernel = ConstantKernel(
        _DEFAULT_CONSTANT, constant_value_bounds=_DEFAULT_CONSTANT_BOUNDS
    ) * Matern(
        length_scale=_DEFAULT_LENGTH_SCALE,
        length_scale_bounds=_DEFAULT_LENGTH_SCALE_BOUNDS,
        nu=2.5,
    )
    gpr = GaussianProcessRegressor(
        kernel=kernel,
        alpha=alpha_arr,
        n_restarts_optimizer=n_restarts_optimizer,
        normalize_y=False,
        random_state=seed,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gpr.fit(x_train, y_train)

    x_pred = np.log(K_out / F).reshape(-1, 1)
    y_mean, y_std = gpr.predict(x_pred, return_std=True)

    iv_mean = np.maximum(parametric_grid + y_mean, 1e-4)

    # Joint (r, r', r'') samples — IV samples come from the r block plus
    # the parametric grid; r' and r'' are the second and third blocks.
    r_samples, rp_samples, rpp_samples = draw_derivative_samples(
        gpr,
        x_train,
        y_train,
        alpha_arr,
        x_pred,
        n_samples=n_samples,
        seed=seed,
    )
    iv_samples = parametric_grid[None, :] + r_samples
    iv_samples = np.maximum(iv_samples, 1e-4)

    band = GPBand(
        K_grid=K_out,
        iv_mean=iv_mean,
        iv_std=y_std,
        iv_samples=iv_samples,
        kernel_repr=str(gpr.kernel_),
    )
    return band, r_samples, rp_samples, rpp_samples
