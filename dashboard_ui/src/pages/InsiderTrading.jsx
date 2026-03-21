import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

export default function InsiderTrading() {
  const [input, setInput] = useState('')
  const [ticker, setTicker] = useState('')

  const { data, loading, error } = useApi(
    ticker ? `/insiders/${encodeURIComponent(ticker)}` : null,
    { autoFetch: !!ticker }
  )

  const handleSearch = (e) => {
    e.preventDefault()
    const val = input.trim().toUpperCase()
    if (val) setTicker(val)
  }

  const transactions = data?.transactions || []
  const clusterBuys = data?.cluster_buys || []

  // Build set of (insider_name, date) pairs that are part of a cluster buy
  const clusterSet = useMemo(() => {
    const s = new Set()
    for (const c of clusterBuys) {
      for (const name of c.insiders) {
        s.add(name)
      }
    }
    return s
  }, [clusterBuys])

  function formatValue(val) {
    if (!val) return '—'
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
    if (val >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
    if (val >= 1e3) return `$${(val / 1e3).toFixed(0)}K`
    return `$${val.toLocaleString()}`
  }

  function typeBadge(type) {
    const colors = {
      Buy: 'bg-green-800 text-green-300',
      Sell: 'bg-red-800 text-red-300',
      Grant: 'bg-blue-800 text-blue-300',
      Exercise: 'bg-yellow-800 text-yellow-300',
      Gift: 'bg-purple-800 text-purple-300',
      Tax: 'bg-orange-800 text-orange-300',
      Other: 'bg-gray-700 text-gray-300',
    }
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${colors[type] || colors.Other}`}>
        {type}
      </span>
    )
  }

  const buyCount = transactions.filter(t => t.transaction_type === 'Buy').length
  const sellCount = transactions.filter(t => t.transaction_type === 'Sell').length
  const totalBuyValue = transactions
    .filter(t => t.transaction_type === 'Buy')
    .reduce((s, t) => s + t.value, 0)
  const totalSellValue = transactions
    .filter(t => t.transaction_type === 'Sell')
    .reduce((s, t) => s + t.value, 0)

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Insider Trading</h1>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Enter ticker (e.g. AAPL, TSLA, NVDA)..."
          className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500"
        />
        <button type="submit" className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg">
          Search
        </button>
      </form>

      {loading && ticker && (
        <p className="text-gray-500 text-sm">Loading insider transactions for {ticker}...</p>
      )}

      {error && (
        <p className="text-red-400 text-sm">Error: {error}</p>
      )}

      {/* Summary cards */}
      {transactions.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-xs uppercase">Insider Buys</p>
            <p className="text-green-400 text-2xl font-bold">{buyCount}</p>
            <p className="text-gray-500 text-xs">{formatValue(totalBuyValue)} total</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-xs uppercase">Insider Sells</p>
            <p className="text-red-400 text-2xl font-bold">{sellCount}</p>
            <p className="text-gray-500 text-xs">{formatValue(totalSellValue)} total</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-xs uppercase">Total Transactions</p>
            <p className="text-white text-2xl font-bold">{transactions.length}</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p className="text-gray-400 text-xs uppercase">Cluster Buys</p>
            <p className={`text-2xl font-bold ${clusterBuys.length > 0 ? 'text-yellow-400' : 'text-gray-600'}`}>
              {clusterBuys.length}
            </p>
            <p className="text-gray-500 text-xs">2+ insiders within 14 days</p>
          </div>
        </div>
      )}

      {/* Cluster buy alerts */}
      {clusterBuys.length > 0 && (
        <div className="space-y-2">
          {clusterBuys.map((c, i) => (
            <div key={i} className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className="px-2 py-0.5 rounded text-xs font-bold bg-yellow-800 text-yellow-300">
                  CLUSTER BUY
                </span>
                <span className="text-white text-sm font-semibold">
                  {c.start_date} — {c.end_date}
                </span>
              </div>
              <p className="text-gray-300 text-sm">
                {c.insider_count} insiders bought {c.total_shares.toLocaleString()} shares
                ({formatValue(c.total_value)}):{' '}
                <span className="text-gray-400">{c.insiders.join(', ')}</span>
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Transactions table */}
      {transactions.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold">
              Transactions ({transactions.length})
            </h2>
            <ExportButton data={transactions} filename={`insiders_${ticker}`} />
          </div>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-750 sticky top-0">
                <tr className="text-gray-400">
                  <th className="px-2 py-1 text-left">Date</th>
                  <th className="px-2 py-1 text-left">Insider</th>
                  <th className="px-2 py-1 text-left">Title</th>
                  <th className="px-2 py-1 text-left">Type</th>
                  <th className="px-2 py-1 text-right">Shares</th>
                  <th className="px-2 py-1 text-right">Price</th>
                  <th className="px-2 py-1 text-right">Value</th>
                  <th className="px-2 py-1 text-center">Filing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {transactions.map((t, i) => {
                  const isCluster = t.transaction_type === 'Buy' && clusterSet.has(t.insider_name)
                  return (
                    <tr
                      key={i}
                      className={`hover:bg-gray-700/30 ${isCluster ? 'bg-yellow-900/10' : ''}`}
                    >
                      <td className="px-2 py-1 font-mono text-gray-300">{t.date}</td>
                      <td className="px-2 py-1 text-white truncate max-w-48">{t.insider_name}</td>
                      <td className="px-2 py-1 text-gray-400 truncate max-w-32">{t.title || '—'}</td>
                      <td className="px-2 py-1">{typeBadge(t.transaction_type)}</td>
                      <td className="px-2 py-1 text-right text-gray-300 font-mono">
                        {t.shares.toLocaleString()}
                      </td>
                      <td className="px-2 py-1 text-right text-gray-400 font-mono">
                        {t.price_per_share ? `$${t.price_per_share.toFixed(2)}` : '—'}
                      </td>
                      <td className="px-2 py-1 text-right text-white font-mono">
                        {formatValue(t.value)}
                      </td>
                      <td className="px-2 py-1 text-center">
                        {t.filing_url && (
                          <a
                            href={t.filing_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-indigo-400 hover:text-indigo-300 underline"
                          >
                            SEC
                          </a>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && ticker && transactions.length === 0 && !error && (
        <div className="bg-gray-800 rounded-lg p-8 border border-gray-700 text-center">
          <p className="text-gray-400">No insider transactions found for {ticker}</p>
          <p className="text-gray-600 text-sm mt-1">Try a different ticker or check back later</p>
        </div>
      )}

      {!ticker && (
        <div className="bg-gray-800 rounded-lg p-8 border border-gray-700 text-center">
          <p className="text-gray-400">Enter a ticker symbol to view insider trading activity</p>
          <p className="text-gray-600 text-sm mt-1">
            Data sourced from SEC EDGAR Form 4 filings
          </p>
        </div>
      )}
    </div>
  )
}
