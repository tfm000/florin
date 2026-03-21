import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

const SECTORS = [
  '', 'Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical',
  'Consumer Defensive', 'Industrials', 'Energy', 'Basic Materials',
  'Communication Services', 'Real Estate', 'Utilities',
]

const EXCHANGES = [
  { value: '', label: 'All US' },
  { value: 'NMS,NGM,NCM', label: 'NASDAQ' },
  { value: 'NYQ', label: 'NYSE' },
  { value: 'ASE', label: 'NYSE American' },
]

export default function Screener() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState({
    price_min: '', price_max: '',
    market_cap_min: '', market_cap_max: '',
    pe_min: '', pe_max: '',
    dividend_yield_min: '',
    sector: '',
    exchange: '',
    sort_by: 'intradaymarketcap',
    sort_asc: false,
  })

  const queryParams = Object.entries(filters)
    .filter(([, v]) => v !== '' && v !== false)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')

  const { data, loading } = useApi(`/screener?${queryParams}`)
  const results = data?.results || []

  const update = (key, value) => setFilters(prev => ({ ...prev, [key]: value }))

  function formatMcap(val) {
    if (!val) return '—'
    if (val >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
    if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`
    return `$${val.toLocaleString()}`
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-white">Stock Screener</h1>
        <div className="flex items-center gap-3">
          {data && <span className="text-gray-400 text-sm">{data.total} matching</span>}
          {results.length > 0 && <ExportButton data={results} filename="screener_results" />}
        </div>
      </div>

      {/* Filters */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 text-xs">
          <div>
            <label className="text-gray-400 block mb-1">Price Min ($)</label>
            <input type="number" value={filters.price_min} onChange={e => update('price_min', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="0" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Price Max ($)</label>
            <input type="number" value={filters.price_max} onChange={e => update('price_max', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="No limit" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Market Cap Min ($)</label>
            <input type="number" value={filters.market_cap_min} onChange={e => update('market_cap_min', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="0" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Market Cap Max ($)</label>
            <input type="number" value={filters.market_cap_max} onChange={e => update('market_cap_max', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="No limit" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">P/E Min</label>
            <input type="number" value={filters.pe_min} onChange={e => update('pe_min', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="0" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">P/E Max</label>
            <input type="number" value={filters.pe_max} onChange={e => update('pe_max', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="No limit" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Min Div Yield (%)</label>
            <input type="number" value={filters.dividend_yield_min} onChange={e => update('dividend_yield_min', e.target.value)}
              step="0.1" className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="0" />
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Sector</label>
            <select value={filters.sector} onChange={e => update('sector', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
              {SECTORS.map(s => <option key={s} value={s}>{s || 'All'}</option>)}
            </select>
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Exchange</label>
            <select value={filters.exchange} onChange={e => update('exchange', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
              {EXCHANGES.map(e => <option key={e.value} value={e.value}>{e.label}</option>)}
            </select>
          </div>
        </div>
      </div>

      {loading && <p className="text-gray-500">Screening...</p>}

      {/* Results */}
      {results.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Ticker</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Name</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Price</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Chg%</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Mkt Cap</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">P/E</th>
                <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Div%</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Sector</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Exchange</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {results.map(r => (
                <tr key={r.ticker} onClick={() => navigate(`/research/${r.ticker}`)}
                  className="hover:bg-gray-800/50 cursor-pointer">
                  <td className="px-3 py-2 font-mono text-white font-semibold">{r.ticker}</td>
                  <td className="px-3 py-2 text-gray-300 truncate max-w-40">{r.name}</td>
                  <td className="px-3 py-2 text-right font-mono text-white">{r.price != null ? `$${r.price.toFixed(2)}` : '—'}</td>
                  <td className={`px-3 py-2 text-right font-mono ${(r.change_pct || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {r.change_pct != null ? `${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{formatMcap(r.market_cap)}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{r.pe_ratio != null ? r.pe_ratio.toFixed(1) : '—'}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{r.dividend_yield != null ? `${(r.dividend_yield * 100).toFixed(2)}%` : '—'}</td>
                  <td className="px-3 py-2 text-gray-400 truncate max-w-32">{r.sector || '—'}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs">{r.exchange}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && results.length === 0 && (
        <p className="text-gray-500 text-center py-8">No stocks match your criteria</p>
      )}
    </div>
  )
}
