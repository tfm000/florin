"""
Canonical financial statistics — pure numpy, no I/O.

All functions operate on numpy arrays of returns in DECIMAL form
(e.g., 0.02 means +2%). Output values labelled "pct" are percentages.

Standard conventions:
- Sample standard deviation (ddof=1) everywhere.
- rf_daily accepts a scalar OR an array aligned to returns;
  numpy broadcasting handles both transparently.  The caller is
  responsible for converting from annual % using the correct day
  count convention (ACT/360 or ACT/365) — see ``stats.risk_free``.
- 252 trading days per year for annualisation (configurable).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReturnStats:
    mean_daily: float
    annualized_return: float      # pct
    annualized_volatility: float  # pct
    trading_days: int


@dataclass(frozen=True)
class RiskAdjustedStats:
    sharpe: float
    sortino: float


@dataclass(frozen=True)
class VaRStats:
    var_95: float   # pct
    var_99: float   # pct
    cvar_95: float  # pct
    cvar_99: float  # pct


@dataclass(frozen=True)
class DrawdownStats:
    max_drawdown_pct: float  # positive number (e.g. 15.3 means −15.3%)
    peak_index: int
    trough_index: int


@dataclass(frozen=True)
class DistributionStats:
    mean: float           # pct (daily)
    std_dev: float        # pct (daily)
    skewness: float
    excess_kurtosis: float


@dataclass(frozen=True)
class FullStats:
    returns: ReturnStats
    risk_adjusted: RiskAdjustedStats
    var: VaRStats
    drawdown: DrawdownStats
    distribution: DistributionStats


# ---------------------------------------------------------------------------
# Return computation
# ---------------------------------------------------------------------------

def simple_returns(prices: np.ndarray) -> np.ndarray:
    """Simple (arithmetic) returns from a price series.

    Returns array of length ``len(prices) - 1`` in decimal form.
    """
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < 2:
        return np.array([], dtype=np.float64)
    return np.diff(prices) / prices[:-1]


def log_returns(prices: np.ndarray) -> np.ndarray:
    """Log returns from a price series.

    Returns array of length ``len(prices) - 1`` in decimal form.
    """
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < 2:
        return np.array([], dtype=np.float64)
    return np.log(prices[1:] / prices[:-1])


# ---------------------------------------------------------------------------
# Core statistics
# ---------------------------------------------------------------------------

def annualized_return(returns: np.ndarray, trading_days: int = 252) -> float:
    """Annualized return in percentage."""
    if len(returns) == 0:
        return 0.0
    return float((1 + np.mean(returns)) ** trading_days - 1) * 100


def annualized_volatility(returns: np.ndarray, trading_days: int = 252) -> float:
    """Annualized volatility in percentage (sample std, ddof=1)."""
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns, ddof=1) * np.sqrt(trading_days) * 100)


def sharpe_ratio(
    returns: np.ndarray,
    rf_daily: float | np.ndarray = 0.0,
    trading_days: int = 252,
) -> float:
    """Annualized Sharpe ratio.

    ``rf_daily`` is the daily risk-free rate in decimal form.
    Can be a scalar (constant rate) or an array aligned to *returns*.
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - rf_daily
    std = float(np.std(excess, ddof=1))
    if std <= 0:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(trading_days))


def sortino_ratio(
    returns: np.ndarray,
    rf_daily: float | np.ndarray = 0.0,
    trading_days: int = 252,
) -> float:
    """Annualized Sortino ratio.

    Downside deviation uses excess returns below zero.
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - rf_daily
    mean_excess = float(np.mean(excess))
    downside = np.minimum(excess, 0.0)
    downside_std = float(np.sqrt(np.mean(downside ** 2)))
    if downside_std <= 0:
        return 0.0
    return float(mean_excess / downside_std * np.sqrt(trading_days))


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

def max_drawdown(prices: np.ndarray) -> DrawdownStats:
    """Maximum drawdown from a price series (running-peak method)."""
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < 2:
        return DrawdownStats(max_drawdown_pct=0.0, peak_index=0, trough_index=0)

    peaks = np.maximum.accumulate(prices)
    drawdowns = (peaks - prices) / peaks

    trough_idx = int(np.argmax(drawdowns))
    peak_idx = int(np.argmax(prices[: trough_idx + 1])) if trough_idx > 0 else 0
    dd_pct = float(drawdowns[trough_idx]) * 100

    return DrawdownStats(
        max_drawdown_pct=dd_pct,
        peak_index=peak_idx,
        trough_index=trough_idx,
    )


def max_drawdown_from_log_returns(log_rets: np.ndarray) -> DrawdownStats:
    log_rets = np.asarray(log_rets, dtype=np.float64)
    if len(log_rets) == 0:
        return DrawdownStats(max_drawdown_pct=0.0, peak_index=0, trough_index=0)

    cum = np.concatenate(([0.0], np.cumsum(log_rets)))  # length N+1
    peaks = np.maximum.accumulate(cum)
    dd = cum - peaks

    trough_idx = int(np.argmin(dd))
    peak_idx = int(np.argmax(cum[: trough_idx + 1]))
    dd_pct = float((1 - np.exp(dd[trough_idx])) * 100)

    # Shift indices back to align with the original log_rets array
    # Index 0 in cum corresponds to "before any returns"
    peak_idx = max(peak_idx - 1, 0)
    trough_idx = max(trough_idx - 1, 0)

    return DrawdownStats(
        max_drawdown_pct=dd_pct,
        peak_index=peak_idx,
        trough_index=trough_idx,
    )


# ---------------------------------------------------------------------------
# Value-at-Risk
# ---------------------------------------------------------------------------

def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Historical VaR at given confidence level, as percentage."""
    if len(returns) == 0:
        return 0.0
    pctile = (1 - confidence) * 100  # e.g. 5 for 95% confidence
    return float(np.percentile(returns, pctile)) * 100


