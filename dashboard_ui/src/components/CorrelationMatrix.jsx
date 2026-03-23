import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { corrColor } from '../utils/colors'
import SearchBar from './SearchBar'
import ExportButton from './ExportButton'

const METHODS = [
  { value: 'pearson', label: 'Pearson' },
  { value: 'spearman', label: 'Spearman' },
  { value: 'kendall', label: 'Kendall' },
  { value: 'pp_kendall', label: 'PP Kendall' },
  { value: 'rm_pearson', label: 'RM Pearson' },
  { value: 'rm_spearman', label: 'RM Spearman' },
  { value: 'rm_kendall', label: 'RM Kendall' },
  { value: 'rm_pp_kendall', label: 'RM PP Kendall' },
  { value: 'laloux_pearson', label: 'Laloux Pearson' },
  { value: 'laloux_spearman', label: 'Laloux Spearman' },
  { value: 'laloux_kendall', label: 'Laloux Kendall' },
  { value: 'laloux_pp_kendall', label: 'Laloux PP Kendall' },
]

export default function CorrelationMatrix() {
  const [tickers, setTickers] = useState(['SPY', 'QQQ', 'IWM', 'GLD', 'TLT'])
  const [method, setMethod] = useState('pearson')
  const [period, setPeriod] = useState('1y')

  const tickerStr = tickers.join(',')
  const { data, loading } = useApi(
    tickers.length >= 2 ? `/correlation?tickers=${tickerStr}&method=${method}&period=${period}` : null,
    { autoFetch: tickers.length >= 2 }
  )

  const addTicker = (item) => {
    const sym = item.ticker.toUpperCase()
    if (!tickers.includes(sym)) setTickers(prev => [...prev, sym].slice(0, 15))
  }

  const removeTicker = (sym) => {
    setTickers(prev => prev.filter(t => t !== sym))
  }

  // Build export data
  const exportData = useMemo(() => {
    if (!data?.matrix) return []
    return data.tickers.map((t, i) => {
      const row = { ticker: t }
      data.tickers.forEach((t2, j) => { row[t2] = data.matrix[i][j] })
      return row
    })
  }, [data])

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold">Correlation Matrix</h3>
        <div className="flex items-center gap-2">
          <select value={method} onChange={e => setMethod(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white">
            {METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <select value={period} onChange={e => setPeriod(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white">
            <option value="3mo">3M</option>
            <option value="6mo">6M</option>
            <option value="1y">1Y</option>
            <option value="3y">3Y</option>
          </select>
          {exportData.length > 0 && <ExportButton data={exportData} filename={`corr_${method}`} />}
        </div>
      </div>

      {/* Ticker management */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <SearchBar onSelect={addTicker} placeholder="Add ticker..." />
        {tickers.map(t => (
          <span key={t} className="flex items-center gap-1 bg-gray-700 rounded px-2 py-0.5 text-xs text-white font-mono">
            {t}
            <button onClick={() => removeTicker(t)} className="text-gray-400 hover:text-red-400">&times;</button>
          </span>
        ))}
      </div>

      {loading && <p className="text-gray-500 text-sm text-center py-4">Computing correlations...</p>}

      {/* Matrix table */}
      {data?.matrix && (
        <div className="overflow-x-auto">
          <table className="text-xs font-mono">
            <thead>
              <tr>
                <th className="px-2 py-1"></th>
                {data.tickers.map(t => (
                  <th key={t} className="px-2 py-1 text-gray-400 text-center" style={{ minWidth: 50 }}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.tickers.map((t, i) => (
                <tr key={t}>
                  <td className="px-2 py-1 text-gray-400">{t}</td>
                  {data.matrix[i].map((val, j) => (
                    <td key={j} className="px-2 py-1 text-center text-white"
                      style={{ background: corrColor(val), minWidth: 50 }}>
                      {val.toFixed(2)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tickers.length < 2 && (
        <p className="text-gray-500 text-sm text-center py-4">Add at least 2 tickers</p>
      )}
    </div>
  )
}
