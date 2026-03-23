import { useMemo, useState } from 'react'
import {
  ComposedChart, Line, Bar, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import { useLegendToggle } from '../hooks/useLegendToggle'
import { useChartColors } from '../hooks/useChartColors'
import { INDICATOR_DEFS } from '../utils/indicators'
import { INTRADAY_TO_HISTORY } from './PeriodSelector'

const OVERLAY_KEYS = Object.entries(INDICATOR_DEFS).filter(([, v]) => v.type === 'overlay').map(([k]) => k)
const SUBCHART_KEYS = Object.entries(INDICATOR_DEFS).filter(([, v]) => v.type === 'subchart').map(([k]) => k)
export default function CumulativeReturnChart({
  ticker, period = '1y', customStart = '', customEnd = '', compareTickers = [],
  regimeData = null,
}) {
  const colors = useChartColors()
  const REGIME_COLORS = colors.regime
  const [activeIndicators, setActiveIndicators] = useState(new Set())
  const [chartType, setChartType] = useState('line') // 'line' | 'candle'
  const [showRegimes, setShowRegimes] = useState(false)
  const intraday = INTRADAY_TO_HISTORY[period]
  const queryStr = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}&interval=1d`
    : intraday
      ? `period=${intraday.period}&interval=${intraday.interval}`
      : `period=${period}&interval=1d`

  const { data: history, loading } = useApi(`/research/asset/${ticker}/history?${queryStr}`)

  const { data: cmp0 } = useApi(compareTickers[0] ? `/research/asset/${compareTickers[0]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[0] })
  const { data: cmp1 } = useApi(compareTickers[1] ? `/research/asset/${compareTickers[1]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[1] })
  const { data: cmp2 } = useApi(compareTickers[2] ? `/research/asset/${compareTickers[2]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[2] })
  const { data: cmp3 } = useApi(compareTickers[3] ? `/research/asset/${compareTickers[3]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[3] })
  const cmpData = [cmp0, cmp1, cmp2, cmp3]

  // Build date → regime lookup from parent-provided data
  const regimeMap = useMemo(() => {
    if (!showRegimes || !regimeData?.regimes) return {}
    const map = {}
    for (const r of regimeData.regimes) {
      map[r.date] = r.regime
    }
    return map
  }, [showRegimes, regimeData])

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()
  const hasCompare = compareTickers.length > 0

  const toggleIndicator = (key) => {
    setActiveIndicators(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Compute indicators from raw OHLCV
  const indicatorData = useMemo(() => {
    if (!history || history.length === 0) return {}
    const result = {}
    for (const key of activeIndicators) {
      const def = INDICATOR_DEFS[key]
      if (!def) continue
      result[key] = def.compute(history)
    }
    return result
  }, [history, activeIndicators])

  // Build main chart data
  const chartData = useMemo(() => {
    if (!history || history.length === 0) return []
    const baseFirst = history[0].close

    return history.map((h, i) => {
      // For intraday data, keep full timestamp; for daily, truncate to date
      const dateKey = intraday ? h.date : h.date.slice(0, 10)
      const row = { date: dateKey }

      // Attach regime info if available — use full key for intraday, date-only for daily
      const regimeKey = intraday ? dateKey : h.date.slice(0, 10)
      if (regimeMap[regimeKey] != null) {
        row.regime = regimeMap[regimeKey]
        row.regimeBar = 1
      }

      if (hasCompare) {
        row[ticker] = ((h.close - baseFirst) / baseFirst) * 100
        compareTickers.forEach((sym, ci) => {
          const data = cmpData[ci]
          if (data && data[i] && data[0]) {
            row[sym] = ((data[i].close - data[0].close) / data[0].close) * 100
          }
        })
      } else {
        row.close = h.close
        row.open = h.open
        row.high = h.high
        row.low = h.low
        // Candle body range for Bar chart (open-close range)
        row.candleBody = [Math.min(h.open, h.close), Math.max(h.open, h.close)]
        row.candleUp = h.close >= h.open
        row.volume = h.volume
        // Add indicator overlay values
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
      return row
    })
  }, [history, cmpData, compareTickers, hasCompare, ticker, activeIndicators, indicatorData, regimeMap])

  // Build subchart data
  const subchartData = useMemo(() => {
    if (!history || history.length === 0) return {}
    const result = {}
    for (const key of activeIndicators) {
      const def = INDICATOR_DEFS[key]
      if (!def || def.type !== 'subchart') continue
      const vals = indicatorData[key]
      if (!vals) continue

      result[key] = history.map((h, i) => {
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
  }, [history, activeIndicators, indicatorData])

  // Y-axis domain
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [0, 1]
    let values
    if (hasCompare) {
      const allKeys = [ticker, ...compareTickers]
      values = chartData.flatMap(d => allKeys.map(k => d[k]).filter(v => v != null))
    } else if (chartType === 'candle') {
      // Use high/low for candlestick mode
      values = chartData.flatMap(d => [d.high, d.low].filter(v => v != null && v > 0))
    } else {
      values = chartData.map(d => d.close).filter(v => v != null)
    }
    if (values.length === 0) return [0, 1]
    const min = Math.min(...values)
    const max = Math.max(...values)
    const padding = (max - min) * 0.05 || Math.abs(max) * 0.02 || 1
    return [min - padding, max + padding]
  }, [chartData, hasCompare, ticker, compareTickers, chartType])

  const formatY = hasCompare
    ? (v) => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`
    : (v) => {
        if (v >= 1000) return `$${(v / 1000).toFixed(1)}k`
        if (v >= 1) return `$${v.toFixed(2)}`
        return `$${v.toFixed(4)}`
      }

  const periodLabel = customStart && customEnd
    ? `${customStart} to ${customEnd}` : period.toUpperCase()
  const allKeys = hasCompare ? [ticker, ...compareTickers] : ['close']
  const xInterval = Math.max(0, Math.floor(chartData.length / 8))

  const activeOverlays = [...activeIndicators].filter(k => INDICATOR_DEFS[k]?.type === 'overlay')
  const activeSubcharts = [...activeIndicators].filter(k => INDICATOR_DEFS[k]?.type === 'subchart')

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center gap-2">
          <h3 className="text-white font-semibold">{hasCompare ? 'Cumulative Returns' : 'Price History'}</h3>
          <button
            onClick={() => setShowRegimes(!showRegimes)}
            className={`px-2 py-0.5 text-xs rounded ${
              showRegimes ? 'bg-amber-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'
            }`}
          >
            Regimes
          </button>
          {showRegimes && regimeData?.stats && (
            <div className="flex items-center gap-1.5">
              {regimeData.source_ticker && regimeData.source_ticker !== ticker && (
                <span className="text-[10px] text-gray-500">via {regimeData.source_ticker}</span>
              )}
              {regimeData.stats.map(s => (
                <span key={s.regime} className="flex items-center gap-1 text-[10px] text-gray-400">
                  <span className="inline-block w-2 h-2 rounded"
                    style={{ backgroundColor: REGIME_COLORS[s.regime] }} />
                  R{s.regime} {s.volatility}%vol
                </span>
              ))}
            </div>
          )}
        </div>
        <span className="text-xs text-gray-500">{periodLabel} · {chartData.length} days</span>
      </div>

      {/* Chart type + Indicator toggles */}
      {!hasCompare && (
        <div className="flex flex-wrap gap-1 mb-3">
          <button
            onClick={() => setChartType(chartType === 'line' ? 'candle' : 'line')}
            className={`px-2 py-0.5 text-xs rounded mr-2 ${
              chartType === 'candle' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'
            }`}
          >
            {chartType === 'candle' ? 'Candlestick' : 'Line'}
          </button>
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

      {loading && <p className="text-gray-500 text-sm py-8 text-center">Loading...</p>}

      {/* Main price chart */}
      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            {/* Regime background shading */}
            {showRegimes && (
              <Bar yAxisId="regime" dataKey="regimeBar" legendType="none" isAnimationActive={false}
                shape={({ x, width, payload, background }) => {
                  if (payload.regime == null) return null
                  const areaY = background?.y ?? 5
                  const areaH = background?.height ?? 250
                  return (
                    <rect x={x} y={areaY} width={width} height={areaH}
                      fill={REGIME_COLORS[payload.regime]} fillOpacity={0.12} />
                  )
                }}
              />
            )}
            <YAxis yAxisId="regime" domain={[0, 1]} hide />
            <XAxis dataKey="date" tick={{ fill: '#9CA3AF', fontSize: 10 }} interval={xInterval}
              tickFormatter={v => {
                if (intraday) {
                  // Show "Mar 23 15:30" for intraday
                  const d = new Date(v)
                  if (isNaN(d)) return v.slice(5, 16).replace('T', ' ')
                  return d.toLocaleDateString('en', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit', hour12: false })
                }
                const d = new Date(v + 'T00:00:00')
                return d.toLocaleDateString('en', { month: 'short', year: 'numeric' })
              }} />
            <YAxis
              tick={{ fill: '#9CA3AF', fontSize: 11 }}
              domain={yDomain}
              tickFormatter={formatY}
              label={{ value: hasCompare ? 'Return (%)' : 'Price', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
            />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
              labelStyle={{ color: '#fff' }}
              labelFormatter={v => {
                if (intraday) return v.length > 10 ? v.slice(0, 16).replace('T', ' ') : v
                const d = new Date(v + 'T00:00:00')
                return d.toLocaleDateString('en', { day: 'numeric', month: 'short', year: 'numeric' })
              }}
              content={!hasCompare && chartType === 'candle' ? ({ active, payload, label }) => {
                if (!active || !payload?.[0]) return null
                const d = payload[0].payload
                const fmtLabel = (() => { const dt = new Date(label + 'T00:00:00'); return dt.toLocaleDateString('en', { day: 'numeric', month: 'short', year: 'numeric' }) })()
                return (
                  <div style={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
                    <p style={{ color: '#fff', marginBottom: 4 }}>{fmtLabel}</p>
                    <p style={{ color: '#9CA3AF', margin: 0 }}>O: {formatY(d.open)}</p>
                    <p style={{ color: '#9CA3AF', margin: 0 }}>H: {formatY(d.high)}</p>
                    <p style={{ color: '#9CA3AF', margin: 0 }}>L: {formatY(d.low)}</p>
                    <p style={{ color: d.candleUp ? colors.positive : colors.negative, margin: 0 }}>C: {formatY(d.close)}</p>
                  </div>
                )
              } : undefined}
              formatter={!hasCompare && chartType === 'candle' ? undefined : (v, name) => {
                if (name === 'regimeBar') return null
                return [
                  hasCompare ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : formatY(v),
                  name === 'close' ? 'Price' : name,
                ]
              }}
            />
            {allKeys.length > 1 && (
              <Legend wrapperStyle={{ fontSize: 11, cursor: 'pointer' }} onClick={handleLegendClick} formatter={legendFormatter} />
            )}
            {/* Bollinger bands area */}
            {activeIndicators.has('bbands') && (
              <Area type="monotone" dataKey="bb_upper" stroke="none" fill="#6366F1" fillOpacity={0.1} />
            )}
            {/* Main price data */}
            {!hasCompare && chartType === 'candle' ? (
              <>
                {/* Candlestick wicks (high-low as thin line) */}
                <Bar dataKey="candleBody" fill="none" legendType="none"
                  shape={(props) => {
                    const { x, y, width, height, payload } = props
                    if (!payload || payload.high == null) return null
                    const barColor = payload.candleUp ? colors.positive : colors.negative
                    const bodyTop = Math.min(y, y + height)
                    const bodyMid = x + width / 2

                    // For wick, we need to use the YAxis scale
                    // The Bar y/height already maps open/close; we need high/low relative
                    const domain0 = yDomain[0], domain1 = yDomain[1]
                    const chartHeight = props.background?.height || 240
                    const chartY = props.background?.y || 20
                    const priceToY = (price) => chartY + chartHeight - ((price - domain0) / (domain1 - domain0)) * chartHeight

                    const wickTop = priceToY(payload.high)
                    const wickBottom = priceToY(payload.low)

                    return (
                      <g>
                        {/* Wick */}
                        <line x1={bodyMid} y1={wickTop} x2={bodyMid} y2={wickBottom}
                          stroke={barColor} strokeWidth={1} />
                        {/* Body */}
                        <rect x={x + 1} y={bodyTop} width={Math.max(width - 2, 2)} height={Math.max(Math.abs(height), 1)}
                          fill={payload.candleUp ? barColor : barColor}
                          fillOpacity={payload.candleUp ? 0.3 : 0.9}
                          stroke={barColor} strokeWidth={1} />
                      </g>
                    )
                  }}
                />
              </>
            ) : (
              /* Line mode */
              allKeys.map((key, i) => (
                <Line key={key} type="monotone" dataKey={key}
                  stroke={colors.series[i % colors.series.length]}
                  strokeWidth={i === 0 ? 2 : 1.5} dot={false} hide={isHidden(key)} />
              ))
            )}
            {/* Overlay indicators */}
            {!hasCompare && activeOverlays.map(key => {
              const def = INDICATOR_DEFS[key]
              if (key === 'bbands') {
                return [
                  <Line key="bb_upper" type="monotone" dataKey="bb_upper" stroke={def.color} strokeWidth={1} strokeDasharray="3 3" dot={false} legendType="none" />,
                  <Line key="bb_middle" type="monotone" dataKey="bb_middle" stroke={def.color} strokeWidth={1} dot={false} legendType="none" />,
                  <Line key="bb_lower" type="monotone" dataKey="bb_lower" stroke={def.color} strokeWidth={1} strokeDasharray="3 3" dot={false} legendType="none" />,
                ]
              }
              return (
                <Line key={key} type="monotone" dataKey={key}
                  stroke={def.color} strokeWidth={1.5} dot={false} legendType="none" />
              )
            })}
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Volume chart */}
      {!loading && !hasCompare && chartData.length > 0 && (
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
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#fff' }}
              labelFormatter={v => {
                if (intraday) return v.length > 10 ? v.slice(0, 16).replace('T', ' ') : v
                const d = new Date(v + 'T00:00:00')
                return d.toLocaleDateString('en', { day: 'numeric', month: 'short', year: 'numeric' })
              }}
              formatter={v => [v.toLocaleString(), 'Volume']}
            />
            <Bar dataKey="volume" fill="#6366F1" opacity={0.6} isAnimationActive={false}
              shape={({ x, y, width, height, payload }) => (
                <rect x={x} y={y} width={width} height={height}
                  fill={payload.candleUp ? '#22C55E' : '#EF4444'} fillOpacity={0.5} />
              )}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Subcharts */}
      {!hasCompare && activeSubcharts.map(key => {
        const def = INDICATOR_DEFS[key]
        const data = subchartData[key]
        if (!data) return null

        return (
          <div key={key} className="mt-1">
            <ResponsiveContainer width="100%" height={100}>
              <ComposedChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" tick={false} />
                <YAxis
                  tick={{ fill: '#9CA3AF', fontSize: 9 }}
                  domain={def.range || ['auto', 'auto']}
                  width={45}
                  label={{ value: def.label, angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 9, dx: -5 }}
                />
                <Tooltip
                  contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: '#fff' }}
                />
                {/* Reference lines for RSI/Stochastic */}
                {def.lines && def.lines.map(v => (
                  <ReferenceLine key={v} y={v} stroke="#4B5563" strokeDasharray="3 3" />
                ))}
                {key === 'macd' ? (
                  <>
                    <Bar dataKey="histogram" fill={def.color} opacity={0.4} />
                    <Line type="monotone" dataKey="macd" stroke={def.color} strokeWidth={1.5} dot={false} />
                    <Line type="monotone" dataKey="signal" stroke="#EF4444" strokeWidth={1} dot={false} />
                  </>
                ) : key === 'stoch' ? (
                  <>
                    <Line type="monotone" dataKey="k" stroke={def.color} strokeWidth={1.5} dot={false} name="%K" />
                    <Line type="monotone" dataKey="d" stroke="#EF4444" strokeWidth={1} dot={false} name="%D" />
                  </>
                ) : (
                  <Line type="monotone" dataKey="value" stroke={def.color} strokeWidth={1.5} dot={false} />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )
      })}

      {!loading && chartData.length === 0 && (
        <p className="text-gray-500 text-sm py-8 text-center">No history data available</p>
      )}
    </div>
  )
}
