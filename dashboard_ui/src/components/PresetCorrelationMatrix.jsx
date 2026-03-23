import { useApi } from '../hooks/useApi'

function corrColor(val) {
  if (val == null) return 'transparent'
  const abs = Math.min(Math.abs(val), 1)
  if (val > 0) return `rgba(59, 130, 246, ${abs * 0.8})`
  if (val < 0) return `rgba(239, 68, 68, ${abs * 0.8})`
  return 'transparent'
}

/**
 * Read-only correlation matrix with fixed ticker lists and display labels.
 *
 * Uses the existing /correlation endpoint. No user interaction for adding/removing
 * tickers — the matrix is pre-configured.
 *
 * Props:
 *   title   — heading text
 *   tickers — array of ticker symbols to correlate
 *   labels  — array of display labels (same length/order as tickers)
 *   method  — correlation method (default: 'pearson')
 *   period  — lookback period (default: '1y')
 */
export default function PresetCorrelationMatrix({
  title,
  tickers,
  labels,
  method = 'pearson',
  period = '1y',
}) {
  const tickerStr = tickers.join(',')
  const { data, loading, error } = useApi(
    `/correlation?tickers=${tickerStr}&method=${method}&period=${period}`
  )

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">{title}</h3>

      {loading && (
        <p className="text-gray-500 text-sm text-center py-4">Computing correlations...</p>
      )}

      {error && (
        <p className="text-red-400 text-sm text-center py-4">Failed to load: {error}</p>
      )}

      {data?.matrix && (
        <div className="overflow-x-auto">
          <table className="text-xs font-mono">
            <thead>
              <tr>
                <th className="px-2 py-1"></th>
                {labels.map((label, i) => (
                  <th
                    key={tickers[i]}
                    className="px-2 py-1 text-gray-400 text-center"
                    style={{ minWidth: 50 }}
                    title={tickers[i]}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((label, i) => (
                <tr key={tickers[i]}>
                  <td className="px-2 py-1 text-gray-400 whitespace-nowrap" title={tickers[i]}>
                    {label}
                  </td>
                  {data.matrix[i].map((val, j) => (
                    <td
                      key={j}
                      className="px-2 py-1 text-center text-white"
                      style={{ background: corrColor(val), minWidth: 50 }}
                    >
                      {val != null && isFinite(val) ? val.toFixed(2) : '—'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
