"""
Canonical financial statistics — single source of truth.

All stat functions live here. Route handlers, providers, and frontend
should call into this module rather than computing inline.
"""

from stats.core import (
    ReturnStats,
    RiskAdjustedStats,
    VaRStats,
    DrawdownStats,
    DistributionStats,
    FullStats,
    simple_returns,
    log_returns,
    annualized_return,
    annualized_volatility,
    sharpe_ratio,
    sortino_ratio,
    max_drawdown,
    max_drawdown_from_log_returns,
    historical_var,
    historical_cvar,
    var_cvar,
    distribution_stats,
    period_return,
    compute_return_stats,
    compute_risk_adjusted,
    compute_full_stats,
)
from stats.parametric import ParametricStats, fit_student_t

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
    "period_return",
    "compute_return_stats",
    "compute_risk_adjusted",
    "compute_full_stats",
    "fit_student_t",
]
