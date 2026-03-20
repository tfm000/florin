import { useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { useApi } from '../hooks/useApi'

const PERIODS = ['1mo', '3mo', '6mo', '1y', '3y', 'max']

export default function CumulativeReturnChart({ ticker }) {
  const [period, setPeriod] = useState('1y')
  const { data: history, loading } = useApi(`/research/asset/${ticker}/history?period=${period}&interval=1d`)

  const chartData = (history || []).map(h => {
    const d = new Date(h.date)
    return {
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      close: h.close,
    }
  })

  // Compute cumulative return
  if (chartData.length > 0) {
    const base = chartData[0].close
    chartData.forEach(d => {
      d.return_pct = ((d.close - base) / base) * 100
    })
  }

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-white font-semibold">Price History</h3>
        <div className="flex gap-1">
          {PERIODS.map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2 py-1 text-xs rounded ${
                period === p
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700'
              }`}
            >
              {p.toUpperCase()}
            </button>
          ))}
        </div>
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
              tickFormatter={v => `$${v.toFixed(0)}`}
            />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
              labelStyle={{ color: '#fff' }}
              formatter={(v, name) => {
                if (name === 'close') return [`$${v.toFixed(2)}`, 'Price']
                return [`${v.toFixed(2)}%`, 'Return']
              }}
            />
            <Line type="monotone" dataKey="close" stroke="#22C55E" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
      {!loading && chartData.length === 0 && (
        <p className="text-gray-500 text-sm py-8 text-center">No history data available</p>
      )}
    </div>
  )
}
