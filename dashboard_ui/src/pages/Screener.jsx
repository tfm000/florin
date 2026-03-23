import { useState, useMemo, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useApi, apiPost, apiFetch } from '../hooks/useApi'
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

const ASSET_TYPES = [
  { value: '', label: 'All' },
  { value: 'EQUITY', label: 'Stocks' },
  { value: 'ETF', label: 'ETFs' },
  { value: 'INDEX', label: 'Indices' },
  { value: 'CRYPTOCURRENCY', label: 'Crypto' },
]

const MOMENTUM_PERIODS = [
  { value: '', label: 'None' },
  { value: '1d', label: 'Current Day' },
  { value: '5d', label: 'Last 5 Days' },
  { value: '1w', label: '1 Week' },
  { value: '1mo', label: '1 Month' },
  { value: '3mo', label: 'Quarter' },
  { value: '1y', label: '1 Year' },
]

const DEFAULT_FILTERS = {
  price_min: '', price_max: '',
  market_cap_min: '', market_cap_max: '',
  pe_min: '', pe_max: '',
  dividend_yield_min: '',
  sector: '',
  exchange: '',
  asset_type: '',
  momentum_min: '', momentum_max: '',
  momentum_period: '',
  sort_by: 'intradaymarketcap',
  sort_asc: false,
}

