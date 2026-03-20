import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useLegendToggle } from '../hooks/useLegendToggle'
import { useChartColors } from '../hooks/useChartColors'

export default function CumulativeReturnChart({
  ticker, period = '1y', customStart = '', customEnd = '', compareTickers = [],
}) {
  const colors = useChartColors()
  const queryStr = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}&interval=1d`
    : `period=${period}&interval=1d`

  const { data: history, loading } = useApi(`/research/asset/${ticker}/history?${queryStr}`)

  // Fetch comparison histories
  const { data: cmp0 } = useApi(compareTickers[0] ? `/research/asset/${compareTickers[0]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[0] })
  const { data: cmp1 } = useApi(compareTickers[1] ? `/research/asset/${compareTickers[1]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[1] })
  const { data: cmp2 } = useApi(compareTickers[2] ? `/research/asset/${compareTickers[2]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[2] })
  const { data: cmp3 } = useApi(compareTickers[3] ? `/research/asset/${compareTickers[3]}/history?${queryStr}` : null, { autoFetch: !!compareTickers[3] })
  const cmpData = [cmp0, cmp1, cmp2, cmp3]

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  // Normalize all series to % return from first value for comparison
  const hasCompare = compareTickers.length > 0

  const chartData = useMemo(() => {
    if (!history || history.length === 0) return []

    const baseFirst = history[0].close

    return history.map((h, i) => {
      const d = new Date(h.date)
      const row = {
        date: `${d.getMonth() + 1}/${d.getDate()}`,
      }

      if (hasCompare) {
        // Use normalized returns for comparison mode
        row[ticker] = ((h.close - baseFirst) / baseFirst) * 100

        compareTickers.forEach((sym, ci) => {
          const data = cmpData[ci]
          if (data && data[i] && data[0]) {
            const cmpFirst = data[0].close
            row[sym] = ((data[i].close - cmpFirst) / cmpFirst) * 100
          }
        })
      } else {
        row.close = h.close
      }

      return row
    })
  }, [history, cmpData, compareTickers, hasCompare, ticker])

  // Y-axis domain
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [0, 1]
    const allKeys = hasCompare ? [ticker, ...compareTickers] : ['close']
    const values = chartData.flatMap(d => allKeys.map(k => d[k]).filter(v => v != null))
    if (values.length === 0) return [0, 1]
    const min = Math.min(...values)
    const max = Math.max(...values)
    const padding = (max - min) * 0.05 || Math.abs(max) * 0.02 || 1
    return [min - padding, max + padding]
  }, [chartData, hasCompare, ticker, compareTickers])

  const formatY = hasCompare
    ? (v) => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`
    : (v) => {
        if (v >= 1000) return `$${(v / 1000).toFixed(1)}k`
        if (v >= 1) return `$${v.toFixed(2)}`
        return `$${v.toFixed(4)}`
      }

  const periodLabel = customStart && customEnd
    ? `${customStart} to ${customEnd}`
    : period.toUpperCase()

  const allKeys = hasCompare ? [ticker, ...compareTickers] : ['close']

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-white font-semibold">{hasCompare ? 'Cumulative Returns' : 'Price History'}</h3>
        <span className="text-xs text-gray-500">{periodLabel} · {chartData.length} days</span>
      </div>
      {loading && <p className="text-gray-500 text-sm py-8 text-center">Loading...</p>}
      {!loading && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="date"
              tick={{ fill: '#9CA3AF', fontSize: 11 }}
              interval={Math.max(0, Math.floor(chartData.length / 8))}
            />
            <YAxis
              tick={{ fill: '#9CA3AF', fontSize: 11 }}
              domain={yDomain}
              tickFormatter={formatY}
              label={{ value: hasCompare ? 'Return (%)' : 'Price', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
            />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
              labelStyle={{ color: '#fff' }}
              formatter={(v, name) => [
                hasCompare ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : formatY(v),
                name === 'close' ? 'Price' : name,
              ]}
            />
            {allKeys.length > 1 && (
              <Legend
                wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
                onClick={handleLegendClick}
                formatter={legendFormatter}
              />
            )}
            {allKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={colors.series[i % colors.series.length]}
                strokeWidth={i === 0 ? 2 : 1.5}
                dot={false}
                hide={isHidden(key)}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
      {!loading && chartData.length === 0 && (
        <p className="text-gray-500 text-sm py-8 text-center">No history data available</p>
      )}
    </div>
  )
}
