"""
Option-surface service — orchestrates the per-expiry pipeline and assembles
multi-expiry surfaces for the dashboard.

Public methods:
    get_single_expiry_fit  full SurfaceFit for one expiry (default model SSVI)
    get_multi_expiry_fit   per-expiry fits assembled into an IV + RND surface
    get_spread_curve       per-expiry ATM put-call IV spread (lightweight)

Caching: in-process LRU keyed by ``(ticker, expiry, model, asset_class,
n_grid, r_bucket)`` where ``r_bucket = round(r * 1e4)`` so an overnight
SOFR refresh invalidates the previous day's fits. Default TTL is 30 minutes.

Risk-free rate handling: the pipeline no longer extracts a rate from the
chain (the put-call parity slope is too noisy on short-DTE / illiquid
chains — sub-cent bid-ask noise amplifies into double-digit rate
errors). Instead the service resolves the SOFR rate once per call via
``_resolve_rfr`` and passes it into ``fit_expiry`` as ``r_external``.
The chain-implied rate is still computed inside the pipeline and
preserved on ``SurfaceFit.r_implied_raw`` as a diagnostic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np
import pandas as pd

from core.exceptions import ValidationError
from stats.options.diagnostics import calendar_violation
from stats.options.pipeline import fit_expiry
from stats.options.types import (
    AssetClass,
    SurfaceFit,
    VolModel,
)

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 1800  # 30 minutes
_DEFAULT_N_GRID_SINGLE = 200
_DEFAULT_N_GRID_MULTI = 120
_DEFAULT_GP_SAMPLES = 500
_MONEYNESS_LO = 0.6
_MONEYNESS_HI = 1.4
# Hardcoded fallback risk-free rate used only when the SOFR fetcher
# fails (no network, DB unavailable). Roughly mid-cycle SOFR — better
# to price against a plausible constant than to crash the whole
# surface fetch. Logged loudly so the operator knows the fetcher is
# down.
_FALLBACK_RATE = 0.045
_FALLBACK_SOURCE = "fallback_constant"


def _seconds_to_years(seconds: float) -> float:
    """ACT/365 day count."""
    return max(seconds / (365.25 * 24 * 3600), 0.0)


class OptionSurfaceService:
    """Backend orchestrator for the options / RND surface tab."""

    def __init__(
        self,
        yf_provider,
        rf_fetcher=None,
        asset_class: AssetClass = AssetClass.EQUITY,
        cache_ttl: int = _DEFAULT_TTL,
    ) -> None:
        self._yf = yf_provider
        self._rf = rf_fetcher
        self._asset_class = asset_class
        self._ttl = int(cache_ttl)
        self._cache: dict[tuple, tuple[float, Any]] = {}

    # ---- internal cache --------------------------------------------------

    def _cache_get(self, key: tuple) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._ttl:
                return val
            del self._cache[key]
        return None

    def _cache_set(self, key: tuple, val: Any) -> None:
        self._cache[key] = (time.time(), val)
        # Naive eviction policy — bound to 100 entries.
        if len(self._cache) > 100:
            oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
            del self._cache[oldest]

    # ---- risk-free rate --------------------------------------------------

    async def _resolve_rfr(self, currency: str = "USD") -> tuple[float, str]:
        """Resolve the external risk-free rate for option pricing.

        Returns:
            ``(rate_decimal, source_label)`` — e.g. ``(0.0431, "SOFR")``.
            ``rate_decimal`` is the annualised zero rate as a decimal
            (so 0.0431 ↔ 4.31 %).

        Falls back to ``_FALLBACK_RATE`` with a warning if the fetcher
        is unavailable or raises. The asset universe is US-listed
        equity/ETF/index so ``currency`` is effectively always
        ``"USD"`` — the parameter is kept for forward compatibility
        when we expand to non-USD listings.
        """
        if self._rf is None:
            logger.warning(
                "No risk-free fetcher configured; using fallback r = %.4f",
                _FALLBACK_RATE,
            )
            return _FALLBACK_RATE, _FALLBACK_SOURCE
        try:
            rate_pct, source = await self._rf.get_current_rate(currency)
            return float(rate_pct) / 100.0, str(source)
        except (OSError, KeyError, ValueError) as e:
            logger.warning(
                "Risk-free rate fetch failed (%s); using fallback r = %.4f",
                e,
                _FALLBACK_RATE,
            )
            return _FALLBACK_RATE, _FALLBACK_SOURCE

    # ---- single-expiry fit ----------------------------------------------

    async def get_single_expiry_fit(
        self,
        ticker: str,
        expiry: str | None = None,
        *,
        model: VolModel = VolModel.SSVI,
        n_grid: int = _DEFAULT_N_GRID_SINGLE,
        gp_samples: int = _DEFAULT_GP_SAMPLES,
    ) -> SurfaceFit:
        """Run the full slice pipeline for one expiry, returning a SurfaceFit.

        Cache invariant: an auto-select call and a subsequent explicit
        call for the same resolved expiry **must return the same
        SurfaceFit object** (otherwise the user sees the chart shift
        when they click their own auto-selected date in the dropdown).
        We enforce this by:

        1. Letting ``get_option_chain_raw`` dual-cache its result
           under both ``TICKER:auto`` and ``TICKER:resolved`` keys
           (see the provider for details).
        2. After running the pipeline, also cache the SurfaceFit
           under the ``resolved-expiry`` key so the next explicit
           lookup hits the same object rather than re-running the
           fit.
        3. Before running the pipeline on an auto request, probe the
           cache for the resolved-expiry key (after we know what the
           provider returned) — if a previous explicit call already
           computed it, reuse that fit.

        Cache key includes a rounded SOFR bucket (``round(r * 1e4)``)
        so an overnight rate refresh invalidates the previous day's
        fits.
        """
        r_external, _ = await self._resolve_rfr("USD")
        r_bucket = round(r_external * 1e4)

        def _cache_key(exp_str: str) -> tuple:
            return (
                "single",
                ticker.upper(),
                exp_str,
                model.value,
                self._asset_class.value,
                n_grid,
                r_bucket,
            )

        requested_key = _cache_key(expiry or "auto")
        cached = self._cache_get(requested_key)
        if cached is not None:
            return cached

        raw = await self._yf.get_option_chain_raw(ticker.upper(), expiry=expiry)
        if not raw.get("calls") or not raw.get("puts"):
            raise ValueError(
                f"No option chain data for {ticker} (expiry={expiry})"
            )

        # After resolution, also probe the explicit-expiry cache —
        # an earlier explicit lookup may already have computed this
        # exact fit.
        resolved_key = _cache_key(raw["expiry"])
        if resolved_key != requested_key:
            cached_resolved = self._cache_get(resolved_key)
            if cached_resolved is not None:
                self._cache_set(requested_key, cached_resolved)
                return cached_resolved

        quotes_df = _raw_chain_to_dataframe(raw)
        T = _seconds_to_years(raw["expiry_ts"] - time.time())
        if T <= 0:
            raise ValueError(
                f"Expiry {raw['expiry']} is in the past — T={T:.4f} years"
            )

        fit = await asyncio.to_thread(
            fit_expiry,
            quotes_df,
            ticker=raw["ticker"],
            expiry=raw["expiry"],
            T=T,
            spot=raw["spot"],
            r_external=r_external,
            model=model,
            asset_class=self._asset_class,
            n_grid=n_grid,
            gp_samples=gp_samples,
            available_expiries=list(raw.get("available_expiries", [])),
        )
        self._cache_set(requested_key, fit)
        # Cross-cache under the resolved-expiry key so a later
        # explicit lookup for the same date returns the same fit.
        if resolved_key != requested_key:
            self._cache_set(resolved_key, fit)
        return fit

    # ---- multi-expiry fit -----------------------------------------------

    async def get_multi_expiry_fit(
        self,
        ticker: str,
        *,
        n_expiries: int = 8,
        model: VolModel = VolModel.SSVI,
        n_grid: int = _DEFAULT_N_GRID_MULTI,
        gp_samples: int = 200,
    ) -> dict:
        """Fit the first N expiries; assemble IV + RND surfaces on a shared
        moneyness grid.

        Returns the dict that ``MultiSurfaceFitResponse`` consumes. The
        moneyness grid is shared across expiries (``K = F[i] · moneyness``);
        the frontend uses ``F`` per expiry to recover absolute strikes for
        display.

        Cache key includes a rounded SOFR bucket (``round(r * 1e4)``) so
        an overnight rate refresh invalidates the previous day's fits.
        """
        r_external, _ = await self._resolve_rfr("USD")
        r_bucket = round(r_external * 1e4)
        key = (
            "multi",
            ticker.upper(),
            model.value,
            self._asset_class.value,
            n_expiries,
            n_grid,
            r_bucket,
        )
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        # Fetch the full list of expiries via a single light call.
        raw_first = await self._yf.get_option_chain_raw(ticker.upper(), expiry=None)
        expiries = (raw_first.get("available_expiries") or [])[:n_expiries]
        if not expiries:
            raise ValueError(f"No expiries available for {ticker}")

        # Fan out per-expiry fits concurrently. Failures are logged and
        # the corresponding expiry is dropped from the surface. We catch
        # the typed errors the pipeline can raise (ValueError from
        # filter/inversion, RuntimeError from optimiser, LinAlgError
        # from covariance inversion); anything else propagates so we
        # don't silently swallow programming bugs.
        async def _safe_single(exp: str):
            try:
                return await self.get_single_expiry_fit(
                    ticker, expiry=exp, model=model, n_grid=n_grid, gp_samples=gp_samples
                )
            except (ValidationError, ValueError, RuntimeError, np.linalg.LinAlgError) as e:
                logger.warning(
                    "Skipping expiry %s for %s: %s", exp, ticker, e
                )
                return None

        fits_raw = await asyncio.gather(*(_safe_single(e) for e in expiries))
        fits: list[SurfaceFit] = [f for f in fits_raw if f is not None]
        if not fits:
            raise ValueError(f"All per-expiry fits failed for {ticker}")

        moneyness = np.linspace(_MONEYNESS_LO, _MONEYNESS_HI, n_grid)
        iv_surface: list[list[float]] = []
        iv_lo68: list[list[float]] = []
        iv_hi68: list[list[float]] = []
        rnd_surface: list[list[float]] = []
        rnd_lo68: list[list[float]] = []
        rnd_hi68: list[list[float]] = []
        F_vals: list[float] = []
        r_vals: list[float] = []
        T_vals: list[float] = []
        expiry_strs: list[str] = []

        for fit in fits:
            F_vals.append(fit.F)
            r_vals.append(fit.r)
            T_vals.append(fit.T)
            expiry_strs.append(fit.expiry)

            K_local = fit.F * moneyness  # absolute strikes for this expiry
            # Interpolate IV mean / 68-band onto K_local from the slice's K_grid.
            iv_surface.append(
                np.interp(K_local, fit.gp_band.K_grid, fit.gp_band.iv_mean).tolist()
            )
            iv_lo = fit.gp_band.iv_mean - fit.gp_band.iv_std
            iv_hi = fit.gp_band.iv_mean + fit.gp_band.iv_std
            iv_lo68.append(np.interp(K_local, fit.gp_band.K_grid, iv_lo).tolist())
            iv_hi68.append(np.interp(K_local, fit.gp_band.K_grid, iv_hi).tolist())
            rnd_surface.append(
                np.interp(K_local, fit.rnd_band.K_grid, fit.rnd_band.density_median).tolist()
            )
            rnd_lo68.append(
                np.interp(K_local, fit.rnd_band.K_grid, fit.rnd_band.density_lo68).tolist()
            )
            rnd_hi68.append(
                np.interp(K_local, fit.rnd_band.K_grid, fit.rnd_band.density_hi68).tolist()
            )

        # Calendar-arbitrage diagnostic across the assembled slices.
        # Uses each slice's IV grid + parity-implied forward.
        calendar = calendar_violation(
            [(fit.T, fit.gp_band.K_grid, fit.gp_band.iv_mean) for fit in fits],
            [fit.F for fit in fits],
        )

        payload = {
            "ticker": ticker.upper(),
            "spot": fits[0].spot,
            "expiries": expiry_strs,
            "T_values": T_vals,
            "moneyness_grid": moneyness.tolist(),
            "iv_surface": iv_surface,
            "iv_lo68": iv_lo68,
            "iv_hi68": iv_hi68,
            "rnd_surface": rnd_surface,
            "rnd_lo68": rnd_lo68,
            "rnd_hi68": rnd_hi68,
            "F": F_vals,
            "r": r_vals,
            "calendar": {
                "n_violations": int(calendar["n_violations"]),
                "worst_violation": float(calendar["worst_violation"]),
            },
        }
        self._cache_set(key, payload)
        return payload

    # ---- spread curve ---------------------------------------------------

    async def get_spread_curve(self, ticker: str, *, n_expiries: int = 12) -> dict:
        """Per-expiry ATM put-call IV spread (decimal IV).

        Uses yfinance's published IV at the strike closest to spot.
        Cheap — no inversion, no fitting.
        """
        key = ("spread", ticker.upper(), n_expiries)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        raw_first = await self._yf.get_option_chain_raw(ticker.upper(), expiry=None)
        expiries = (raw_first.get("available_expiries") or [])[:n_expiries]
        spot = raw_first.get("spot", 0.0)

        async def _safe_spread(exp: str):
            try:
                raw = await self._yf.get_option_chain_raw(
                    ticker.upper(), expiry=exp
                )
                T = _seconds_to_years(raw["expiry_ts"] - time.time())
                if T <= 0:
                    return None
                calls = raw["calls"]
                puts = raw["puts"]
                if not calls or not puts:
                    return None
                atm_call = min(
                    (c for c in calls if c["iv_yahoo"] is not None),
                    key=lambda c: abs(c["strike"] - spot),
                    default=None,
                )
                atm_put = min(
                    (p for p in puts if p["iv_yahoo"] is not None),
                    key=lambda p: abs(p["strike"] - spot),
                    default=None,
                )
                if atm_call is None or atm_put is None:
                    return None
                return {
                    "expiry": exp,
                    "T": T,
                    "call_iv": float(atm_call["iv_yahoo"]),
                    "put_iv": float(atm_put["iv_yahoo"]),
                    "spread": float(atm_put["iv_yahoo"] - atm_call["iv_yahoo"]),
                }
            except (ValidationError, ValueError, RuntimeError, KeyError) as e:
                # Per-expiry failure is the common off-hours case
                # (entire chain stale → quality_filter empties); demote
                # to debug and emit a single summary WARNING below if
                # any expiry was skipped.
                logger.debug(
                    "Spread curve: skipping %s expiry %s: %s", ticker, exp, e
                )
                return None

        rows_raw = await asyncio.gather(*(_safe_spread(e) for e in expiries))
        rows = [r for r in rows_raw if r is not None]
        n_skipped = len(expiries) - len(rows)
        if n_skipped:
            logger.warning(
                "Spread curve: %d / %d %s expiries skipped (likely off-hours "
                "or no published IV).",
                n_skipped,
                len(expiries),
                ticker,
            )
        payload = {"ticker": ticker.upper(), "spread_curve": rows}
        self._cache_set(key, payload)
        return payload


def _raw_chain_to_dataframe(raw: dict) -> pd.DataFrame:
    """Flatten the ``get_option_chain_raw`` payload into a single DataFrame."""
    calls = pd.DataFrame(raw["calls"])
    puts = pd.DataFrame(raw["puts"])
    df = pd.concat([calls, puts], ignore_index=True)
    if "spread" not in df.columns:
        df["spread"] = df["ask"] - df["bid"]
    if "mid" not in df.columns:
        df["mid"] = 0.5 * (df["bid"] + df["ask"])
    return df
