import { useState, useMemo, useCallback } from 'react'
import {
  Treemap,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'
import { useLegendToggle } from '../hooks/useLegendToggle'

const TIMEFRAMES = [
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '6m', label: '6M' },
  { value: '1y', label: '1Y' },
]

const VIEWS = [
  { value: 'heatmap', label: 'Heatmap' },
  { value: 'bar', label: 'Bar' },
  { value: 'line', label: 'Line' },
]

// Period param for the /sectors/history endpoint per timeframe.
// Only periods with dedicated history data are mapped here.
const HISTORY_PERIOD = {
  '1m': '1m',
  '3m': '3m',
  '6m': '6m',
  '1y': '1y',
}

// Distinct colors for 11 sector lines
const SECTOR_COLORS = [
  '#3B82F6', '#EF4444', '#22C55E', '#F59E0B', '#8B5CF6',
  '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#A855F7', '#06B6D4',
]

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r}, ${g}, ${b}`
}

/** Shared toggle button group for view/timeframe selectors. */
function ToggleButtonGroup({ options, value, onChange }) {
  return (
    <div className="flex rounded overflow-hidden border border-gray-600">
      {options.map(opt => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-2 py-1 text-xs transition-colors ${
            value === opt.value
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-400 hover:text-white'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

/** Treemap cell renderer for the sector heatmap view. */
function TreemapContent({ x, y, width, height, name, returnVal, colors }) {
  if (width < 30 || height < 20) return null
  const isPositive = (returnVal || 0) >= 0
  const bg = isPositive
    ? `rgba(${hexToRgb(colors.positive)}, 0.55)`
    : `rgba(${hexToRgb(colors.negative)}, 0.55)`

  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={bg} stroke="#1F2937" strokeWidth={2} rx={4} />
      {width > 50 && height > 35 && (
        <>
          <text x={x + width / 2} y={y + height / 2 - 8} textAnchor="middle" fill="#fff" fontSize={12} fontWeight="bold">
            {name}
          </text>
          <text
            x={x + width / 2}
            y={y + height / 2 + 10}
            textAnchor="middle"
            fill={isPositive ? colors.positive : colors.negative}
            fontSize={11}
            fontWeight="600"
          >
            {returnVal >= 0 ? '+' : ''}{(returnVal || 0).toFixed(2)}%
          </text>
        </>
      )}
    </g>
  )
}

function HeatmapView({ sectors, timeframe, colors }) {
  const treemapData = useMemo(() =>
    sectors
      .filter(s => s.market_cap)
      .map(s => ({
        name: s.name,
        size: s.market_cap || 1e9,
        returnVal: s.returns?.[timeframe] ?? 0,
        etf: s.etf,
        price: s.price,
      })),
    [sectors, timeframe]
  )

  if (treemapData.length === 0) return <p className="text-gray-500 text-sm">No sector data</p>

  return (
    <ResponsiveContainer width="100%" height={300}>
      <Treemap
        data={treemapData}
        dataKey="size"
        stroke="#1F2937"
        content={<TreemapContent colors={colors} />}
      >
        <Tooltip
          content={({ payload }) => {
            if (!payload?.[0]) return null
            const d = payload[0].payload
            return (
              <div style={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
                <p style={{ color: '#fff', fontWeight: 'bold' }}>{d.name} ({d.etf})</p>
                <p style={{ color: d.returnVal >= 0 ? colors.positive : colors.negative }}>
                  {d.returnVal >= 0 ? '+' : ''}{d.returnVal?.toFixed(2)}%
                </p>
                {d.price && <p style={{ color: '#9CA3AF' }}>${d.price.toFixed(2)}</p>}
              </div>
            )
          }}
        />
      </Treemap>
    </ResponsiveContainer>
  )
}

function BarView({ sectors, timeframe, colors }) {
  const barData = useMemo(() =>
    sectors
      .map(s => ({
        name: s.name,
        return: s.returns?.[timeframe] ?? 0,
        etf: s.etf,
      }))
      .sort((a, b) => a.return - b.return),
    [sectors, timeframe]
  )

  return (
    <ResponsiveContainer width="100%" height={360}>
      <BarChart data={barData} layout="vertical" margin={{ left: 90, right: 20, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
        <XAxis type="number" tick={{ fill: '#9CA3AF', fontSize: 11 }} tickFormatter={v => `${v}%`} />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: '#9CA3AF', fontSize: 11 }}
          width={85}
        />
        <Tooltip
          contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
          formatter={(val) => [`${val >= 0 ? '+' : ''}${val.toFixed(2)}%`, 'Return']}
          labelFormatter={(label) => {
            const item = barData.find(d => d.name === label)
            return item ? `${label} (${item.etf})` : label
          }}
        />
        <Bar
          dataKey="return"
          radius={[0, 4, 4, 0]}
          label={false}
        >
          {barData.map((entry, i) => (
            <Cell key={i} fill={entry.return >= 0 ? colors.positive : colors.negative} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

function LineView({ historyPeriod }) {
  const { data, loading } = useApi(`/research/sectors/history?period=${historyPeriod}`)
  const { handleLegendClick, isHidden, legendFormatter } = useLegendToggle()

  const chartData = useMemo(() => {
    if (!data?.dates) return []
    return data.dates.map((date, i) => {
      const point = { date }
      for (const [sector, values] of Object.entries(data.series)) {
        point[sector] = values[i] ?? null
      }
      return point
    })
  }, [data])

  const sectorNames = useMemo(() => (data?.series ? Object.keys(data.series) : []), [data])

  if (loading) return <p className="text-gray-500 text-sm text-center py-8">Loading history...</p>
  if (chartData.length === 0) return <p className="text-gray-500 text-sm text-center py-8">No history data</p>

  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={chartData} margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis
          dataKey="date"
          tick={{ fill: '#9CA3AF', fontSize: 10 }}
          tickFormatter={d => d.slice(5)} // MM-DD
          interval="preserveStartEnd"
          minTickGap={40}
        />
        <YAxis
          tick={{ fill: '#9CA3AF', fontSize: 11 }}
          tickFormatter={v => `${v}%`}
        />
        <Tooltip
          contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
          formatter={(val) => [`${val >= 0 ? '+' : ''}${val.toFixed(2)}%`]}
          labelFormatter={d => d}
        />
        <Legend onClick={handleLegendClick} formatter={legendFormatter} />
        {sectorNames.map((name, i) => (
          <Line
            key={name}
            type="monotone"
            dataKey={name}
            stroke={SECTOR_COLORS[i % SECTOR_COLORS.length]}
            strokeWidth={1.5}
            dot={false}
            hide={isHidden(name)}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

// Valid periods for the line chart (must match /sectors/history endpoint)
const LINE_VALID_TIMEFRAMES = new Set(['1m', '3m', '6m', '1y'])

export default function SectorPerformanceChart() {
  const colors = useChartColors()
  const [view, setView] = useState('heatmap')
  const [timeframe, setTimeframe] = useState('1m')

  const { data, loading } = useApi('/research/sectors', { interval: 300000 })

  const sectors = data?.sectors || []

  const handleViewChange = useCallback((newView) => {
    setView(newView)
    // Snap to nearest valid period when switching to line view
    if (newView === 'line' && !LINE_VALID_TIMEFRAMES.has(timeframe)) {
      setTimeframe('1m')
    }
  }, [timeframe])

  // Filter timeframes based on current view
  const visibleTimeframes = view === 'line'
    ? TIMEFRAMES.filter(tf => LINE_VALID_TIMEFRAMES.has(tf.value))
    : TIMEFRAMES

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      {/* Header with controls */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-white font-semibold">Sector Performance</h3>
        <div className="flex items-center gap-2">
          <ToggleButtonGroup options={VIEWS} value={view} onChange={handleViewChange} />
          <ToggleButtonGroup options={visibleTimeframes} value={timeframe} onChange={setTimeframe} />
        </div>
      </div>

      {/* Loading state */}
      {loading && sectors.length === 0 && (
        <p className="text-gray-500 text-sm text-center py-8">Loading sectors...</p>
      )}

      {/* Views */}
      {view === 'heatmap' && sectors.length > 0 && (
        <HeatmapView sectors={sectors} timeframe={timeframe} colors={colors} />
      )}
      {view === 'bar' && sectors.length > 0 && (
        <BarView sectors={sectors} timeframe={timeframe} colors={colors} />
      )}
      {view === 'line' && (
        <LineView historyPeriod={HISTORY_PERIOD[timeframe] || '1m'} />
      )}
    </div>
  )
}
