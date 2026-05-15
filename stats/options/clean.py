"""
Quote-cleaning filters for option chains.

All filters take and return an ``ExpiryChain`` so they compose naturally:

    chain = quality_filter(chain)
    chain = otm_filter(chain, F)
    chain = restrict_log_moneyness(chain, F)

``FilterConfig`` collects every tunable threshold so they can be swapped
out from the service layer for different asset classes / liquidity
regimes.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from stats.options.types import ExpiryChain, FilterConfig


def quality_filter(
    chain: ExpiryChain, cfg: FilterConfig | None = None
) -> ExpiryChain:
    """Drop quotes failing basic liquidity / spread checks.

    Rules:
      bid > min_bid                  (filters zero-bid / phantom strikes)
      ask > min_ask
      relative_spread ≤ max_rel_spread
      volume + open_interest ≥ min_volume_oi
    """
    cfg = cfg or FilterConfig()
    q = chain.quotes
    if len(q) == 0:
        diags = dict(chain.diagnostics)
        diags["n_after_quality"] = 0
        return replace(chain, diagnostics=diags)

    mid = q["mid"].to_numpy(dtype=float)
    spread = q["spread"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel_spread = np.where(mid > 0, spread / mid, np.inf)
    vol = q["volume"].fillna(0).to_numpy(dtype=float)
    oi = q["oi"].fillna(0).to_numpy(dtype=float)
    keep = (
        (q["bid"].to_numpy(dtype=float) > cfg.min_bid)
        & (q["ask"].to_numpy(dtype=float) > cfg.min_ask)
        & (rel_spread <= cfg.max_rel_spread)
        & ((vol + oi) >= cfg.min_volume_oi)
    )
    new_quotes = q.loc[keep].reset_index(drop=True)
    diags = dict(chain.diagnostics)
    diags["n_after_quality"] = int(len(new_quotes))
    return replace(chain, quotes=new_quotes, diagnostics=diags)


def otm_filter(chain: ExpiryChain, F: float) -> ExpiryChain:
    """Keep OTM only: calls at K ≥ F, puts at K < F.

    For American single-stock options the early-exercise premium is
    largest ITM; the OTM-only restriction makes put-call parity hold to
    well within the bid-ask noise floor.
    """
    q = chain.quotes
    if len(q) == 0:
        return chain
    keep_call = q["is_call"] & (q["strike"] >= F)
    keep_put = (~q["is_call"]) & (q["strike"] < F)
    new_quotes = q.loc[keep_call | keep_put].reset_index(drop=True)
    diags = dict(chain.diagnostics)
    diags["n_after_otm"] = int(len(new_quotes))
    return replace(chain, quotes=new_quotes, diagnostics=diags)


def restrict_log_moneyness(
    chain: ExpiryChain, F: float, cfg: FilterConfig | None = None
) -> ExpiryChain:
    """Drop quotes with |log(K/F)| exceeding the configured wing cap.

    Useful before parametric calibration: the asymptotic tails contribute
    little signal but can dominate a least-squares objective.
    """
    cfg = cfg or FilterConfig()
    q = chain.quotes
    if len(q) == 0:
        return chain
    K = q["strike"].to_numpy(dtype=float)
    lm = np.log(K / F)
    keep = np.abs(lm) <= cfg.max_abs_log_moneyness
    new_quotes = q.loc[keep].reset_index(drop=True)
    diags = dict(chain.diagnostics)
    diags["n_after_log_moneyness"] = int(len(new_quotes))
    return replace(chain, quotes=new_quotes, diagnostics=diags)
