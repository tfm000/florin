import { useState } from 'react'

function formatMarketCap(val) {
  if (!val) return '—'
  if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (val >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  if (val >= 1e3) return `$${(val / 1e3).toFixed(0)}K`
  return `$${val.toFixed(0)}`
}

export default function StockTable({ stocks, onRowClick }) {
  const [sortField, setSortField] = useState('ticker')
  const [sortDir, setSortDir] = useState('asc')
  const [filter, setFilter] = useState('')

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  const filtered = (stocks || []).filter(s =>
    s.ticker.toLowerCase().includes(filter.toLowerCase()) ||
    s.name.toLowerCase().includes(filter.toLowerCase())
  )

  const sorted = [...filtered].sort((a, b) => {
    const aVal = a[sortField] ?? ''
    const bVal = b[sortField] ?? ''
    const cmp = typeof aVal === 'number' ? aVal - bVal : String(aVal).localeCompare(String(bVal))
    return sortDir === 'asc' ? cmp : -cmp
  })

  const SortHeader = ({ field, children }) => (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase cursor-pointer hover:text-white"
      onClick={() => handleSort(field)}
    >
      {children} {sortField === field ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
    </th>
  )

  return (
    <div>
      <input
        type="text"
        placeholder="Filter by ticker or name..."
        value={filter}
        onChange={e => setFilter(e.target.value)}
        className="mb-3 w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-500"
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-800">
            <tr>
              <SortHeader field="ticker">Ticker</SortHeader>
              <SortHeader field="name">Name</SortHeader>
              <SortHeader field="exchange">Exchange</SortHeader>
              <SortHeader field="last_price">Price</SortHeader>
              <SortHeader field="market_cap">Market Cap</SortHeader>
              <SortHeader field="sector">Sector</SortHeader>
              <SortHeader field="avg_volume">Avg Vol</SortHeader>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {sorted.map(s => (
              <tr
                key={s.ticker}
                onClick={() => onRowClick?.(s)}
                className="hover:bg-gray-800/50 cursor-pointer"
              >
                <td className="px-3 py-2 font-mono text-white">{s.ticker}</td>
                <td className="px-3 py-2 text-gray-300 truncate max-w-48">{s.name}</td>
                <td className="px-3 py-2 text-gray-400">{s.exchange}</td>
                <td className="px-3 py-2 font-mono text-white">${s.last_price.toFixed(2)}</td>
                <td className="px-3 py-2 text-gray-400 font-mono">{formatMarketCap(s.market_cap)}</td>
                <td className="px-3 py-2 text-gray-400 truncate max-w-32">{s.sector}</td>
                <td className="px-3 py-2 text-gray-400 font-mono">{(s.avg_volume || 0).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length === 0 && (
          <p className="text-center text-gray-500 py-8">No stocks found</p>
        )}
      </div>
    </div>
  )
}
