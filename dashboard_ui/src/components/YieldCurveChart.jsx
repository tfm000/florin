import { useState, useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { useApi } from '../hooks/useApi'
import { useLegendToggle } from '../hooks/useLegendToggle'

const PERIODS = ['1mo', '3mo', '6mo', '1y', '2y']
const COLORS = ['#6366F1', '#F59E0B', '#EF4444', '#10B981', '#8B5CF6']
const TENORS = ['3M', '2Y', '5Y', '10Y', '30Y']

export default function YieldCurveChart() {
  const [period, setPeriod] = useState('1y')
  const [selectedDates, setSelectedDates] = useState([])
  const { data: current } = useApi('/research/yield-curve')
  const { data: history, loading } = useApi(`/research/yield-curve/history?period=${period}`)

  // Available dates from history (sample evenly for the picker)
  const availableDates = useMemo(() => {
    if (!history?.dates?.length) return []
    return history.dates
  }, [history])

  // Build chart data: each tenor is a row, each selected date + "Today" is a line
  const chartData = useMemo(() => {
    const lines = []

    // Today's curve
    if (current?.curve) {
      lines.push({ label: 'Today', curve: current.curve })
    }

    // Historical curves from selected dates
    if (history?.tenors && selectedDates.length > 0) {
      for (const dateStr of selectedDates) {
        const idx = history.dates.indexOf(dateStr)
        if (idx === -1) continue
        const curve = {}
        for (const tenor of TENORS) {
          const vals = history.tenors[tenor]
          if (vals && vals[idx] != null) {
            curve[tenor] = vals[idx]
          }
        }
        if (Object.keys(curve).length > 0) {
          lines.push({ label: dateStr, curve })
        }
      }
    }

    // Transform to recharts format: [{tenor: "3M", Today: 4.2, "2024-06-01": 3.8}, ...]
    return TENORS.map(tenor => {
      const point = { tenor }
      for (const line of lines) {
        if (line.curve[tenor] != null) {
          point[line.label] = line.curve[tenor]
        }
      }
      return point
    })
  }, [current, history, selectedDates])

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()
  const lineKeys = ['Today', ...selectedDates]

  const toggleDate = (dateStr) => {
    setSelectedDates(prev =>
      prev.includes(dateStr)
        ? prev.filter(d => d !== dateStr)
        : [...prev, dateStr].slice(-4) // max 4 historical dates
    )
  }

  // Sample dates for the picker — show ~12 evenly spaced dates
  const pickerDates = useMemo(() => {
    if (availableDates.length <= 12) return availableDates
    const step = Math.floor(availableDates.length / 12)
    const sampled = []
    for (let i = 0; i < availableDates.length; i += step) {
      sampled.push(availableDates[i])
    }
    return sampled
  }, [availableDates])

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">US Treasury Yield Curve</h3>
        <div className="flex gap-1">
          {PERIODS.map(p => (
            <button
              key={p}
              onClick={() => { setPeriod(p); setSelectedDates([]) }}
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

      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="tenor" tick={{ fill: '#9CA3AF', fontSize: 12 }} />
            <YAxis
              tick={{ fill: '#9CA3AF', fontSize: 12 }}
              domain={['auto', 'auto']}
              tickFormatter={v => `${v}%`}
              label={{ value: 'Yield', angle: -90, position: 'insideLeft', fill: '#6B7280', fontSize: 10, dx: -5 }}
            />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
              labelStyle={{ color: '#fff' }}
              formatter={(v, name) => [`${v.toFixed(3)}%`, name]}
            />
            {lineKeys.length > 1 && (
              <Legend
                wrapperStyle={{ fontSize: 11, cursor: 'pointer' }}
                onClick={handleLegendClick}
                formatter={legendFormatter}
              />
            )}
            {lineKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={key === 'Today' ? 2.5 : 1.5}
                strokeDasharray={key === 'Today' ? undefined : '5 3'}
                dot={{ fill: COLORS[i % COLORS.length], r: key === 'Today' ? 4 : 3 }}
                connectNulls
                hide={isHidden(key)}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* Date picker */}
      {pickerDates.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-gray-500 mb-2">
            Compare with historical dates (click to overlay, max 4):
          </p>
          <div className="flex flex-wrap gap-1">
            {pickerDates.map(d => (
              <button
                key={d}
                onClick={() => toggleDate(d)}
                className={`px-2 py-0.5 text-xs rounded ${
                  selectedDates.includes(d)
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:text-white hover:bg-gray-600'
                }`}
              >
                {d.slice(5)} {/* show MM-DD */}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <p className="text-gray-500 text-xs mt-2">Loading historical data...</p>}
    </div>
  )
}
