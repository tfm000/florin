import { useMemo, useState } from 'react'
import { ComposedChart, Bar, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useLegendToggle } from '../hooks/useLegendToggle'
import { useChartColors } from '../hooks/useChartColors'

const NUM_BINS = 40
const REGIME_COLORS = ['#22C55E', '#EF4444', '#F59E0B']

function computeReturns(history) {
  if (!history || history.length < 2) return []
  const returns = []
  for (let i = 1; i < history.length; i++) {
    const prev = history[i - 1].close
    const curr = history[i].close
    if (prev > 0 && curr > 0) {
      returns.push(((curr - prev) / prev) * 100)
    }
  }
  return returns
}

// Stats for regime splits only (inherently client-side since the split is UI state).
// Main ticker/compare ticker stats come from the /stats/returns/ API.
function computeRegimeStats(returns) {
  if (returns.length === 0) return null
  const n = returns.length
  const mean = returns.reduce((s, r) => s + r, 0) / n
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (n - 1)
  const stdDev = Math.sqrt(variance)
  const skewness = n > 2 && stdDev > 0
    ? (n / ((n - 1) * (n - 2))) * returns.reduce((s, r) => s + ((r - mean) / stdDev) ** 3, 0)
    : 0
  const kurtosis = n > 3 && stdDev > 0
    ? (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) *
      returns.reduce((s, r) => s + ((r - mean) / stdDev) ** 4, 0) -
      3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    : 0

  const sorted = [...returns].sort((a, b) => a - b)
  const varIdx = Math.max(0, Math.floor(0.05 * n) - 1)
  const var95 = sorted[varIdx]
  const tailSlice = sorted.slice(0, varIdx + 1)
  const cvar95 = tailSlice.length > 0
    ? tailSlice.reduce((s, r) => s + r, 0) / tailSlice.length
    : var95
  const sharpe = stdDev > 0 ? (mean / stdDev) * Math.sqrt(252) : 0

  return { mean, stdDev, skewness, kurtosis, var95, cvar95, sharpe, n }
}

// Convert API stats response to the format used in the stats table
function apiStatsToDisplay(apiStats) {
  if (!apiStats) return null
  return {
    mean: apiStats.mean_daily_pct,
    stdDev: apiStats.std_dev_daily_pct,
    skewness: apiStats.skewness,
    kurtosis: apiStats.excess_kurtosis,
    var95: apiStats.var_95_pct,
    cvar95: apiStats.cvar_95_pct,
    sharpe: apiStats.sharpe,
    n: apiStats.trading_days,
  }
}

function buildBins(returns, globalMin, globalMax) {
  if (returns.length === 0 || globalMax === globalMin) return new Array(NUM_BINS).fill(0)
  const binWidth = (globalMax - globalMin) / NUM_BINS
  const counts = new Array(NUM_BINS).fill(0)
  for (const r of returns) {
    let idx = Math.floor((r - globalMin) / binWidth)
    if (idx >= NUM_BINS) idx = NUM_BINS - 1
    if (idx < 0) idx = 0
    counts[idx]++
  }
  return counts
}

