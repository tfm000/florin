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
 * Tick formatting is delegated to formatPrice() from the shared formatPrice.js utility
 * so the CURRENCY_PREFIX map is not duplicated here.
 *
 * @module PriceAxis
 */

import { YAxis } from 'recharts'
import { formatPrice } from './formatPrice'

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
  return (
    <YAxis
      tick={{ fill: '#9CA3AF', fontSize: 11 }}
      domain={domain}
      tickFormatter={(v) => formatPrice(v, currency)}
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
