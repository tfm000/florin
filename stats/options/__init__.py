"""
stats/options — production-grade implied-volatility surface and risk-neutral
density extraction.

Pipeline at a glance (per-expiry slice):

    1. clean.quality_filter         drop wide / thin quotes
    2. parity.fit_parity            extract (D, F, r) via WLS
    3. clean.otm_filter             keep OTM only (parity restriction)
    4. ivinvert.invert_chain        Newton + Brent on Black-76 mids
    5a. ssvi.calibrate_ssvi   (default — arb-free by construction)
    5b. sabr.calibrate_sabr   (toggle)
    6. gp.fit_gp_residual           Matérn-5/2 GP on (mkt − parametric)
    7. rnd.rnd_with_uncertainty     Gatheral (SSVI) or Shimko (SABR)
    8. diagnostics.*                Durrleman, Lee, calendar checks

See ``stats/options/types.py`` for the data classes that flow between
stages, and ``stats/options/pipeline.py`` for the orchestrator entry
points used by ``dashboard/services/option_surface.py``.
"""

from stats.options.types import (
    BETA_BY_ASSET_CLASS,
    RND,
    ArbDiagnostics,
    AssetClass,
    ExpiryChain,
    FilterConfig,
    GPBand,
    IVFit,
    OptionQuote,
    ParityFit,
    RNDBand,
    SABRParams,
    SSVIParams,
    SurfaceFit,
    VolModel,
)

__all__ = [
    "ArbDiagnostics",
    "AssetClass",
    "BETA_BY_ASSET_CLASS",
    "ExpiryChain",
    "FilterConfig",
    "GPBand",
    "IVFit",
    "OptionQuote",
    "ParityFit",
    "RND",
    "RNDBand",
    "SABRParams",
    "SSVIParams",
    "SurfaceFit",
    "VolModel",
]
