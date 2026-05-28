/**
 * PercentAxis — recharts YAxis wrapper with signed-percentage formatting.
 *
 * Closes PRIM-02 (axis primitives) + CHART-03 (percent formatter with 1-decimal precision).
 *
 * Extracts the comparison-mode YAxis from CumulativeReturnChart.jsx:285-290 with the
 * formatY defined at lines 173-174. Bumps precision from 0 decimal (CRC's axis) to
 * 1 decimal per plan requirement — tooltips get the added precision while the axis
 * still looks clean at ±10.0%, ±5.0%, etc.
 *
 * The `domain` prop is pre-computed by the caller via safeDomain() (Plan 02-01). This
 * primitive does NOT import safeDomain — separation of concerns: the primitive renders,
 * the caller computes the domain.
 *
 * @module PercentAxis
 */

import { YAxis } from 'recharts'

/**
 * Recharts YAxis wrapper that renders signed percentage labels with 1-decimal precision.
 *
 * Renders: "+5.0%", "-2.3%", "+0.0%", "-12.5%"
 *
 * @param {object} props
 * @param {[number, number]} [props.domain] - Pre-computed [min, max] from safeDomain().
 *   If omitted, recharts auto-scales.
 * @param {string} [props.label="Return (%)"] - Y-axis label text rendered vertically
 *   on the left side.
 * @returns {React.ReactElement} Recharts YAxis element with the percent formatter.
 */
export function PercentAxis({ domain, label = 'Return (%)' }) {
  return (
    <YAxis
      tick={{ fill: '#9CA3AF', fontSize: 11 }}
      domain={domain}
      tickFormatter={(v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
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
