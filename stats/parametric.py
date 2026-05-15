"""
Parametric risk metrics via Student-t distribution fitting (copulax).

Fits a Student-t distribution to log returns, samples 10 000 paths,
projects back to simple-return space, and computes parametric
VaR / CVaR / Sharpe / Sortino.

Returns ``None`` if copulax is not installed or fitting fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from stats.core import VaRStats, annualized_return, annualized_volatility

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParametricStats:
    var: VaRStats
    annualized_return: float  # pct
    annualized_volatility: float  # pct
    sharpe: float
    sortino: float


def sample_log_t(fitted_t, n_samples: int, scale: float = 1.0, eps: float = 0.001) -> np.ndarray:
    """Sample from a Student-t distribution with given parameters."""
    log_samples = np.asarray(fitted_t.rvs(n_samples), dtype=np.float64) / scale

    # Clip to eliminate infinite variance from heavy Student-t tails
    percentiles_to_clip = fitted_t.ppf([eps, 1 - eps]) / scale
    log_samples = np.clip(log_samples, percentiles_to_clip[0], percentiles_to_clip[1])

    samples = np.exp(log_samples) - 1
    return samples


def fit_student_t(
    log_rets: np.ndarray,
    rf_daily: float | np.ndarray = 0.0,
    trading_days: int = 252,
    n_samples: int = 10_000,
    scale: float = 100.0,
) -> ParametricStats | None:
    """Fit Student-t to *log_rets*, sample, compute parametric metrics.

    Parameters
    ----------
    log_rets : array of daily log returns (decimal).
    rf_daily : daily risk-free rate (scalar or aligned array).
               When an array, its mean is used for the sampled paths.
    trading_days : annualisation factor.
    n_samples : Monte-Carlo sample size.
    scale : scaling factor for fitting — helps copulax avoid degenerate fits
            on tiny-magnitude data (e.g. daily log returns ~0.02).

    Returns ``None`` if copulax is unavailable or fitting fails.
    """
    log_rets = np.asarray(log_rets, dtype=np.float64)
    if len(log_rets) < 10:
        return None

    # Compute log excess returns: log(1 + r - rf) = log(exp(log_r) - rf)
    # This can produce NaN when rf > exp(log_r), so we clamp the argument.
    gross = np.exp(log_rets) - rf_daily  # 1 + simple_excess
    gross = np.clip(gross, 1e-10, None)  # prevent log(0) or log(negative)
    log_excess_rets = np.log(gross)

    try:
        from copulax.univariate import student_t

        # Scale up by the provided factor before fitting — copulax can produce degenerate
        # fits on tiny-magnitude data (daily log returns ~0.02).
        fitted = student_t.fit(log_rets * scale)
        fitted_excess = student_t.fit(log_excess_rets * scale)

        # Sample, scale back down, project to simple-return space
        simple_samples = sample_log_t(fitted, n_samples, scale=scale)
        excess_samples = sample_log_t(fitted_excess, n_samples, scale=scale)

        # Annualised return / vol (these already return percentages)
        ann_ret = annualized_return(simple_samples, trading_days)
        ann_vol = annualized_volatility(simple_samples, trading_days)

        # Sharpe from the fitted excess-return distribution
        mean_ex = float(np.mean(excess_samples))
        std_ex = float(np.std(excess_samples, ddof=1))
        p_sharpe = (mean_ex / std_ex * np.sqrt(trading_days)) if std_ex > 0 else 0.0

        # Sortino
        downside = np.minimum(excess_samples, 0.0)
        ds_std = float(np.sqrt(np.mean(downside**2)))
        p_sortino = (mean_ex / ds_std * np.sqrt(trading_days)) if ds_std > 0 else 0.0

        # Parametric VaR / CVaR via the fitted distribution's PPF
        # PPF returns scaled values, so divide by scale before exp()
        log_var_95 = float(fitted.ppf(0.05)) / scale
        log_var_99 = float(fitted.ppf(0.01)) / scale
        p_var_95 = (np.exp(log_var_95) - 1) * 100
        p_var_99 = (np.exp(log_var_99) - 1) * 100

        sv95 = np.exp(log_var_95) - 1
        sv99 = np.exp(log_var_99) - 1
        m95 = simple_samples <= sv95
        m99 = simple_samples <= sv99
        p_cvar_95 = float(simple_samples[m95].mean()) * 100 if m95.any() else p_var_95
        p_cvar_99 = float(simple_samples[m99].mean()) * 100 if m99.any() else p_var_99

        return ParametricStats(
            var=VaRStats(
                var_95=round(p_var_95, 4),
                var_99=round(p_var_99, 4),
                cvar_95=round(p_cvar_95, 4),
                cvar_99=round(p_cvar_99, 4),
            ),
            annualized_return=round(ann_ret, 2),
            annualized_volatility=round(ann_vol, 2),
            sharpe=round(float(p_sharpe), 4),
            sortino=round(float(p_sortino), 4),
        )
    except Exception:
        logger.exception("copulax Student-t fitting failed")
        return None
