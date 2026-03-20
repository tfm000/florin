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
  const { data: history, loading } = useApi(`/research/yield-curve/history?period=${period}`)

  // Available dates from history (sample evenly for the picker)
  const availableDates = useMemo(() => {
    if (!history?.dates?.length) return []
    return history.dates
  }, [history])

  // Helper: extract a curve at a given date index from history
  const getCurveAt = (idx) => {
    if (!history?.tenors) return null
    const curve = {}
    for (const tenor of TENORS) {
      const vals = history.tenors[tenor]
      if (vals && vals[idx] != null) {
        curve[tenor] = vals[idx]
      }
    }
    return Object.keys(curve).length > 0 ? curve : null
  }

  // "Today" = latest date in the history (same data source, no discrepancy)
  const latestDate = history?.dates?.[history.dates.length - 1] || ''

  // Build chart data: each tenor is a row, each selected date + "Latest" is a line
  const chartData = useMemo(() => {
    const lines = []

    // Latest curve from history
    if (history?.dates?.length > 0) {
      const curve = getCurveAt(history.dates.length - 1)
      if (curve) lines.push({ label: `Today (${latestDate})`, curve })
    }

    // Historical curves from selected dates
    for (const dateStr of selectedDates) {
      const idx = history?.dates?.indexOf(dateStr)
      if (idx == null || idx === -1) continue
      const curve = getCurveAt(idx)
      if (curve) lines.push({ label: dateStr, curve })
    }

    return TENORS.map(tenor => {
      const point = { tenor }
      for (const line of lines) {
        if (line.curve[tenor] != null) {
          point[line.label] = line.curve[tenor]
        }
      }
      return point
    })
  }, [history, selectedDates, latestDate])

  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()
  const lineKeys = latestDate ? [`Today (${latestDate})`, ...selectedDates] : [...selectedDates]

  const toggleDate = (dateStr) => {
    setSelectedDates(prev =>
      prev.includes(dateStr)
        ? prev.filter(d => d !== dateStr)
        : [...prev, dateStr].slice(-4) // max 4 historical dates
    )
  }

  // Sample dates for the picker — show ~12 evenly spaced dates, excluding the latest (already shown as "Today")
  const pickerDates = useMemo(() => {
    const filtered = availableDates.filter(d => d !== latestDate)
    if (filtered.length <= 12) return filtered
    const step = Math.floor(filtered.length / 12)
    const sampled = []
    for (let i = 0; i < filtered.length; i += step) {
      sampled.push(filtered[i])
    }
    return sampled
  }, [availableDates, latestDate])

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
            {lineKeys.map((key, i) => {
              const isToday = key.startsWith('Today')
              return (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={isToday ? 2.5 : 1.5}
                  strokeDasharray={isToday ? undefined : '5 3'}
                  dot={{ fill: COLORS[i % COLORS.length], r: isToday ? 4 : 3 }}
                  connectNulls
                  hide={isHidden(key)}
                />
              )
            })}
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* Date picker */}
      {availableDates.length > 0 && (
        <div className="mt-3 space-y-2">
          {/* Custom date input */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Add date:</span>
            <input
              type="date"
              min={availableDates[0]}
              max={latestDate}
              onChange={(e) => {
                const val = e.target.value
                if (!val) return
                // Snap to nearest available date
                const nearest = availableDates.reduce((best, d) =>
                  Math.abs(new Date(d) - new Date(val)) < Math.abs(new Date(best) - new Date(val)) ? d : best
                )
                if (nearest !== latestDate && !selectedDates.includes(nearest)) {
                  toggleDate(nearest)
                }
                e.target.value = ''
              }}
              className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white"
            />
            {selectedDates.length > 0 && (
              <button
                onClick={() => setSelectedDates([])}
                className="text-xs text-gray-500 hover:text-red-400"
              >
                Clear all
              </button>
            )}
          </div>

          {/* Selected dates as removable chips */}
          {selectedDates.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {selectedDates.map((d, i) => (
                <span key={d} className="flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-gray-700 text-white"
                  style={{ borderLeft: `3px solid ${COLORS[(i + 1) % COLORS.length]}` }}
                >
                  {d}
                  <button onClick={() => toggleDate(d)} className="text-gray-400 hover:text-red-400 ml-0.5">&times;</button>
                </span>
              ))}
            </div>
          )}

          {/* Quick-pick presets */}
          <div className="flex flex-wrap gap-1">
            <span className="text-xs text-gray-500 mr-1">Quick:</span>
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
                {d.slice(2)}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <p className="text-gray-500 text-xs mt-2">Loading historical data...</p>}
    </div>
  )
}
