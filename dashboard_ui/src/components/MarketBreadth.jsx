import { useApi } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'

export default function MarketBreadth() {
  const colors = useChartColors()
  const { data, loading } = useApi('/breadth', { interval: 60000 })

  if (loading) return (
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
      <h3 className="text-white font-semibold mb-3">Market Breadth</h3>
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
      <p className="text-gray-500 text-xs mt-1 text-center">{data.total_stocks} stocks tracked</p>
    </div>
  )
}
