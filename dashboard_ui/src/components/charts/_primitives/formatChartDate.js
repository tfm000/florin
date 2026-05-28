/**
 * UTC-pinned date formatting utilities for Recharts axis ticks and tooltip labels.
 *
 * Closes PRIM-03 / B-11 / CONTEXT D-05.
 *
 * The bug this replaces: `new Date(v + 'T00:00:00')` creates a LOCAL timezone Date
 * object. In zones west of UTC (e.g., US/Eastern UTC-5), midnight local = 05:00 UTC,
 * so '2024-03-10T00:00:00' displays as 'Mar 9' when formatted in UTC-offset locales.
 * The fix: split the ISO string and construct via Date.UTC(...) so the Date is always
 * at UTC midnight, then format with timeZone: 'UTC' to prevent a reshift.
 *
 * Supersedes the four inline `new Date(v + 'T00:00:00')` sites in CumulativeReturnChart.jsx
 * (lines 282, 296, 302, 414-415).
 */

/**
 * Format an ISO date string for chart axis tick labels.
 *
 * Daily mode (default): returns 'Mon YYYY' (e.g., 'Jan 2024').
 * Intraday mode: returns 'YYYY-MM-DD HH:MM' (e.g., '2024-01-15 14:30').
 *
 * @param {string|null} dateStr - ISO date string ("2024-01-15" or "2024-01-15T14:30:00").
 *   Null and empty string are handled gracefully.
 * @param {boolean} [intraday=false] - When true, the string is treated as an intraday
 *   timestamp and the time component is preserved.
 * @returns {string} Formatted label, or '' for null/empty input.
 */
export function formatChartDate(dateStr, intraday = false) {
  if (!dateStr) return ''

  if (intraday) {
    // Intraday timestamps: preserve the time component verbatim.
    // "2024-01-15T14:30:00" → "2024-01-15 14:30"
    return dateStr.length > 10 ? dateStr.slice(0, 16).replace('T', ' ') : dateStr
  }

  // Daily: parse only the date portion to avoid any time/TZ contamination.
  const datePart = dateStr.slice(0, 10) // "YYYY-MM-DD"
  const [year, month, day] = datePart.split('-').map(Number)

  // Date.UTC constructs a UTC midnight timestamp — no local-TZ shift.
  const d = new Date(Date.UTC(year, month - 1, day))

  // timeZone: 'UTC' prevents toLocaleDateString from re-applying a local offset.
  return d.toLocaleDateString('en', {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/**
 * Format an ISO date string for chart tooltip labels (longer form with day number).
 *
 * Daily mode: returns 'D Mon YYYY' (e.g., '15 Jan 2024').
 * Intraday mode: returns 'YYYY-MM-DD HH:MM' (same as formatChartDate intraday).
 *
 * Used by ChartTooltip (Plan 02-03) as the tooltip labelFormatter.
 *
 * @param {string|null} dateStr - ISO date string ("2024-01-15" or "2024-01-15T14:30:00").
 * @param {boolean} [intraday=false] - When true, the time component is preserved.
 * @returns {string} Formatted label, or '' for null/empty input.
 */
export function formatChartDateLong(dateStr, intraday = false) {
  if (!dateStr) return ''

  if (intraday) {
    return dateStr.length > 10 ? dateStr.slice(0, 16).replace('T', ' ') : dateStr
  }

  const [year, month, day] = dateStr.slice(0, 10).split('-').map(Number)
  const d = new Date(Date.UTC(year, month - 1, day))

  // Includes day: 'numeric' for the full date (e.g., "Jan 15, 2024" or "15 Jan 2024"
  // depending on locale, but always with day, month, and year present).
  return d.toLocaleDateString('en', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}
