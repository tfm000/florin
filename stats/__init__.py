"""
Canonical financial statistics — single source of truth.

All stat functions live here. Route handlers, providers, and frontend
should call into this module rather than computing inline.
"""

from stats.core import (
    DistributionStats,
    DrawdownStats,
    FullStats,
    ReturnStats,
    RiskAdjustedStats,
    VaRStats,
    annualized_return,
    annualized_volatility,
    compute_full_stats,
    compute_return_stats,
    compute_risk_adjusted,
    distribution_stats,
    historical_cvar,
    historical_var,
    log_returns,
    max_drawdown,
    max_drawdown_from_log_returns,
    period_return,
    sharpe_ratio,
    simple_pct_change,
    simple_returns,
    sortino_ratio,
    total_return,
    var_cvar,
)
from stats.parametric import ParametricStats, fit_student_t
from stats.regime import fit_markov_regimes

__all__ = [
    "ReturnStats",
    "RiskAdjustedStats",
    "VaRStats",
    "DrawdownStats",
    "DistributionStats",
    "FullStats",
    "ParametricStats",
    "simple_returns",
    "log_returns",
    "annualized_return",
    "annualized_volatility",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "max_drawdown_from_log_returns",
    "historical_var",
    "historical_cvar",
    "var_cvar",
    "distribution_stats",
    "simple_pct_change",
    "total_return",
    "period_return",
    "compute_return_stats",
    "compute_risk_adjusted",
    "compute_full_stats",
    "fit_student_t",
    "fit_markov_regimes",
]
