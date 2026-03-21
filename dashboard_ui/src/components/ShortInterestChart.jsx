import { useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'

function formatNumber(n) {
  if (n == null) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toLocaleString()
}

export default function ShortInterestChart({ ticker }) {
  const colors = useChartColors()
  const { data, loading, error } = useApi(`/short-interest/${ticker}`)

  const squeeze = useMemo(() => {
    if (!data) return null
    const pct = data.short_percent_of_float
    const ratio = data.short_ratio
    // Score from 0-100 based on short % of float and days to cover
    let score = 0
    if (pct != null) score += Math.min(pct * 100, 50) // up to 50 points for 50%+ short float
    if (ratio != null) score += Math.min(ratio * 5, 50) // up to 50 points for 10+ days to cover
    let label = 'Low'
    let color = colors.positive
    if (score >= 60) { label = 'High'; color = colors.negative }
    else if (score >= 30) { label = 'Moderate'; color = colors.atm }
    return { score, label, color }
  }, [data, colors])

  if (loading) return <p className="text-gray-500 text-sm">Loading short interest...</p>
  if (error) return <p className="text-red-400 text-sm">Error: {error}</p>
  if (!data) return null

  const pctDisplay = data.short_percent_of_float != null
    ? (data.short_percent_of_float * 100).toFixed(2) + '%'
    : '—'

  const ratioDisplay = data.short_ratio != null
    ? data.short_ratio.toFixed(2) + ' days'
    : '—'

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">Short Interest</h3>

      {/* Key metrics */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div>
          <p className="text-gray-400 text-xs uppercase font-semibold">Short % of Float</p>
          <p className="text-white text-lg font-mono">{pctDisplay}</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase font-semibold">Shares Short</p>
          <p className="text-white text-lg font-mono">{formatNumber(data.shares_short)}</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase font-semibold">Short Ratio (DTC)</p>
          <p className="text-white text-lg font-mono">{ratioDisplay}</p>
        </div>
      </div>

      {/* Squeeze potential indicator */}
      {squeeze && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <p className="text-gray-400 text-xs uppercase font-semibold">Squeeze Potential</p>
            <span className="text-xs font-semibold" style={{ color: squeeze.color }}>
              {squeeze.label}
            </span>
          </div>
          <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(squeeze.score, 100)}%`,
                backgroundColor: squeeze.color,
              }}
            />
          </div>
          <p className="text-gray-500 text-xs mt-1">
            Based on short % of float and days to cover
          </p>
        </div>
      )}
    </div>
  )
}
