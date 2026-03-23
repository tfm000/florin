import { useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { corrColor } from '../utils/colors'

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
  if (process.env.NODE_ENV !== 'production' && labels.length !== tickers.length) {
    console.warn(`PresetCorrelationMatrix "${title}": labels (${labels.length}) and tickers (${tickers.length}) length mismatch`)
  }

  const apiUrl = useMemo(() => {
    const params = new URLSearchParams({
      tickers: tickers.join(','),
      method,
      period,
    })
    return `/correlation?${params}`
  }, [tickers, method, period])

  const { data, loading, error } = useApi(apiUrl)

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
