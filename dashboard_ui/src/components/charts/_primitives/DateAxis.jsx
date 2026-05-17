/**
 * DateAxis — recharts XAxis wrapper with UTC-pinned date formatting.
 *
 * Closes the PRIM-02 axis half + PRIM-03 consumer half.
 *
 * The inline `new Date(v + 'T00:00:00')` pattern used throughout CumulativeReturnChart.jsx
 * (lines 282, 296, 302, 414-415) creates LOCAL timezone Date objects. In timezones west
 * of UTC (e.g., US/Eastern, UTC-5), midnight local time = 05:00 UTC, so '2024-03-10'
 * displays as 'Mar 9' on the axis. This primitive replaces that bug site by delegating to
 * formatChartDate which uses Date.UTC + timeZone:'UTC' formatting throughout.
 *
 * @module DateAxis
 */

import { XAxis } from 'recharts'
import { formatChartDate } from './formatChartDate'

/**
 * Recharts XAxis wrapper that formats date ticks via the UTC-pinned formatChartDate utility.
 *
 * Renders a standard recharts XAxis with the canonical axis tick style (#9CA3AF, fontSize 10)
 * and a tickFormatter that delegates to formatChartDate(v, intraday) — no inline date
 * construction. The `interval` prop is computed by the caller as:
 *   Math.max(0, Math.floor(chartData.length / 8))
 * to maintain ~8 ticks regardless of series length.
 *
 * @param {object} props
 * @param {string} [props.dataKey="date"] - The recharts dataKey for the time axis.
 * @param {boolean} [props.intraday=false] - When true, tickFormatter preserves the time
 *   portion (e.g., "2024-01-15 14:30"). When false, shows "Mon YYYY" (e.g., "Jan 2024").
 * @param {number} [props.interval=0] - Tick interval hint forwarded to recharts XAxis.
 *   Callers typically compute Math.max(0, Math.floor(data.length / 8)).
 * @returns {React.ReactElement} Recharts XAxis element.
 */
export function DateAxis({ dataKey = 'date', intraday = false, interval = 0 }) {
  return (
    <XAxis
      dataKey={dataKey}
      tick={{ fill: '#9CA3AF', fontSize: 10 }}
      interval={interval}
      tickFormatter={(v) => formatChartDate(v, intraday)}
    />
  )
}
