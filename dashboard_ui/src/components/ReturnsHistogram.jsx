import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useLegendToggle } from '../hooks/useLegendToggle'

const NUM_BINS = 40
const COLORS = ['#22C55E', '#6366F1', '#F59E0B', '#EF4444', '#EC4899']

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

function computeStats(returns) {
  if (returns.length === 0) return null
  const mean = returns.reduce((s, r) => s + r, 0) / returns.length
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / returns.length
  const stdDev = Math.sqrt(variance)
  const skewness = stdDev > 0 ? returns.reduce((s, r) => s + ((r - mean) / stdDev) ** 3, 0) / returns.length : 0
  const kurtosis = stdDev > 0 ? returns.reduce((s, r) => s + ((r - mean) / stdDev) ** 4, 0) / returns.length - 3 : 0
  return { mean, stdDev, skewness, kurtosis, n: returns.length }
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
}) {
  const queryStr = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}&interval=1d`
    : `period=${period}&interval=1d`

  const { data: history, loading } = useApi(`/research/asset/${ticker}/history?${queryStr}`)
  const { data: cmp0 } = useApi(compareTickers[0] ? `/research/asset/${compareTickers[0]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[0] })
  const { data: cmp1 } = useApi(compareTickers[1] ? `/research/asset/${compareTickers[1]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[1] })
  const { data: cmp2 } = useApi(compareTickers[2] ? `/research/asset/${compareTickers[2]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[2] })
  const { data: cmp3 } = useApi(compareTickers[3] ? `/research/asset/${compareTickers[3]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[3] })
  const cmpData = [cmp0, cmp1, cmp2, cmp3]

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  const allTickers = [ticker, ...compareTickers]

  const { chartData, allStats } = useMemo(() => {
    const allReturns = {}
    allReturns[ticker] = computeReturns(history)
    compareTickers.forEach((sym, i) => {
      allReturns[sym] = computeReturns(cmpData[i])
    })

    // Global min/max for consistent bin boundaries across all series
    const allValues = Object.values(allReturns).flat()
    if (allValues.length === 0) return { chartData: [], allStats: {} }
    const globalMin = Math.min(...allValues)
    const globalMax = Math.max(...allValues)
    const binWidth = (globalMax - globalMin) / NUM_BINS

    // Build bins for each series
    const binArrays = {}
    for (const [sym, returns] of Object.entries(allReturns)) {
      binArrays[sym] = buildBins(returns, globalMin, globalMax)
    }

    // Build chart rows
    const chartData = Array.from({ length: NUM_BINS }, (_, i) => {
      const mid = globalMin + (i + 0.5) * binWidth
      const row = { bin: mid }
      for (const sym of allTickers) {
        row[sym] = binArrays[sym]?.[i] || 0
      }
      return row
    })

    const allStats = {}
    for (const [sym, returns] of Object.entries(allReturns)) {
      allStats[sym] = computeStats(returns)
    }

    return { chartData, allStats }
  }, [history, cmpData, ticker, compareTickers, allTickers])

  if (loading) return <p className="text-gray-500 text-sm py-4 text-center">Loading...</p>
  if (chartData.length === 0) return null

  const primaryStats = allStats[ticker]
  const periodLabel = customStart && customEnd
    ? `${customStart} to ${customEnd}`
    : period.toUpperCase()

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">Daily Returns Distribution</h3>
        <span className="text-xs text-gray-500">{primaryStats?.n || 0} days · {periodLabel}</span>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={chartData} barCategoryGap={0} barGap={0}>
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
            formatter={(v, name) => [v, name]}
          />
          <ReferenceLine x={0} stroke="#6B7280" strokeWidth={1} />
          {primaryStats && (
            <ReferenceLine x={primaryStats.mean} stroke="#F59E0B" strokeDasharray="4 4" strokeWidth={1.5}
              label={{ value: `μ=${primaryStats.mean.toFixed(2)}%`, fill: '#F59E0B', fontSize: 9, position: 'top' }}
            />
          )}
          {allTickers.length > 1 && (
            <Legend
              wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
              onClick={handleLegendClick}
              formatter={legendFormatter}
            />
          )}
          {allTickers.map((sym, i) => (
            <Bar
              key={sym}
              dataKey={sym}
              fill={COLORS[i % COLORS.length]}
              opacity={allTickers.length > 1 ? 0.6 : 0.9}
              radius={[2, 2, 0, 0]}
              hide={isHidden(sym)}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>

      {/* Stats table */}
      <div className="overflow-x-auto mt-3">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500">
              <th className="text-left px-2 py-1">Ticker</th>
              <th className="text-right px-2 py-1">Mean</th>
              <th className="text-right px-2 py-1">Std Dev</th>
              <th className="text-right px-2 py-1">Skew</th>
              <th className="text-right px-2 py-1">Excess Kurt</th>
              <th className="text-right px-2 py-1">Days</th>
            </tr>
          </thead>
          <tbody>
            {allTickers.map((sym, i) => {
              const s = allStats[sym]
              if (!s) return null
              return (
                <tr key={sym} className="text-white">
                  <td className="px-2 py-1 font-mono" style={{ color: COLORS[i % COLORS.length] }}>{sym}</td>
                  <td className={`text-right px-2 py-1 font-mono ${s.mean >= 0 ? 'text-green-400' : 'text-red-400'}`}>{s.mean.toFixed(3)}%</td>
                  <td className="text-right px-2 py-1 font-mono">{s.stdDev.toFixed(3)}%</td>
                  <td className="text-right px-2 py-1 font-mono">{s.skewness.toFixed(3)}</td>
                  <td className="text-right px-2 py-1 font-mono">{s.kurtosis.toFixed(3)}</td>
                  <td className="text-right px-2 py-1 font-mono text-gray-400">{s.n}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
