"""
Type definitions for the options / volatility-surface pipeline.

All dataclasses are designed to be immutable wherever the contents are
primitive scalars; classes that hold ``numpy`` arrays use plain
``@dataclass`` (which prevents accidental reassignment of the field but
leaves the array contents mutable, as numpy requires).

Conventions throughout this package:
- ``sigma`` (implied vol) is stored in decimal form: ``0.20`` means 20 %.
- ``T`` is in years (typically ACT/365 for equity index options).
- ``F`` is the parity-implied forward; ``D = e^{-rT}`` the matching
  discount factor; ``r`` the corresponding annualised zero rate.
- All log-moneyness inputs use ``k = log(K / F)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class AssetClass(str, Enum):
    """Asset class — selects SABR ``beta`` and downstream conventions."""

    EQUITY = "equity"
    FX = "fx"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    RATES = "rates"


# SABR β by asset class. β is conventionally fixed per asset (α and β are
# near-collinear when fit to a single smile), so the calibrator treats β
# as a constant looked up from this map.
BETA_BY_ASSET_CLASS: dict[AssetClass, float] = {
    AssetClass.EQUITY: 1.0,
    AssetClass.FX: 0.5,
    AssetClass.COMMODITY: 0.7,
    AssetClass.CRYPTO: 1.0,
    AssetClass.RATES: 0.0,
}


class VolModel(str, Enum):
    """Parametric vol-curve family used for the slice fit."""

    SSVI = "ssvi"
    SABR = "sabr"


@dataclass(frozen=True)
class FilterConfig:
    """Tunable thresholds for `clean.quality_filter` & friends."""

    min_bid: float = 0.05
    min_ask: float = 0.05
    max_rel_spread: float = 0.25
    min_volume_oi: int = 10
    max_abs_log_moneyness: float = 1.5


@dataclass(frozen=True)
class OptionQuote:
    """One row of an option chain (post-cleaning).

    ``mid`` is ``(bid + ask) / 2``; ``spread`` is ``ask - bid``.
    ``iv_yahoo`` is the IV published by yfinance — kept for reference
    only; the pipeline re-inverts IV from the mid price via Black-76.
    """

    strike: float
    bid: float
    ask: float
    mid: float
    last: float | None
    volume: int
    oi: int
    iv_yahoo: float | None
    is_call: bool
    contract_symbol: str = ""

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class ExpiryChain:
    """All quotes for one underlying at one expiry.

    The internal representation is a pandas ``DataFrame`` because the rest
    of the pipeline is vectorised. Expected columns:

        strike (float), bid, ask, mid, last, volume, oi,
        iv_yahoo, is_call (bool), contract_symbol, spread (= ask - bid)
    """

    ticker: str
    spot: float
    expiry: str  # YYYY-MM-DD
    T: float  # years to expiry
    quotes: pd.DataFrame
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParityFit:
    """Output of parity.* — (D, F, r) for one expiry.

    Two production callers populate this:

    - ``fit_parity`` (diagnostic only): all four fields are
      chain-implied from the two-parameter regression.
    - ``fit_forward_at_rate`` (pricing path): ``D`` and ``r`` are
      pinned to the externally-known SOFR; only ``F`` is extracted
      from the chain (one-parameter fit, much more robust to
      noisy short-DTE / illiquid chains than the regression-slope
      extraction).
    """

    D: float
    F: float
    r: float
    r2: float
    residual_std: float
    n_strikes: int
    n_iterations: int


@dataclass
class SSVIParams:
    """Calibrated SSVI slice parameters."""

    theta_T: float  # ATM total variance anchor
    rho: float  # skew
    eta: float  # vol-of-vol multiplier
    gamma: float  # power-law exponent for φ = η · θ^{-γ}
    rmse_iv: float
    n_obs: int
    butterfly_margin: float  # gap to G-J Thm 4.2 bound; > 0 ⇒ arb-free
    param_cov: np.ndarray = field(  # 3×3 over (ρ, η, γ); θ_T held fixed
        default_factory=lambda: np.zeros((3, 3))
    )


@dataclass
class SABRParams:
    """Calibrated SABR (Hagan 2002 lognormal) slice parameters."""

    alpha: float
    beta: float  # fixed by AssetClass; β row/col of cov are zeros
    rho: float
    nu: float
    rmse_iv: float
    n_obs: int
    param_cov: np.ndarray = field(default_factory=lambda: np.zeros((4, 4)))


@dataclass
class IVFit:
    """Result of the parametric vol-curve fit (SSVI or SABR)."""

    model: VolModel
    K_grid: np.ndarray
    iv_grid: np.ndarray  # parametric-only IV on K_grid
    F: float
    D: float
    T: float
    rmse_iv: float
    n_obs: int
    ssvi: SSVIParams | None = None
    sabr: SABRParams | None = None


@dataclass
class GPBand:
    """Posterior of the GP fit on the (market − parametric) IV residual."""

    K_grid: np.ndarray
    iv_mean: np.ndarray  # parametric + GP-posterior mean residual
    iv_std: np.ndarray
    iv_samples: np.ndarray  # (n_samples, n_grid) — full IV curves
    kernel_repr: str = ""  # str(gpr.kernel_) for diagnostics


@dataclass
class RND:
    """One risk-neutral density curve (median or single posterior sample)."""

    K_grid: np.ndarray
    density: np.ndarray
    integral: float  # ∫ q dK — should be ~ 1.0
    mean: float  # ∫ K q dK — should be ~ F
    variance: float
    method: str  # "gatheral" or "shimko"
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class RNDBand:
    """Credible bands from per-sample RND extraction."""

    K_grid: np.ndarray
    density_median: np.ndarray
    density_lo68: np.ndarray
    density_hi68: np.ndarray
    density_lo90: np.ndarray
    density_hi90: np.ndarray
    n_samples: int
    method: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArbDiagnostics:
    """No-arbitrage check results on the fitted slice."""

    durrleman_min: float  # min Durrleman g(k); should be ≥ 0
    lee_left: float  # left-wing total variance slope
    lee_right: float  # right-wing total variance slope
    n_neg_clipped: int  # samples requiring q ← max(q, 0)
    integral_q: float
    mean_recovery_pct: float  # 100·(E[K] − F)/F


@dataclass
class SurfaceFit:
    """Complete slice fit — everything needed for one expiry's UI payload."""

    ticker: str
    spot: float
    expiry: str
    T: float
    F: float
    D: float
    # ``r`` is the externally-known risk-free rate (SOFR) — the
    # pipeline no longer extracts a rate from the chain. The chain-
    # implied rate from the unconstrained parity regression is
    # preserved as ``r_implied_raw`` (below) purely for diagnostic
    # transparency.
    r: float
    model: VolModel
    parity: ParityFit
    iv_fit: IVFit
    gp_band: GPBand
    rnd_band: RNDBand
    arbitrage: ArbDiagnostics
    market_quotes: pd.DataFrame  # filtered OTM quotes with iv column
    available_expiries: list[str] = field(default_factory=list)
    # Raw parity-implied annualised rate, **before** any SOFR
    # substitution. Useful for quants who want to see what the
    # regression actually produced even when the value was overridden
    # because it failed the (0, 0.20) USD sanity bounds.
    r_implied_raw: float = 0.0
    # Off-hours staleness: ``stale_fraction`` is the share of underlying
    # quotes that fell back to ``lastPrice`` (no live bid/ask).
    # ``is_stale`` is True when that share is ≥ 50 % — the slice was
    # fitted on settled prices rather than live two-sided quotes and
    # downstream (parity-implied r, GP credible bands, RND uncertainty)
    # should be treated as degraded.
    stale_fraction: float = 0.0
    is_stale: bool = False