export default function Screener() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('desc')
  const [saveName, setSaveName] = useState('')
  const [showSaveInput, setShowSaveInput] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)

  // Load preset from URL if present
  const presetId = searchParams.get('preset')
  useEffect(() => {
    if (!presetId) return
    apiFetch(`/screener/saved/${presetId}`)
      .then(data => {
        if (data?.filters) {
          setFilters(prev => ({
            ...DEFAULT_FILTERS,
            ...data.filters,
            sort_by: data.sort_by || 'intradaymarketcap',
            sort_asc: data.sort_asc || false,
          }))
        }
      })
      .catch(() => {})
  }, [presetId])

  const queryParams = Object.entries(filters)
    .filter(([, v]) => v !== '' && v !== false)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')

  const { data, loading } = useApi(`/screener?${queryParams}`)
  const rawResults = data?.results || []

  // Client-side sorting (overrides server sort for columns the server doesn't sort by)
  const results = useMemo(() => {
    if (!sortCol) return rawResults
    const sorted = [...rawResults].sort((a, b) => {
      const av = a[sortCol] ?? -Infinity
      const bv = b[sortCol] ?? -Infinity
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
      return sortDir === 'asc' ? av - bv : bv - av
    })
    return sorted
  }, [rawResults, sortCol, sortDir])

  const update = (key, value) => setFilters(prev => ({ ...prev, [key]: value }))

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('desc')
    }
  }

  const handleSave = async () => {
    if (!saveName.trim()) return
    setSaveMessage(null)
    try {
      const { sort_by, sort_asc, ...filterFields } = filters
      await apiPost('/screener/saved', {
        name: saveName.trim(),
        filters: filterFields,
        sort_by,
        sort_asc,
      })
      setSaveMessage('Saved!')
      setSaveName('')
      setShowSaveInput(false)
      setTimeout(() => setSaveMessage(null), 3000)
    } catch (err) {
      setSaveMessage(`Error: ${err.message}`)
    }
  }

  function formatMcap(val) {
    if (!val) return '\u2014'
    if (val >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
    if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`
    return `$${val.toLocaleString()}`
  }

  function formatVolume(val) {
    if (!val) return '\u2014'
    if (val >= 1e9) return `${(val / 1e9).toFixed(1)}B`
    if (val >= 1e6) return `${(val / 1e6).toFixed(1)}M`
    if (val >= 1e3) return `${(val / 1e3).toFixed(0)}K`
    return val.toLocaleString()
  }

  function SortHeader({ col, label, align = 'left' }) {
    const active = sortCol === col
    const arrow = active ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : ''
    return (
      <th
        onClick={() => handleSort(col)}
        className={`px-3 py-2 text-xs font-medium text-gray-400 uppercase cursor-pointer hover:text-white select-none ${
          align === 'right' ? 'text-right' : 'text-left'
        } ${active ? 'text-white' : ''}`}
      >
        {label}{arrow}
      </th>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-white">Screener</h1>
        <div className="flex items-center gap-3">
          {data && <span className="text-gray-400 text-sm">{data.total} matching</span>}
          {results.length > 0 && <ExportButton data={results} filename="screener_results" />}

          {/* Save screener */}
          {showSaveInput ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={saveName}
                onChange={e => setSaveName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSave()}
                placeholder="Screener name..."
                className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-sm w-40"
                autoFocus
              />
              <button onClick={handleSave} className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded">
                Save
              </button>
              <button onClick={() => setShowSaveInput(false)} className="px-2 py-1 text-gray-400 hover:text-white text-sm">
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowSaveInput(true)}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              Save Screener
            </button>
          )}
          {saveMessage && (
            <span className={`text-xs ${saveMessage.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>
              {saveMessage}
            </span>
          )}
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
          <div>
            <label className="text-gray-400 block mb-1">Asset Type</label>
            <select value={filters.asset_type} onChange={e => update('asset_type', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
              {ASSET_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-gray-400 block mb-1">Momentum Period</label>
            <select value={filters.momentum_period} onChange={e => update('momentum_period', e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white">
              {MOMENTUM_PERIODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </div>
          {filters.momentum_period && (
            <>
              <div>
                <label className="text-gray-400 block mb-1">Momentum Min (%)</label>
                <input type="number" value={filters.momentum_min} onChange={e => update('momentum_min', e.target.value)}
                  step="0.1" className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="0" />
              </div>
              <div>
                <label className="text-gray-400 block mb-1">Momentum Max (%)</label>
                <input type="number" value={filters.momentum_max} onChange={e => update('momentum_max', e.target.value)}
                  step="0.1" className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white" placeholder="No limit" />
              </div>
            </>
          )}
        </div>
      </div>

      {loading && <p className="text-gray-500">Screening...</p>}

      {/* Results */}
      {results.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800">
              <tr>
                <SortHeader col="ticker" label="Ticker" />
                <SortHeader col="name" label="Name" />
                <SortHeader col="price" label="Price" align="right" />
                <SortHeader col="volume" label="Volume" align="right" />
                <SortHeader col="change_pct" label="Chg%" align="right" />
                <SortHeader col="market_cap" label="Mkt Cap" align="right" />
                <SortHeader col="pe_ratio" label="P/E" align="right" />
                <SortHeader col="dividend_yield" label="Div%" align="right" />
                <SortHeader col="sector" label="Sector" />
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Exchange</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {results.map(r => (
                <tr key={r.ticker} onClick={() => navigate(`/research/${r.ticker}`)}
                  className="hover:bg-gray-800/50 cursor-pointer">
                  <td className="px-3 py-2 font-mono text-white font-semibold">{r.ticker}</td>
                  <td className="px-3 py-2 text-gray-300 truncate max-w-40">{r.name}</td>
                  <td className="px-3 py-2 text-right font-mono text-white">{r.price != null ? `$${r.price.toFixed(2)}` : '\u2014'}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{formatVolume(r.volume || r.avg_volume)}</td>
                  <td className={`px-3 py-2 text-right font-mono ${(r.change_pct || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {r.change_pct != null ? `${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%` : '\u2014'}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{formatMcap(r.market_cap)}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{r.pe_ratio != null ? r.pe_ratio.toFixed(1) : '\u2014'}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">{r.dividend_yield != null ? `${(r.dividend_yield * 100).toFixed(2)}%` : '\u2014'}</td>
                  <td className="px-3 py-2 text-gray-400 truncate max-w-32">{r.sector || '\u2014'}</td>
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
