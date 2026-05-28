/**
 * NaN-safe domain computation for Recharts YAxis.
 *
 * Closes PRIM-02 / B-14 / CONTEXT D-05.
 *
 * The bug this replaces: `Math.min(...[])` returns Infinity; `Math.max(...[])` returns
 * -Infinity. Passing [Infinity, -Infinity] as a recharts `domain` prop causes the axis
 * to render nothing or behave unexpectedly. Similarly, a values array containing NaN
 * or null (e.g., from missing data points or regime gaps) causes Math.min/max to return
 * NaN, corrupting the axis scale.
 *
 * Supersedes the inline `Math.min(...values)` / `Math.max(...values)` at
 * CumulativeReturnChart.jsx:166-171.
 *
 * Both PriceAxis and PercentAxis import this helper (extracted to a shared file rather
 * than inlined to avoid duplication per CONTEXT D-05 and PATTERNS.md).
 */

/**
 * Compute a NaN-safe [min, max] domain from an array of values.
 *
 * Filters out NaN, null, undefined, and non-finite values (Infinity, -Infinity) before
 * computing min/max. Applies symmetric padding so the axis doesn't clip the data line.
 * Falls back to [0, 1] if no finite values remain (empty array or all-NaN input).
 *
 * Degenerate case (single value or all same value): padding is computed as
 * `Math.abs(value) * 0.1 || 1` to ensure a non-zero range, matching the precedent
 * at CumulativeReturnChart.jsx:169.
 *
 * @param {Array<number|null|undefined>} values - Raw numeric values (may contain NaN, null, undefined).
 * @param {number} [paddingFactor=0.05] - Fractional padding applied symmetrically to each side.
 *   e.g., 0.05 means 5% of the data range is added to each end.
 * @returns {[number, number]} A finite [lo, hi] tuple safe for use as a recharts domain prop.
 */
export function safeDomain(values, paddingFactor = 0.05) {
  // Filter to only finite numbers — rejects NaN, null, undefined, Infinity, -Infinity
  const finite = values.filter(v => v != null && Number.isFinite(v))

  if (finite.length === 0) {
    // No usable data: return a unit interval so the axis renders with a sensible scale
    return [0, 1]
  }

  const min = Math.min(...finite)
  const max = Math.max(...finite)

  if (min === max) {
    // Degenerate: single value or all identical values.
    // Use 10% of the absolute value as padding (or 1 if the value is zero).
    const padding = Math.abs(max) * 0.1 || 1
    return [min - padding, max + padding]
  }

  const padding = (max - min) * paddingFactor
  return [min - padding, max + padding]
}