def historical_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Historical CVaR (Expected Shortfall) at given confidence, as pct."""
    if len(returns) == 0:
        return 0.0
    pctile = (1 - confidence) * 100
    threshold = np.percentile(returns, pctile)
    tail = returns[returns <= threshold]
    if len(tail) == 0:
        return float(threshold) * 100
    return float(np.mean(tail)) * 100


def var_cvar(returns: np.ndarray) -> VaRStats:
    """Compute VaR and CVaR at 95% and 99% confidence levels."""
    return VaRStats(
        var_95=historical_var(returns, 0.95),
        var_99=historical_var(returns, 0.99),
        cvar_95=historical_cvar(returns, 0.95),
        cvar_99=historical_cvar(returns, 0.99),
    )


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

def distribution_stats(returns_pct: np.ndarray) -> DistributionStats:
    """Mean, std (sample, ddof=1), skewness, excess kurtosis.

    Input must be in PERCENTAGE space (returns × 100).
    """
    if len(returns_pct) < 2:
        return DistributionStats(mean=0.0, std_dev=0.0, skewness=0.0, excess_kurtosis=0.0)

    n = len(returns_pct)
    mean = float(np.mean(returns_pct))
    std = float(np.std(returns_pct, ddof=1))

    if std <= 0:
        return DistributionStats(mean=mean, std_dev=0.0, skewness=0.0, excess_kurtosis=0.0)

    z = (returns_pct - mean) / std
    # Adjusted Fisher-Pearson skewness (sample)
    skew = float(n / ((n - 1) * (n - 2)) * np.sum(z ** 3)) if n > 2 else 0.0
    # Excess kurtosis (sample)
    if n > 3:
        kurt = float(
            n * (n + 1) / ((n - 1) * (n - 2) * (n - 3)) * np.sum(z ** 4)
            - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
        )
    else:
        kurt = 0.0

    return DistributionStats(mean=mean, std_dev=std, skewness=skew, excess_kurtosis=kurt)


# ---------------------------------------------------------------------------
# Period return
# ---------------------------------------------------------------------------

def period_return(prices: np.ndarray, n_days: int) -> float | None:
    """Return over the last *n_days* as a percentage.

    Returns ``None`` if not enough data.
    """
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < n_days or n_days < 1:
        return None
    return float((prices[-1] - prices[-n_days]) / prices[-n_days] * 100)


# ---------------------------------------------------------------------------
# Composite helpers
# ---------------------------------------------------------------------------

def compute_return_stats(
    returns: np.ndarray,
    trading_days: int = 252,
) -> ReturnStats:
    """Core return statistics from an array of decimal returns."""
    returns = np.asarray(returns, dtype=np.float64)
    return ReturnStats(
        mean_daily=float(np.mean(returns)) if len(returns) > 0 else 0.0,
        annualized_return=annualized_return(returns, trading_days),
        annualized_volatility=annualized_volatility(returns, trading_days),
        trading_days=len(returns),
    )


def compute_risk_adjusted(
    returns: np.ndarray,
    rf_daily: float | np.ndarray = 0.0,
    trading_days: int = 252,
) -> RiskAdjustedStats:
    """Sharpe and Sortino from returns + risk-free rate."""
    returns = np.asarray(returns, dtype=np.float64)
    return RiskAdjustedStats(
        sharpe=sharpe_ratio(returns, rf_daily, trading_days),
        sortino=sortino_ratio(returns, rf_daily, trading_days),
    )


def compute_full_stats(
    prices: np.ndarray,
    rf_daily: float | np.ndarray = 0.0,
    trading_days: int = 252,
) -> FullStats:
    """All-in-one: takes prices, computes everything."""
    prices = np.asarray(prices, dtype=np.float64)
    rets = simple_returns(prices)
    rets_pct = rets * 100

    return FullStats(
        returns=compute_return_stats(rets, trading_days),
        risk_adjusted=compute_risk_adjusted(rets, rf_daily, trading_days),
        var=var_cvar(rets),
        drawdown=max_drawdown(prices),
        distribution=distribution_stats(rets_pct),
    )
