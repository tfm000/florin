/**
 * ChartTooltip — shared tooltip primitive for all Florin chart components.
 *
 * Built on recharts 3.x headless hooks (D-03) so the inner body has access to
 * the chart's Redux store state directly, not only via the `content` prop args.
 *
 * Usage:
 *   <ChartTooltip />
 *   <ChartTooltip labelFormatter={v => `Date: ${v}`} />
 *   <ChartTooltip labelFormatter={v => v} formatter={(v, name) => [v.toFixed(2), name]} />
 *
 * Only ChartTooltip is exported. ChartTooltipBody is an internal implementation
 * detail that is deliberately NOT exported — consumers interact exclusively via
 * ChartTooltip's prop API.
 *
 * @module ChartTooltip
 */
import {
  Tooltip,
  useActiveTooltipDataPoints,
  useActiveTooltipLabel,
  useIsTooltipActive,
} from 'recharts'

/**
 * Default style objects extracted from CumulativeReturnChart.jsx lines 292-293 —
 * the dark-theme baseline all Florin chart tooltips share.
 */
const DEFAULT_CONTENT_STYLE = {
  background: '#1F2937',
  border: '1px solid #374151',
  borderRadius: 8,
}

const DEFAULT_LABEL_STYLE = { color: '#fff' }

/**
 * Inner tooltip body rendered as the `content` prop of recharts <Tooltip>.
 *
 * Receives props injected by recharts (active, payload, label) PLUS forwarded
 * caller props (labelFormatter, formatter). Also calls the three D-03 headless
 * hooks to access chart state directly from the recharts Redux store.
 *
 * IMPORTANT — do NOT add any setState / useState calls to this component.
 * useActiveTooltipDataPoints returns a new Set reference on every selector
 * evaluation (recharts GitHub issue #6613). If this component re-renders in
 * response to a state update, it triggers an infinite re-render loop.
 * This component is intentionally display-only: no local state, no effects.
 *
 * @param {boolean} active - Whether the tooltip is currently visible (from recharts).
 * @param {Array} payload - TooltipPayloadEntry[]; each has .value, .name, .color,
 *   .dataKey, .payload (raw data row).
 * @param {*} label - The active X-axis label (from recharts).
 * @param {Function} [labelFormatter] - Called as labelFormatter(resolvedLabel, payload);
 *   result replaces the header label.
 * @param {Function} [formatter] - Called as formatter(value, name, entry, index, payload)
 *   per recharts contract; result replaces the per-entry display value.
 */
function ChartTooltipBody({ active, payload, label, labelFormatter, formatter }) {
  // D-03: headless hooks called inside Tooltip content component, which is inside
  // the recharts ComposedChart tree and therefore has access to the Redux store.
  const isActive = useIsTooltipActive()
  const activeLabel = useActiveTooltipLabel()
  // Raw data rows — useful for OHLCV access; here consumed only indirectly via payload.
  // eslint-disable-next-line no-unused-vars
  const _dataPoints = useActiveTooltipDataPoints()

  // Fall back to hook values when recharts injects undefined (e.g. during SSR
  // or when Tooltip is rendered outside a ComposedChart in tests).
  const resolvedActive = active ?? isActive
  const resolvedLabel = label ?? activeLabel

  if (!resolvedActive || !payload?.length) return null

  const formattedLabel = labelFormatter
    ? labelFormatter(resolvedLabel, payload)
    : resolvedLabel

  return (
    <div
      style={{
        background: '#1F2937',
        border: '1px solid #374151',
        borderRadius: 8,
        padding: '8px 12px',
        fontSize: 12,
      }}
    >
      <p style={{ color: '#fff', marginBottom: 4 }}>{formattedLabel}</p>
      {payload
        .filter(entry => entry.name !== 'regimeBar' && entry.value != null)
        .map((entry, i) => {
          const displayValue = formatter
            ? formatter(entry.value, entry.name, entry, i, payload)
            : entry.value
          return (
            <p
              key={entry.dataKey ?? entry.name ?? i}
              style={{ color: entry.color ?? '#9CA3AF', margin: 0 }}
            >
              {entry.name}: {displayValue}
            </p>
          )
        })}
    </div>
  )
}

/**
 * ChartTooltip — drop-in replacement for recharts <Tooltip> in all Florin charts.
 *
 * Provides the dark-theme tooltip style by default (matching the rest of the
 * dashboard). Filters the synthetic 'regimeBar' shading key so it never appears
 * in tooltip text. Forwards all props to the inner ChartTooltipBody so callers
 * can provide custom labelFormatter and formatter functions.
 *
 * Any recharts <Tooltip> prop (cursor, animationDuration, wrapperStyle, etc.)
 * is forwarded to the underlying <Tooltip> via prop spread. Callers that need
 * a fully custom tooltip body should use recharts <Tooltip> directly rather
 * than wrapping ChartTooltip.
 *
 * @param {Function} [props.labelFormatter] - Custom label formatter; called as
 *   labelFormatter(label, payload). Forwarded to ChartTooltipBody.
 * @param {Function} [props.formatter] - Custom value formatter; called as
 *   formatter(value, name, entry, index, payload). Forwarded to ChartTooltipBody.
 * @param {Object} [props.contentStyle] - Override the default dark contentStyle.
 * @param {Object} [props.labelStyle] - Override the default white labelStyle.
 * @param {*} [props...] - Any other recharts Tooltip props are forwarded.
 */
export function ChartTooltip(props) {
  return (
    <Tooltip
      contentStyle={DEFAULT_CONTENT_STYLE}
      labelStyle={DEFAULT_LABEL_STYLE}
      content={<ChartTooltipBody {...props} />}
      {...props}
    />
  )
}
