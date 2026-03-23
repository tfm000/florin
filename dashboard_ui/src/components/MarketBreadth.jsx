import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'
import { EXCHANGE_GROUPS } from '../utils/exchanges'

const DEFAULT_SELECTED = ['NASDAQ', 'NYSE']

export default function MarketBreadth() {
  const colors = useChartColors()
  const [selected, setSelected] = useState(DEFAULT_SELECTED)

  // Resolve group labels to exchange codes
  const exchangeCodes = useMemo(() => {
    const codes = []
    for (const group of EXCHANGE_GROUPS) {
      if (selected.includes(group.label)) {
        codes.push(...group.codes)
      }
    }
    return codes.join(',')
  }, [selected])

  const { data, loading } = useApi(
    `/breadth?exchange=${encodeURIComponent(exchangeCodes)}`,
    { interval: 60000 },
  )

  const toggleGroup = (label) => {
    setSelected(prev => {
      if (prev.includes(label)) {
        // Don't allow deselecting all
        if (prev.length <= 1) return prev
        return prev.filter(g => g !== label)
      }
      return [...prev, label]
    })
  }

  if (loading && !data) return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">Market Breadth</h3>
      <p className="text-gray-500 text-sm text-center py-4">Loading breadth data...</p>
    </div>
  )
  if (!data || data.total_stocks === 0) return null

  const advPct = data.pct_advancing
  const decPct = 100 - advPct - (data.unchanged / data.total_stocks * 100)

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">Market Breadth</h3>
        <div className="flex items-center gap-1 flex-wrap">
          {EXCHANGE_GROUPS.map(g => (
            <button
              key={g.label}
              onClick={() => toggleGroup(g.label)}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                selected.includes(g.label)
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 text-center">
        <div>
          <p className="text-gray-500 text-xs">Advancing</p>
          <p className="font-mono text-lg" style={{ color: colors.positive }}>{data.advancing}</p>
        </div>
        <div>
          <p className="text-gray-500 text-xs">Declining</p>
          <p className="font-mono text-lg" style={{ color: colors.negative }}>{data.declining}</p>
        </div>
        <div>
          <p className="text-gray-500 text-xs">A/D Ratio</p>
          <p className={`font-mono text-lg ${data.advance_decline_ratio >= 1 ? 'text-green-400' : 'text-red-400'}`}>
            {data.advance_decline_ratio.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-gray-500 text-xs">% Up</p>
          <p className="font-mono text-lg text-white">{advPct.toFixed(0)}%</p>
        </div>
      </div>
      {/* Bar */}
      <div className="flex h-3 rounded-full overflow-hidden mt-3">
        <div style={{ width: `${advPct}%`, backgroundColor: colors.positive }} />
        <div style={{ width: `${data.unchanged / data.total_stocks * 100}%`, backgroundColor: '#6B7280' }} />
        <div style={{ width: `${decPct}%`, backgroundColor: colors.negative }} />
      </div>
      <p className="text-gray-500 text-xs mt-1 text-center">{data.total_stocks.toLocaleString()} stocks tracked</p>
    </div>
  )
}
