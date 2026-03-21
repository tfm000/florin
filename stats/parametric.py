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

from stats.core import VaRStats

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParametricStats:
    var: VaRStats
    annualized_return: float   # pct
    annualized_volatility: float  # pct
    sharpe: float
    sortino: float


def fit_student_t(
    log_rets: np.ndarray,
    rf_daily: float | np.ndarray = 0.0,
    trading_days: int = 252,
    n_samples: int = 10_000,
) -> ParametricStats | None:
    """Fit Student-t to *log_rets*, sample, compute parametric metrics.

    Parameters
    ----------
    log_rets : array of daily log returns (decimal).
    rf_daily : daily risk-free rate (scalar or aligned array).
               When an array, its mean is used for the sampled paths.
    trading_days : annualisation factor.
    n_samples : Monte-Carlo sample size.

    Returns ``None`` if copulax is unavailable or fitting fails.
    """
    log_rets = np.asarray(log_rets, dtype=np.float64)
    if len(log_rets) < 10:
        return None

    try:
        from copulax.univariate import student_t

        fitted = student_t.fit(log_rets)

        # Sample and project back to simple-return space
        log_samples = np.asarray(fitted.rvs(n_samples), dtype=np.float64)
        simple_samples = np.exp(log_samples) - 1

        # Annualised return / vol
        ann_ret = float(np.mean(simple_samples)) * trading_days * 100
        ann_vol = float(np.std(simple_samples, ddof=1)) * np.sqrt(trading_days) * 100

        # Use mean of rf_daily for the sampled (iid) paths
        rf_scalar = float(np.mean(rf_daily)) if isinstance(rf_daily, np.ndarray) else float(rf_daily)

        # Sharpe
        excess = simple_samples - rf_scalar
        mean_ex = float(np.mean(excess))
        std_ex = float(np.std(excess, ddof=1))
        p_sharpe = (mean_ex / std_ex * np.sqrt(trading_days)) if std_ex > 0 else 0.0

        # Sortino
        downside = np.minimum(excess, 0.0)
        ds_std = float(np.sqrt(np.mean(downside ** 2)))
        p_sortino = (mean_ex / ds_std * np.sqrt(trading_days)) if ds_std > 0 else 0.0

        # Parametric VaR / CVaR via the fitted distribution's PPF
        log_var_95 = float(fitted.ppf(0.05))
        log_var_99 = float(fitted.ppf(0.01))
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
