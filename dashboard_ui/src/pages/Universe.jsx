import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

function formatMarketCap(val) {
  if (!val) return '—'
  if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (val >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  if (val >= 1e3) return `$${(val / 1e3).toFixed(0)}K`
  return `$${val.toFixed(0)}`
}

export default function Universe() {
  const navigate = useNavigate()
  const { data, loading, error } = useApi('/universe?sort_by=today_return')
  const stocks = data?.items || []

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-white">Penny Stocks</h1>
        <div className="flex items-center gap-3">
          {data && <span className="text-gray-400 text-sm">{data.total} stocks</span>}
          {stocks.length > 0 && <ExportButton data={stocks} filename="penny_stocks" />}
        </div>
      </div>

      {loading && <p className="text-gray-500">Loading universe...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}

      {stocks.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Ticker</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Name</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Exchange</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Price</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Today</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Market Cap</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Inferred MCap</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Sector</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Avg Vol</th>
                <th className="px-3 py-2 w-4"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {stocks.map(s => (
                <tr
                  key={s.ticker}
                  onClick={() => navigate(`/research/${s.ticker}`)}
                  className="hover:bg-gray-800/50 cursor-pointer"
                >
                  <td className="px-3 py-2 font-mono text-white font-semibold">{s.ticker}</td>
                  <td className="px-3 py-2 text-gray-300 truncate max-w-48">{s.name}</td>
                  <td className="px-3 py-2 text-gray-400">{s.exchange}</td>
                  <td className="px-3 py-2 text-right font-mono text-white">${s.last_price.toFixed(2)}</td>
                  <td className={`px-3 py-2 text-right font-mono ${
                    s.today_return == null ? 'text-gray-500' :
                    s.today_return >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {s.today_return != null ? `${s.today_return >= 0 ? '+' : ''}${s.today_return.toFixed(2)}%` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-400 font-mono">{formatMarketCap(s.market_cap)}</td>
                  <td className="px-3 py-2 text-right text-gray-500 font-mono">{formatMarketCap(s.inferred_market_cap)}</td>
                  <td className="px-3 py-2 text-gray-400 truncate max-w-32">{s.sector}</td>
                  <td className="px-3 py-2 text-right text-gray-400 font-mono">{(s.avg_volume || 0).toLocaleString()}</td>
                  <td className="px-3 py-2">
                    {s.is_monitored && <span className="inline-block w-2 h-2 rounded-full bg-green-500" title="Monitored" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && stocks.length === 0 && !error && (
        <p className="text-gray-500 text-center py-8">No stocks in universe yet</p>
      )}
    </div>
  )
}