export default function ReturnsHistogram({
  ticker, period = '1y', customStart = '', customEnd = '', compareTickers = [],
  regimeData = null,
}) {
  const colors = useChartColors()
  const [showRegimes, setShowRegimes] = useState(false)

  const queryStr = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}&interval=1d`
    : `period=${period}&interval=1d`

  const statsQueryStr = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}`
    : `period=${period}`

  const { data: history, loading } = useApi(`/research/asset/${ticker}/history?${queryStr}`)
  const { data: cmp0 } = useApi(compareTickers[0] ? `/research/asset/${compareTickers[0]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[0] })
  const { data: cmp1 } = useApi(compareTickers[1] ? `/research/asset/${compareTickers[1]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[1] })
  const { data: cmp2 } = useApi(compareTickers[2] ? `/research/asset/${compareTickers[2]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[2] })
  const { data: cmp3 } = useApi(compareTickers[3] ? `/research/asset/${compareTickers[3]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[3] })
  const cmpData = [cmp0, cmp1, cmp2, cmp3]

  // Fetch canonical stats from API for each ticker
  const { data: apiStats0 } = useApi(`/stats/returns/${ticker}?${statsQueryStr}`)
  const { data: apiStatsCmp0 } = useApi(compareTickers[0] ? `/stats/returns/${compareTickers[0]}?${statsQueryStr}` : null, { autoFetch: !!compareTickers[0] })
  const { data: apiStatsCmp1 } = useApi(compareTickers[1] ? `/stats/returns/${compareTickers[1]}?${statsQueryStr}` : null, { autoFetch: !!compareTickers[1] })
  const { data: apiStatsCmp2 } = useApi(compareTickers[2] ? `/stats/returns/${compareTickers[2]}?${statsQueryStr}` : null, { autoFetch: !!compareTickers[2] })
  const { data: apiStatsCmp3 } = useApi(compareTickers[3] ? `/stats/returns/${compareTickers[3]}?${statsQueryStr}` : null, { autoFetch: !!compareTickers[3] })
  const apiStatsAll = [apiStatsCmp0, apiStatsCmp1, apiStatsCmp2, apiStatsCmp3]

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  const allTickers = [ticker, ...compareTickers]

  // Build date → regime lookup
  const regimeMap = useMemo(() => {
    if (!showRegimes || !regimeData?.regimes) return {}
    const map = {}
    for (const r of regimeData.regimes) {
      map[r.date] = r.regime
    }
    return map
  }, [showRegimes, regimeData])

  // Number of regimes detected
  const nRegimes = regimeData?.stats?.length || 0
  const regimeKeys = useMemo(() =>
    Array.from({ length: nRegimes }, (_, i) => `regime_${i}`),
    [nRegimes]
  )

  const { chartData, allStats, regimeStats } = useMemo(() => {
    const allReturns = {}
    allReturns[ticker] = computeReturns(history)
    compareTickers.forEach((sym, i) => {
      allReturns[sym] = computeReturns(cmpData[i])
    })

    // Split returns by regime if active
    const regimeReturns = {}
    if (showRegimes && history && history.length > 1 && Object.keys(regimeMap).length > 0) {
      for (let i = 1; i < history.length; i++) {
        const prev = history[i - 1].close
        const curr = history[i].close
        if (prev <= 0 || curr <= 0) continue
        const dateKey = history[i].date.slice(0, 10)
        const regime = regimeMap[dateKey]
        if (regime == null) continue
        const key = `regime_${regime}`
        if (!regimeReturns[key]) regimeReturns[key] = []
        regimeReturns[key].push(((curr - prev) / prev) * 100)
      }
    }

    // Global min/max for consistent bin boundaries across all series
    const allValues = showRegimes && Object.keys(regimeReturns).length > 0
      ? Object.values(regimeReturns).flat()
      : Object.values(allReturns).flat()
    if (allValues.length === 0) return { chartData: [], allStats: {}, regimeStats: {} }
    const globalMin = Math.min(...allValues)
    const globalMax = Math.max(...allValues)
    const binWidth = (globalMax - globalMin) / NUM_BINS

    let chartData
    if (showRegimes && Object.keys(regimeReturns).length > 0) {
      // Build bins for each regime
      const binArrays = {}
      for (const [key, returns] of Object.entries(regimeReturns)) {
        binArrays[key] = buildBins(returns, globalMin, globalMax)
      }
      chartData = Array.from({ length: NUM_BINS }, (_, i) => {
        const mid = globalMin + (i + 0.5) * binWidth
        const row = { bin: mid }
        for (const key of Object.keys(regimeReturns)) {
          row[key] = binArrays[key]?.[i] || 0
        }
        return row
      })
    } else {
      // Normal mode: bins per ticker
      const binArrays = {}
      for (const [sym, returns] of Object.entries(allReturns)) {
        binArrays[sym] = buildBins(returns, globalMin, globalMax)
      }
      chartData = Array.from({ length: NUM_BINS }, (_, i) => {
        const mid = globalMin + (i + 0.5) * binWidth
        const row = { bin: mid }
        for (const sym of allTickers) {
          row[sym] = binArrays[sym]?.[i] || 0
        }
        return row
      })
    }

    // Use API-fetched stats for main + compare tickers (canonical, server-side)
    const allStats = {}
    allStats[ticker] = apiStatsToDisplay(apiStats0)
    compareTickers.forEach((sym, i) => {
      allStats[sym] = apiStatsToDisplay(apiStatsAll[i])
    })

    // Regime stats still computed client-side (per-regime split is UI state)
    const regimeStats = {}
    for (const [key, returns] of Object.entries(regimeReturns)) {
      regimeStats[key] = computeRegimeStats(returns)
    }

    return { chartData, allStats, regimeStats }
  }, [history, cmpData, ticker, compareTickers, allTickers, showRegimes, regimeMap, apiStats0, apiStatsAll])

  if (loading) return <p className="text-gray-500 text-sm py-4 text-center">Loading...</p>
  if (chartData.length === 0) return null

  const primaryStats = allStats[ticker]
  const periodLabel = customStart && customEnd
    ? `${customStart} to ${customEnd}`
    : period.toUpperCase()

  const showingRegimes = showRegimes && regimeKeys.length > 0 && Object.keys(regimeStats).length > 0

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-white font-semibold">Daily Returns Distribution</h3>
          <button
            onClick={() => setShowRegimes(!showRegimes)}
            className={`px-2 py-0.5 text-xs rounded ${
              showRegimes ? 'bg-amber-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'
            }`}
          >
            Regimes
          </button>
        </div>
        <span className="text-xs text-gray-500">{primaryStats?.n || 0} days · {periodLabel}</span>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={chartData} barCategoryGap={0} barGap={0}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
          <XAxis
            dataKey="bin"
            tick={{ fill: '#9CA3AF', fontSize: 10 }}
            tickFormatter={v => `${v.toFixed(0)}%`}
            interval={Math.max(0, Math.floor(chartData.length / 8))}
            label={{ value: 'Daily Return (%)', position: 'insideBottom', offset: -2, fill: '#6B7280', fontSize: 10 }}
          />
          <YAxis
            tick={{ fill: '#9CA3AF', fontSize: 10 }}
            label={{ value: 'Frequency', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
          />
          <Tooltip
            contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#fff' }}
            labelFormatter={v => `Return: ${Number(v).toFixed(2)}%`}
            formatter={(v, name) => {
              const label = name.startsWith('regime_')
                ? `Regime ${name.split('_')[1]} (${REGIME_COLORS[Number(name.split('_')[1])] ? ['Low Vol', 'High Vol', 'Med Vol'][Number(name.split('_')[1])] : name})`
                : name
              return [v, label]
            }}
          />
          <ReferenceLine x={0} stroke="#6B7280" strokeWidth={1} />
          {!showingRegimes && primaryStats && (
            <ReferenceLine x={primaryStats.mean} stroke="#F59E0B" strokeDasharray="4 4" strokeWidth={1.5}
              label={{ value: `μ=${primaryStats.mean.toFixed(2)}%`, fill: '#F59E0B', fontSize: 9, position: 'top' }}
            />
          )}
          <Legend
            wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
            onClick={handleLegendClick}
            formatter={(value, entry) => {
              const label = value.startsWith('regime_')
                ? `Regime ${value.split('_')[1]} (${['Low Vol', 'High Vol', 'Med Vol'][Number(value.split('_')[1])] || ''})`
                : value
              return legendFormatter(label, entry)
            }}
          />
          {showingRegimes ? (
            regimeKeys.map((key) => {
              const idx = Number(key.split('_')[1])
              return (
                <Area key={key} type="step" dataKey={key}
                  fill={REGIME_COLORS[idx]} fillOpacity={0.35}
                  stroke={REGIME_COLORS[idx]} strokeWidth={1.5}
                  hide={isHidden(key)}
                />
              )
            })
          ) : (
            allTickers.map((sym, i) => (
              <Bar
                key={sym}
                dataKey={sym}
                fill={colors.series[i % colors.series.length]}
                opacity={allTickers.length > 1 ? 0.6 : 0.9}
                radius={[2, 2, 0, 0]}
                hide={isHidden(sym)}
              />
            ))
          )}
        </ComposedChart>
      </ResponsiveContainer>

      {/* Stats table */}
      <div className="overflow-x-auto mt-3">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500">
              <th className="text-left px-2 py-1">{showingRegimes ? 'Regime' : 'Ticker'}</th>
              <th className="text-right px-2 py-1">Mean</th>
              <th className="text-right px-2 py-1">Std Dev</th>
              <th className="text-right px-2 py-1">Skew</th>
              <th className="text-right px-2 py-1">Ex. Kurt</th>
              <th className="text-right px-2 py-1">VaR 95%</th>
              <th className="text-right px-2 py-1">CVaR 95%</th>
              <th className="text-right px-2 py-1">Sharpe</th>
              <th className="text-right px-2 py-1">Days</th>
            </tr>
          </thead>
          <tbody>
            {showingRegimes ? (
              regimeKeys.map((key) => {
                const s = regimeStats[key]
                if (!s) return null
                const idx = Number(key.split('_')[1])
                return (
                  <tr key={key} className="text-white">
                    <td className="px-2 py-1 font-mono flex items-center gap-1">
                      <span className="inline-block w-2 h-2 rounded"
                        style={{ backgroundColor: REGIME_COLORS[idx] }} />
                      R{idx} ({['Low Vol', 'High Vol', 'Med Vol'][idx]})
                    </td>
                    <td className={`text-right px-2 py-1 font-mono ${s.mean >= 0 ? 'text-green-400' : 'text-red-400'}`}>{s.mean.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{s.stdDev.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{s.skewness.toFixed(3)}</td>
                    <td className="text-right px-2 py-1 font-mono">{s.kurtosis.toFixed(3)}</td>
                    <td className="text-right px-2 py-1 font-mono text-red-400">{s.var95.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono text-red-400">{s.cvar95.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{s.sharpe.toFixed(2)}</td>
                    <td className="text-right px-2 py-1 font-mono text-gray-400">{s.n}</td>
                  </tr>
                )
              })
            ) : (
              allTickers.map((sym, i) => {
                const s = allStats[sym]
                if (!s) return null
                return (
                  <tr key={sym} className="text-white">
                    <td className="px-2 py-1 font-mono" style={{ color: colors.series[i % colors.series.length] }}>{sym}</td>
                    <td className={`text-right px-2 py-1 font-mono ${s.mean >= 0 ? 'text-green-400' : 'text-red-400'}`}>{s.mean.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{s.stdDev.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{s.skewness.toFixed(3)}</td>
                    <td className="text-right px-2 py-1 font-mono">{s.kurtosis.toFixed(3)}</td>
                    <td className="text-right px-2 py-1 font-mono text-red-400">{s.var95.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono text-red-400">{s.cvar95.toFixed(3)}%</td>
                    <td className="text-right px-2 py-1 font-mono">{s.sharpe.toFixed(2)}</td>
                    <td className="text-right px-2 py-1 font-mono text-gray-400">{s.n}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
