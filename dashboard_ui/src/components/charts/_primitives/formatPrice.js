/**
 * Currency-aware price formatting utility shared by PriceAxis tick labels
 * and PriceHistoryChart tooltip formatters.
 *
 * Centralising here prevents the CURRENCY_PREFIX map and tier logic from
 * being duplicated between PriceAxis.jsx and PriceHistoryChart.jsx (closes
 * CHART-03 / D-09 requirement: no hard-coded "$" in display code).
 *
 * @module formatPrice
 */

/**
 * Map of ISO 4217 currency codes to their display prefix symbols.
 * Codes absent from this map fall back to `"<CODE> "` (with a trailing
 * space) so they display as e.g. "CHF 100.00" rather than silently
 * using a dollar sign.
 *
 * @type {Object.<string, string>}
 */
export const CURRENCY_PREFIX = {
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
 * @param {number} v - Numeric price value.
 * @param {string} [currency="USD"] - ISO 4217 currency code.
 * @returns {string} Formatted price string with currency prefix.
 */
export function formatPrice(v, currency = 'USD') {
  const prefix = CURRENCY_PREFIX[currency] ?? `${currency} `
  if (v >= 1000) return `${prefix}${(v / 1000).toFixed(1)}k`
  if (v >= 1) return `${prefix}${v.toFixed(2)}`
  return `${prefix}${v.toFixed(4)}`
}
