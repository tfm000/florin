/**
 * Shared moneyness helpers for the options-surface views.
 *
 * Convention: percent moneyness ``(K / F − 1) × 100`` — reads as
 * ``+5 %`` / ``−10 %``. Matches the legacy PutCallIVChart layout
 * and is the most intuitive scale for at-a-glance interpretation.
 *
 * The math grid (``pipeline.fit_expiry`` produces ``[0.5 F, 1.5 F]``)
 * extends many sigmas beyond the RND's effective support; we leave
 * the math grid alone and crop only the displayed range so the
 * integration / sanity gates remain unaffected.
 */

export function pctMoneyness(K, F) {
  if (!F || !Number.isFinite(F) || F <= 0) return 0
  return (K / F - 1) * 100
}

/**
 * Compute the percent-moneyness window where the density signal is
 * meaningfully above zero. Trims wings that contain less than
 * ``peakFrac`` of the peak density (default 0.2 %), then pads each
 * side by ``padPct`` of the trimmed span (default 5 %).
 *
 * Returns ``null`` when the input arrays are empty or degenerate;
 * callers should fall back to Plotly's autorange in that case.
 */
export function cropRangeFromDensity(
  strikes,
  densities,
  F,
  { peakFrac = 0.002, padPct = 0.05 } = {},
) {
  if (!strikes?.length || !densities?.length) return null
  if (strikes.length !== densities.length) return null
  let peak = 0
  for (const v of densities) {
    if (Number.isFinite(v) && v > peak) peak = v
  }
  if (peak <= 0) return null
  const threshold = peak * peakFrac
  let lo = 0
  while (lo < strikes.length - 1 && !(densities[lo] >= threshold)) lo++
  let hi = strikes.length - 1
  while (hi > lo && !(densities[hi] >= threshold)) hi--
  if (lo >= hi) return null
  const loP = pctMoneyness(strikes[lo], F)
  const hiP = pctMoneyness(strikes[hi], F)
  const pad = (hiP - loP) * padPct
  return [loP - pad, hiP + pad]
}

/**
 * Multi-expiry crop: collapse the (n_expiries × n_grid) density
 * matrix down to a per-K maximum, then crop on that. Ensures no
 * single expiry's density gets clipped when slices have different
 * effective widths.
 *
 * ``moneynessGridRatio`` is the K/F-ratio array shipped in
 * ``MultiSurfaceFitResponse.moneyness_grid``. We convert it to
 * percent in-place for the crop computation, then return the
 * percent-moneyness window.
 */
export function cropRangeFromMultiDensity(
  moneynessGridRatio,
  rndSurface,
  { peakFrac = 0.002, padPct = 0.05 } = {},
) {
  if (!moneynessGridRatio?.length || !rndSurface?.length) return null
  const nGrid = moneynessGridRatio.length
  const maxByK = new Array(nGrid).fill(0)
  for (const row of rndSurface) {
    for (let i = 0; i < nGrid && i < row.length; i++) {
      const v = row[i]
      if (Number.isFinite(v) && v > maxByK[i]) maxByK[i] = v
    }
  }
  // Reuse the strike-based crop with the moneyness-ratio grid: pass
  // (ratio − 1) × 100 as 'strikes' and a synthetic F = 1 so
  // ``pctMoneyness(ratio, 1) = (ratio − 1) × 100``.
  return cropRangeFromDensity(moneynessGridRatio, maxByK, 1.0, {
    peakFrac,
    padPct,
  })
}
