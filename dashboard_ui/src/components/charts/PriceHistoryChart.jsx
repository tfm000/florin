import { useMemo, useState } from 'react'
import {
  ComposedChart, Line, Bar, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { useLegendToggle } from '../../hooks/useLegendToggle'
import { useChartColors } from '../../hooks/useChartColors'
import { INDICATOR_DEFS } from '../../utils/indicators'
import {
  ChartFrame,
  ChartTooltip,
  DateAxis,
  PriceAxis,
  PercentAxis,
  formatChartDateLong,
  formatPrice,
  safeDomain,
} from './_primitives'

/**
 * PriceHistoryChart — unified Layer-2b presentational chart.
 *
 * API contract (CHART-01 / D-06 + Discretion):
 *
 * Required props:
 *   - data {object[]} — pre-fetched, pre-merged array of HistoryPoint rows.
 *     Minimum keys: { date, close }. For full candle mode: also open, high, low,
 *     candleBody (array), candleUp (bool), volume. For comparison mode: date +
 *     keys matching each series[n].key. Regime rows may include `regime` and
 *     `regimeBar` keys after upstream merge.
 *
 *   - series {Array<{key:string, label:string, color?:string, isPrimary?:boolean}>}
 *     — at least one entry. series[0] is the primary series (formerly `ticker` in
 *     CumulativeReturnChart). series.length > 1 activates comparison (percent-return)
 *     mode. The primary series is expected to have isPrimary=true for clarity.
 *
 *   - intraday {boolean} — whether the data is intraday (1Min..1Hour) or daily.
 *     Computed upstream by the page composer from the period string via
 *     INTRADAY_KEYS.has(period) (see utils/periods.js). The chart never imports
 *     INTRADAY_KEYS directly — period is NOT a prop (D-06 Discretion: the chart
 *     receives only the boolean it needs, not the period vocabulary).
 *
 * Optional props (all have sensible defaults):
 *   - features {{ regime?, indicators?, volume?, candle? }} — feature bag (D-08).
 *     - regime: object of shape { data: { regimes, stats, source_ticker } } (matches
 *       the RegimeResponse schema returned by the /regime endpoint after Phase 1).
 *     - indicators: truthy to enable indicator toggle UI + subchart rendering.
 *     - volume: truthy to enable the volume subchart.
 *     - candle: truthy to enable candlestick mode (replaces the line series).
 *     Unknown keys (e.g., features.dailyReturnsHistogram from Phase 3) are silently
 *     ignored — this chart reads ONLY the keys listed above; it does NOT throw or
 *     warn on unrecognised keys (D-08 "silently ignored" Discretion).
 *   - height {number} default 280 — pixel height of the main price ResponsiveContainer.
 *   - loading {boolean} default false — forwarded to ChartFrame (D-04).
 *   - stale {boolean} default false — forwarded to ChartFrame; surfaces the Phase 1
 *     useApi 4-tuple stale flag so callers never silently serve stale data (D-04).
 *   - error {string|null} default null — forwarded to ChartFrame (D-04).
 *   - emptyMessage {string} default 'No data' — forwarded to ChartFrame.
 *   - currency {string} default 'USD' — passed to PriceAxis and formatPrice for
 *     currency-aware formatting (CHART-03 / B-08 — eliminates the hard-coded "$").
 *
 * CHART-02 / D-07 note: This component does NOT perform any data fetching internally
 * (CHART-01 / research/ARCHITECTURE.md anti-pattern #2). The caller (QuantitativeTab in
 * Plan 02-05) fetches, merges, and passes `data` pre-built. The cmpData stability bug
 * (B-12 / D-07) is closed by upstream design: QuantitativeTab passes a stable `data`
 * array reference that is memoised at the page-composer level. Do NOT add usePriceHistory
 * or useApi calls here — this is a display-only component.
 *
 * @param {object} props
 */
export default function PriceHistoryChart({
  data,
  series,
  intraday,
  features = {},
  height = 280,
  loading = false,
  stale = false,
  error = null,
  emptyMessage = 'No data',
  currency = 'USD',
}) {
  const colors = useChartColors()
  const REGIME_COLORS = colors.regime

  // Internal state: indicator toggles live here (D-Discretion — internal useState).
  // QuantitativeTab does not need to control which indicators are on/off.
  const [activeIndicators, setActiveIndicators] = useState(new Set())

  // showRegimes: default false (UX-conservative). Toggled by the Regimes button in the header.
  // Gated on features.regime?.data being truthy so the button only appears when regime data exists.
  const [showRegimes, setShowRegimes] = useState(false)

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  // Pre-compute OVERLAY_KEYS / SUBCHART_KEYS once (stable across renders).
  // bbands is type:'overlay' — it must NOT appear in SUBCHART_KEYS. The filter
  // on INDICATOR_DEFS guarantees this since INDICATOR_DEFS.bbands.type === 'overlay'.
  const OVERLAY_KEYS = useMemo(
    () => Object.entries(INDICATOR_DEFS).filter(([, v]) => v.type === 'overlay').map(([k]) => k),
    [],
  )
  const SUBCHART_KEYS = useMemo(
    () => Object.entries(INDICATOR_DEFS).filter(([, v]) => v.type === 'subchart').map(([k]) => k),
    [],
  )

  const toggleIndicator = (key) => {
    setActiveIndicators(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // --- Data-derived constants ---
  const primaryKey = series?.[0]?.key ?? 'close'
  const hasCompare = (series?.length ?? 0) > 1
  const compareSeries = hasCompare ? series.slice(1) : []
  const compareKeys = compareSeries.map(s => s.key)

  // Build date → regime lookup from the regime feature payload.
  // Gated on showRegimes so the map is empty (and per-row regime keys are skipped)
  // when regimes are toggled off — avoids unnecessary computation.
  const regimeMap = useMemo(() => {
    if (!showRegimes || !features.regime?.data?.regimes) return {}
    const map = {}
    for (const r of features.regime.data.regimes) {
      map[r.date] = r.regime
    }
    return map
  }, [showRegimes, features.regime])

  // Compute indicator values from raw OHLCV.
  // Ported from CumulativeReturnChart.jsx:60-69, gated on features.indicators truthy + data.
  const indicatorData = useMemo(() => {
    if (!features.indicators || !data || data.length === 0) return {}
    const result = {}
    for (const key of activeIndicators) {
      const def = INDICATOR_DEFS[key]
      if (!def) continue
      result[key] = def.compute(data)
    }
    return result
  }, [features.indicators, data, activeIndicators])

  // Build the main chart data array by merging history rows with regime, comparison,
  // and indicator overlay values.
  // Ported from CumulativeReturnChart.jsx:72-123 — the largest port. Renames:
  //   history → data, ticker → primaryKey, compareTickers → compareKeys,
  //   chartType === 'candle' → features.candle.
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return []
    const baseFirst = data[0].close

    return data.map((h, i) => {
      const dateKey = intraday ? h.date : h.date.slice(0, 10)
      const row = { date: dateKey }

      // Attach regime info when showRegimes is active
      const regimeKey = intraday ? dateKey : h.date.slice(0, 10)
      if (regimeMap[regimeKey] != null) {
        row.regime = regimeMap[regimeKey]
        row.regimeBar = 1
      }

      if (hasCompare) {
        // Comparison (percent-return) mode
        row[primaryKey] = ((h.close - baseFirst) / baseFirst) * 100
        compareKeys.forEach((sym) => {
          // In comparison mode the pre-merged data prop already contains keys for
          // each comparison ticker with pre-computed percent returns (merged by caller).
          if (h[sym] != null) {
            row[sym] = h[sym]
          }
        })
      } else {
        // Price mode
        row.close = h.close
        row.open = h.open
        row.high = h.high
        row.low = h.low
        row.candleBody = [Math.min(h.open ?? h.close, h.close), Math.max(h.open ?? h.close, h.close)]
        row.candleUp = (h.close ?? 0) >= (h.open ?? h.close)
        row.volume = h.volume

        // Add indicator overlay values
        if (features.indicators) {
          for (const key of activeIndicators) {
            const def = INDICATOR_DEFS[key]
            if (!def || def.type !== 'overlay') continue
            const vals = indicatorData[key]
            if (!vals) continue
            if (key === 'bbands') {
              row.bb_upper = vals.upper?.[i]
              row.bb_middle = vals.middle?.[i]
              row.bb_lower = vals.lower?.[i]
              // Range tuple for the band fill Area. recharts fills a band between
              // [lower, upper] when a dataKey resolves to a 2-tuple. Only set when
              // both bounds are finite so the warmup period (insufficient lookback)
              // leaves a gap rather than collapsing the fill to the axis.
              row.bb_range =
                vals.lower?.[i] != null && vals.upper?.[i] != null
                  ? [vals.lower[i], vals.upper[i]]
                  : null
            } else {
              row[key] = Array.isArray(vals) ? vals[i] : null
            }
          }
        }
      }
      return row
    })
  }, [data, hasCompare, primaryKey, compareKeys, intraday, regimeMap, activeIndicators, indicatorData, features.indicators, features.candle])

  // Build subchart data (one entry per active subchart indicator).
  // Ported from CumulativeReturnChart.jsx:126-151, rename: history → data.
  // NOTE: bbands is type:'overlay' and therefore never appears in activeSubcharts,
  // so it is never double-rendered. The INDICATOR_DEFS filter above enforces this.
  const subchartData = useMemo(() => {
    if (!features.indicators || !data || data.length === 0) return {}
    const result = {}
    for (const key of activeIndicators) {
      const def = INDICATOR_DEFS[key]
      if (!def || def.type !== 'subchart') continue
      const vals = indicatorData[key]
      if (!vals) continue
      result[key] = data.map((h, i) => {
        const row = { date: intraday ? h.date : h.date.slice(0, 10) }
        if (key === 'macd') {
          row.macd = vals.macdLine?.[i]
          row.signal = vals.signalLine?.[i]
          row.histogram = vals.histogram?.[i]
        } else if (key === 'stoch') {
          row.k = vals.k?.[i]
          row.d = vals.d?.[i]
        } else {
          row.value = Array.isArray(vals) ? vals[i] : null
        }
        return row
      })
    }
    return result
  }, [features.indicators, data, activeIndicators, indicatorData, intraday])

  // Y-axis domain.
  // Ported from CumulativeReturnChart.jsx:154-171.
  // Replaces inline Math.min/Math.max with safeDomain (closes B-14 / PRIM-02 acceptance).
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [0, 1]
    let values
    if (hasCompare) {
      const allKeys = [primaryKey, ...compareKeys]
      values = chartData.flatMap(d => allKeys.map(k => d[k]).filter(v => v != null))
    } else if (features.candle) {
      values = chartData.flatMap(d => [d.high, d.low].filter(v => v != null && v > 0))
    } else {
      values = chartData.map(d => d.close).filter(v => v != null)
    }
    return safeDomain(values)
  }, [chartData, hasCompare, primaryKey, compareKeys, features.candle])

  // Derived layout values
  const allKeys = hasCompare ? [primaryKey, ...compareKeys] : ['close']
  const xInterval = Math.max(0, Math.floor(chartData.length / 8))
  const activeOverlays = [...activeIndicators].filter(k => INDICATOR_DEFS[k]?.type === 'overlay')
  const activeSubcharts = [...activeIndicators].filter(k => INDICATOR_DEFS[k]?.type === 'subchart')

  // Tooltip label formatter — uses formatChartDateLong to avoid the TZ bug (PRIM-03).
  const tooltipLabelFormatter = (v) => {
    if (!v) return ''
    return formatChartDateLong(v, intraday)
  }

  // Tooltip value formatter for line mode — comparison shows %, price mode uses
  // formatPrice for currency-aware formatting (fixes BUG 1: raw float precision).
  const tooltipFormatter = (v, name) => {
    if (name === 'regimeBar') return null
    if (hasCompare) {
      return [`${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, name === primaryKey ? 'Return' : name]
    }
    return [formatPrice(v, currency), name === 'close' ? 'Price' : name]
  }

  // Custom tooltip content for candle mode — shows O/H/L/C with currency formatting.
  // Ported from CRC:299-321 with formatPrice substituted for the old formatY.
  // Rendered as raw <Tooltip content={...}> rather than <ChartTooltip> to bypass
  // ChartTooltip's .filter() logic which would drop the synthetic candleBody entries.
  const candleTooltipContent = ({ active, payload, label }) => {
    if (!active || !payload?.[0]) return null
    const d = payload[0].payload
    return (
      <div style={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
        <p style={{ color: '#fff', marginBottom: 4 }}>{formatChartDateLong(label, intraday)}</p>
        <p style={{ color: '#9CA3AF', margin: 0 }}>O: {formatPrice(d.open, currency)}</p>
        <p style={{ color: '#9CA3AF', margin: 0 }}>H: {formatPrice(d.high, currency)}</p>
        <p style={{ color: '#9CA3AF', margin: 0 }}>L: {formatPrice(d.low, currency)}</p>
        <p style={{ color: d.candleUp ? colors.positive : colors.negative, margin: 0 }}>C: {formatPrice(d.close, currency)}</p>
      </div>
    )
  }

  const regimeData = features.regime?.data ?? null

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      {/* Header row: title + regime toggle + period info */}
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center gap-2">
          <h3 className="text-white font-semibold">
            {hasCompare ? 'Cumulative Returns' : 'Price History'}
          </h3>

          {/* Regimes toggle button — gated on feature data being available (BUG 4 fix).
              Default off (showRegimes=false) so shading doesn't appear unexpectedly. */}
          {features.regime?.data && (
            <button
              onClick={() => setShowRegimes(s => !s)}
              className={`text-xs px-2 py-1 rounded ${
                showRegimes
                  ? 'bg-amber-600 text-white'
                  : 'bg-gray-700 text-gray-400 hover:text-white'
              }`}
            >
              Regimes
            </button>
          )}

          {/* Regime legend strip — only visible when showRegimes is active (CRC:202-213) */}
          {showRegimes && features.regime && regimeData?.stats && (
            <div className="flex items-center gap-1.5">
              {regimeData.source_ticker && regimeData.source_ticker !== primaryKey && (
                <span className="text-[10px] text-gray-500">via {regimeData.source_ticker}</span>
              )}
              {regimeData.stats.map(s => (
                <span key={s.regime} className="flex items-center gap-1 text-[10px] text-gray-400">
                  <span
                    className="inline-block w-2 h-2 rounded"
                    style={{ backgroundColor: REGIME_COLORS[s.regime] }}
                  />
                  R{s.regime} {s.volatility}%vol
                </span>
              ))}
            </div>
          )}
        </div>
        <span className="text-xs text-gray-500">{chartData.length} bars</span>
      </div>

      {/* Indicator toggle UI — gated on features.indicators, hidden in compare mode */}
      {features.indicators && !hasCompare && (
        <div className="flex flex-wrap gap-1 mb-3">
          <span className="text-xs text-gray-500 mr-1 self-center">Indicators:</span>
          {[...OVERLAY_KEYS, ...SUBCHART_KEYS].map(key => {
            const def = INDICATOR_DEFS[key]
            return (
              <button
                key={key}
                onClick={() => toggleIndicator(key)}
                className={`px-2 py-0.5 text-xs rounded ${
                  activeIndicators.has(key)
                    ? 'text-white'
                    : 'bg-gray-700 text-gray-400 hover:text-white hover:bg-gray-600'
                }`}
                style={activeIndicators.has(key) ? { backgroundColor: def.color, opacity: 0.9 } : {}}
              >
                {def.label}
              </button>
            )
          })}
        </div>
      )}

      {/* Main price chart wrapped in ChartFrame (D-04) */}
      <ChartFrame
        loading={loading}
        stale={stale}
        error={error}
        empty={chartData.length === 0}
        emptyMessage={emptyMessage}
      >
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />

            {/* Regime background shading — gated on showRegimes AND feature data (BUG 4 fix) */}
            {showRegimes && features.regime?.data && (
              <Bar
                yAxisId="regime"
                dataKey="regimeBar"
                legendType="none"
                isAnimationActive={false}
                shape={({ x, width, payload, background }) => {
                  if (payload.regime == null) return null
                  const areaY = background?.y ?? 5
                  const areaH = background?.height ?? 250
                  return (
                    <rect
                      x={x}
                      y={areaY}
                      width={width}
                      height={areaH}
                      fill={REGIME_COLORS[payload.regime]}
                      fillOpacity={0.12}
                    />
                  )
                }}
              />
            )}
            {/* Hidden regime yAxis always present when regime feature is enabled to keep axis IDs consistent */}
            {features.regime?.data && <YAxis yAxisId="regime" domain={[0, 1]} hide />}

            {/* X axis via DateAxis primitive (closes PRIM-02 / PRIM-03 UTC bug) */}
            <DateAxis intraday={intraday} interval={xInterval} />

            {/* Y axis: PriceAxis in price mode, PercentAxis in comparison mode */}
            {hasCompare ? (
              <PercentAxis domain={yDomain} />
            ) : (
              <PriceAxis domain={yDomain} currency={currency} />
            )}

            {/* Tooltip: candle mode uses a custom OHLC content function (BUG 2 fix);
                line/compare modes use the shared ChartTooltip primitive (SC1). */}
            {features.candle && !hasCompare ? (
              <Tooltip content={candleTooltipContent} />
            ) : (
              <ChartTooltip
                labelFormatter={tooltipLabelFormatter}
                formatter={tooltipFormatter}
              />
            )}

            {/* Multi-series legend in comparison mode */}
            {allKeys.length > 1 && (
              <Legend
                wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
                onClick={handleLegendClick}
                formatter={legendFormatter}
              />
            )}

            {/* Bollinger bands fill area — fills BETWEEN lower and upper via the
                bb_range [lower, upper] tuple. Using a distinct dataKey (not bb_upper)
                also prevents a duplicate bb_upper entry in the tooltip payload. */}
            {!hasCompare && activeIndicators.has('bbands') && (
              <Area
                type="monotone"
                dataKey="bb_range"
                stroke="none"
                fill="#6366F1"
                fillOpacity={0.1}
                isAnimationActive={false}
              />
            )}

            {/* Main price data: candle mode or line mode */}
            {!hasCompare && features.candle ? (
              <>
                {/* Candlestick bar — ported VERBATIM from CRC:329-363 (RESEARCH Finding 2) */}
                <Bar
                  dataKey="candleBody"
                  fill="none"
                  legendType="none"
                  isAnimationActive={false}
                  shape={(props) => {
                    const { x, y, width, height: barHeight, payload } = props
                    if (!payload || payload.high == null) return null
                    const barColor = payload.candleUp ? colors.positive : colors.negative
                    const bodyTop = Math.min(y, y + barHeight)
                    const bodyMid = x + width / 2

                    // Manual coordinate conversion — recharts Bar shape receives y/height
                    // for the body range but NOT for the wick (high/low are outside the
                    // Bar dataKey range). Re-derive from yDomain captured in enclosing scope.
                    const domain0 = yDomain[0]
                    const domain1 = yDomain[1]
                    const chartHeight = props.background?.height || 240
                    const chartY = props.background?.y || 20
                    const priceToY = (price) =>
                      chartY + chartHeight - ((price - domain0) / (domain1 - domain0)) * chartHeight

                    const wickTop = priceToY(payload.high)
                    const wickBottom = priceToY(payload.low)

                    return (
                      <g>
                        <line
                          x1={bodyMid}
                          y1={wickTop}
                          x2={bodyMid}
                          y2={wickBottom}
                          stroke={barColor}
                          strokeWidth={1}
                        />
                        <rect
                          x={x + 1}
                          y={bodyTop}
                          width={Math.max(width - 2, 2)}
                          height={Math.max(Math.abs(barHeight), 1)}
                          fill={barColor}
                          fillOpacity={payload.candleUp ? 0.3 : 0.9}
                          stroke={barColor}
                          strokeWidth={1}
                        />
                      </g>
                    )
                  }}
                />
              </>
            ) : (
              /* Line mode — single primary or multi-series comparison */
              allKeys.map((key, i) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={
                    series?.[i]?.color ?? colors.series[i % colors.series.length]
                  }
                  strokeWidth={i === 0 ? 2 : 1.5}
                  dot={false}
                  hide={isHidden(key)}
                  isAnimationActive={false}
                />
              ))
            )}

            {/* Overlay indicators (SMA, EMA, Bollinger, VWAP).
                bbands is type:'overlay' and rendered here only — never in the subchart
                loop below. This prevents duplicate dataKey="bb_upper" entries in the
                recharts payload that caused React key collisions (BUG 5 fix). */}
            {!hasCompare && activeOverlays.map(key => {
              const def = INDICATOR_DEFS[key]
              if (key === 'bbands') {
                return [
                  <Line
                    key="bb_upper"
                    type="monotone"
                    dataKey="bb_upper"
                    stroke={def.color}
                    strokeWidth={1}
                    strokeDasharray="3 3"
                    dot={false}
                    legendType="none"
                    isAnimationActive={false}
                  />,
                  <Line
                    key="bb_middle"
                    type="monotone"
                    dataKey="bb_middle"
                    stroke={def.color}
                    strokeWidth={1}
                    dot={false}
                    legendType="none"
                    isAnimationActive={false}
                  />,
                  <Line
                    key="bb_lower"
                    type="monotone"
                    dataKey="bb_lower"
                    stroke={def.color}
                    strokeWidth={1}
                    strokeDasharray="3 3"
                    dot={false}
                    legendType="none"
                    isAnimationActive={false}
                  />,
                ]
              }
              return (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={def.color}
                  strokeWidth={1.5}
                  dot={false}
                  legendType="none"
                  isAnimationActive={false}
                />
              )
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartFrame>

      {/* Volume subchart — gated on features.volume && !hasCompare (CRC:392-427).
          Heading sits above the chart (clearer than a rotated axis label that the
          price chart above used to clip); taller container for readability; bar
          fill routes through useChartColors so it tracks the colorblind toggle. */}
      {features.volume && !hasCompare && chartData.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-medium text-gray-400 mb-1">Volume</h4>
          <ResponsiveContainer width="100%" height={120}>
            <ComposedChart data={chartData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={false} />
              <YAxis
                tick={{ fill: '#9CA3AF', fontSize: 9 }}
                width={45}
                tickFormatter={v => {
                  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
                  if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`
                  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`
                  return v
                }}
              />
              <ChartTooltip
                labelFormatter={v => formatChartDateLong(v, intraday)}
                formatter={v => [v != null ? v.toLocaleString() : '', 'Volume']}
              />
              <Bar
                dataKey="volume"
                opacity={0.6}
                isAnimationActive={false}
                shape={({ x, y, width, height: barH, payload }) => (
                  <rect
                    x={x}
                    y={y}
                    width={width}
                    height={barH}
                    fill={payload?.candleUp ? colors.positive : colors.negative}
                    fillOpacity={0.5}
                  />
                )}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Indicator subcharts — gated on features.indicators && !hasCompare (CRC:429-473).
          bbands is type:'overlay' so it never appears in activeSubcharts and is never
          rendered here — the INDICATOR_DEFS filter guarantees zero overlap with the
          overlay Area/Lines rendered in the main chart above (BUG 5 fix). */}
      {features.indicators && !hasCompare && activeSubcharts.map(key => {
        const def = INDICATOR_DEFS[key]
        const subData = subchartData[key]
        if (!subData) return null

        return (
          <div key={key} className="mt-1">
            <ResponsiveContainer width="100%" height={100}>
              <ComposedChart data={subData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" tick={false} />
                <YAxis
                  tick={{ fill: '#9CA3AF', fontSize: 9 }}
                  domain={def.range || ['auto', 'auto']}
                  width={45}
                  label={{ value: def.label, angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 9, dx: -5 }}
                />
                <ChartTooltip />
                {def.lines && def.lines.map(v => (
                  <ReferenceLine key={v} y={v} stroke="#4B5563" strokeDasharray="3 3" />
                ))}
                {key === 'macd' ? (
                  <>
                    <Bar dataKey="histogram" fill={def.color} opacity={0.4} isAnimationActive={false} />
                    <Line type="monotone" dataKey="macd" stroke={def.color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    <Line type="monotone" dataKey="signal" stroke="#EF4444" strokeWidth={1} dot={false} isAnimationActive={false} />
                  </>
                ) : key === 'stoch' ? (
                  <>
                    <Line type="monotone" dataKey="k" stroke={def.color} strokeWidth={1.5} dot={false} name="%K" isAnimationActive={false} />
                    <Line type="monotone" dataKey="d" stroke="#EF4444" strokeWidth={1} dot={false} name="%D" isAnimationActive={false} />
                  </>
                ) : (
                  <Line type="monotone" dataKey="value" stroke={def.color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )
      })}
    </div>
  )
}
