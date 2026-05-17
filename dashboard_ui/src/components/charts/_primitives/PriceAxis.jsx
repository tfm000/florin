/**
 * PriceAxis — recharts YAxis wrapper with currency-aware price formatting.
 *
 * Closes PRIM-02 (axis primitives) + CHART-03 (currency-aware formatter; removes hard-coded '$').
 *
 * Replaces the hard-coded `$` formatter at CumulativeReturnChart.jsx:175-179 with a
 * currency-aware lookup. Unknown currency codes fall back to the code itself as a prefix
 * (e.g., 'CHF 100.00') rather than silently using '$' or crashing.
 *
 * The `domain` prop is pre-computed by the caller via safeDomain() (Plan 02-01). This
 * primitive does NOT import safeDomain — callers compute the domain and pass it in.
 * PriceAxis also does NOT import formatChartDate (timezone-agnostic; only DateAxis
 * imports it per CONTEXT D-05).
 *
 * @module PriceAxis
 */

import { YAxis } from 'recharts'

/**
 * Map of ISO 4217 currency codes to their display prefix symbols.
 * Codes not in this map fall back to `"<CODE> "` (with a trailing space) as the prefix.
 *
 * @type {Object.<string, string>}
 */
const CURRENCY_PREFIX = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
}

/**
 * Format a numeric price value with the appropriate currency prefix.
 *
 * Tiers (ported from CumulativeReturnChart.jsx:175-179 with currency substitution):
 *   v >= 1000 → "<prefix><v/1000 toFixed 1>k"  (e.g., "$1.2k", "£850.0k")
 *   v >= 1    → "<prefix><v toFixed 2>"          (e.g., "$185.50", "€42.00")
 *   else      → "<prefix><v toFixed 4>"          (e.g., "$0.0012" for sub-penny assets)
 *
 * @param {number} v - Numeric price value from a recharts tick.
 * @param {string} prefix - The currency prefix string (e.g., '$', '€', 'CHF ').
 * @returns {string} Formatted price string.
 */
function formatPrice(v, prefix) {
  if (v >= 1000) return `${prefix}${(v / 1000).toFixed(1)}k`
  if (v >= 1) return `${prefix}${v.toFixed(2)}`
  return `${prefix}${v.toFixed(4)}`
}

/**
 * Recharts YAxis wrapper that renders currency-aware price tick labels.
 *
 * Currency lookup: USD→'$', EUR→'€', GBP→'£', JPY→'¥'. Any code not in the map
 * is rendered as the code itself with a trailing space (e.g., currency='CHF' → 'CHF 100.00').
 * This is intentional: unknown currencies must never silently use '$' (CHART-03 requirement).
 *
 * @param {object} props
 * @param {[number, number]} [props.domain] - Pre-computed [min, max] from safeDomain().
 *   If omitted, recharts auto-scales.
 * @param {string} [props.currency="USD"] - ISO 4217 currency code (e.g., "USD", "GBP", "EUR").
 * @param {string} [props.label="Price"] - Y-axis label text rendered vertically on the left side.
 * @returns {React.ReactElement} Recharts YAxis element with currency-aware formatter.
 */
export function PriceAxis({ domain, currency = 'USD', label = 'Price' }) {
  // Resolve prefix: known codes use their symbol; unknown codes use the code + space
  const prefix = CURRENCY_PREFIX[currency] ?? `${currency} `

  return (
    <YAxis
      tick={{ fill: '#9CA3AF', fontSize: 11 }}
      domain={domain}
      tickFormatter={(v) => formatPrice(v, prefix)}
      label={{
        value: label,
        angle: -90,
        position: 'insideLeft',
        fill: '#6B7280',
        fontSize: 10,
        dx: -5,
      }}
    />
  )
}
