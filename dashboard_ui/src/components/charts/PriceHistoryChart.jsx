import { useMemo, useState } from 'react'
import {
  ComposedChart, Line, Bar, Area, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Legend, ReferenceLine,
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
 *   - currency {string} default 'USD' — passed to PriceAxis for currency-aware
 *     formatting (CHART-03 / B-08 — eliminates the hard-coded "$" from CRC:175-179).
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

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  // Pre-compute OVERLAY_KEYS / SUBCHART_KEYS once (stable across renders)
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
  // Ported from CumulativeReturnChart.jsx:38-45, gated on features.regime?.data?.regimes.
  const regimeMap = useMemo(() => {
    if (!features.regime?.data?.regimes) return {}
    const map = {}
    for (const r of features.regime.data.regimes) {
      map[r.date] = r.regime
    }
    return map
  }, [features.regime])

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

      // Attach regime info when available
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
          // If the key is present, use it directly; otherwise leave undefined.
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
    if (intraday) return v.length > 10 ? v.slice(0, 16).replace('T', ' ') : v
    return formatChartDateLong(v, false)
  }

  // Tooltip value formatter — comparison mode shows %, price mode shows currency via PriceAxis formatter pattern.
  const tooltipFormatter = (v, name) => {
    if (name === 'regimeBar') return null
    if (hasCompare) {
      return [`${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, name === primaryKey ? 'Return' : name]
    }
    return [v, name === 'close' ? 'Price' : name]
  }

  const regimeData = features.regime?.data ?? null

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      {/* Header row: regime legend + period info */}
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center gap-2">
          <h3 className="text-white font-semibold">
            {hasCompare ? 'Cumulative Returns' : 'Price History'}
          </h3>
          {/* Regime legend strip — gated on features.regime?.data?.stats (CRC:202-213) */}
          {features.regime && regimeData?.stats && (
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

            {/* Regime background shading — gated on features.regime (CRC:259-272) */}
            {features.regime && (
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
            {/* Hidden regime yAxis required when regime shading is active */}
            <YAxis yAxisId="regime" domain={[0, 1]} hide />

            {/* X axis via DateAxis primitive (closes PRIM-02 / PRIM-03 UTC bug) */}
            <DateAxis intraday={intraday} interval={xInterval} />

            {/* Y axis: PriceAxis in price mode, PercentAxis in comparison mode */}
            {hasCompare ? (
              <PercentAxis domain={yDomain} />
            ) : (
              <PriceAxis domain={yDomain} currency={currency} />
            )}

            {/* Single ChartTooltip site replacing CRC's 3 inline Tooltip sites (SC1) */}
            <ChartTooltip
              labelFormatter={tooltipLabelFormatter}
              formatter={tooltipFormatter}
            />

            {/* Multi-series legend in comparison mode */}
            {allKeys.length > 1 && (
              <Legend
                wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
                onClick={handleLegendClick}
                formatter={legendFormatter}
              />
            )}

            {/* Bollinger bands fill area (behind lines) */}
            {!hasCompare && activeIndicators.has('bbands') && (
              <Area
                type="monotone"
                dataKey="bb_upper"
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
                    // useYAxisScale() is NOT usable here (React hook rules prohibit hook calls
                    // inside a non-hook callback). RESEARCH.md Finding 2 confirms this pattern.
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

            {/* Overlay indicators (SMA, EMA, Bollinger, VWAP) */}
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

      {/* Volume subchart — gated on features.volume && !hasCompare (CRC:392-427) */}
      {features.volume && !hasCompare && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={80}>
          <ComposedChart data={chartData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
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
              label={{ value: 'Volume', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 9, dx: -5 }}
            />
            <ChartTooltip
              labelFormatter={v => {
                if (!v) return ''
                if (intraday) return v.length > 10 ? v.slice(0, 16).replace('T', ' ') : v
                return formatChartDateLong(v, false)
              }}
              formatter={v => [v != null ? v.toLocaleString() : '', 'Volume']}
            />
            <Bar
              dataKey="volume"
              fill="#6366F1"
              opacity={0.6}
              isAnimationActive={false}
              shape={({ x, y, width, height: barH, payload }) => (
                <rect
                  x={x}
                  y={y}
                  width={width}
                  height={barH}
                  fill={payload?.candleUp ? '#22C55E' : '#EF4444'}
                  fillOpacity={0.5}
                />
              )}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Indicator subcharts — gated on features.indicators && !hasCompare (CRC:429-473) */}
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
