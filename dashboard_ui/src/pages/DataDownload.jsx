import { useState, useMemo } from 'react'
import SearchBar from '../components/SearchBar'
import PeriodSelector, { INTRADAY_TO_HISTORY } from '../components/PeriodSelector'
import { buildHistoryQuery } from '../utils/historyQuery'
import { exportCSV, exportJSON } from '../utils/export'

const FREQUENCIES = [
  { value: '1d', label: 'Daily' },
  { value: '1wk', label: 'Weekly' },
  { value: '1mo', label: 'Monthly' },
  { value: '1h', label: 'Hourly' },
  { value: '5m', label: '5 Min' },
  { value: '1m', label: '1 Min' },
]

const BASE_FIELDS = [
  { key: 'open', label: 'Open' },
  { key: 'high', label: 'High' },
  { key: 'low', label: 'Low' },
  { key: 'close', label: 'Close' },
  { key: 'volume', label: 'Volume' },
  { key: 'bid', label: 'Bid' },
  { key: 'ask', label: 'Ask' },
]

const PROVIDERS = [
  { value: 'yfinance', label: 'Yahoo Finance' },
]

export default function DataDownload() {
  const [tickers, setTickers] = useState([])
  const [period, setPeriod] = useState('1y')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [frequency, setFrequency] = useState('1d')
  const [fields, setFields] = useState(new Set(['open', 'high', 'low', 'close', 'volume']))
  const [provider, setProvider] = useState('yfinance')
  const [adjusted, setAdjusted] = useState(true)
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState(null)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')

  const availableFields = useMemo(() => {
    if (adjusted) return BASE_FIELDS
    return [...BASE_FIELDS, { key: 'adj_close', label: 'Adj Close' }]
  }, [adjusted])

  const addTicker = (item) => {
    const sym = item.ticker.toUpperCase()
    if (!tickers.includes(sym)) setTickers(prev => [...prev, sym])
  }

  const removeTicker = (sym) => setTickers(prev => prev.filter(t => t !== sym))

  const toggleField = (key) => {
    setFields(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const fetchData = async () => {
    if (tickers.length === 0) return
    setLoading(true)
    setPreview(null)
    setError('')
    setProgress('Fetching...')

    const allData = []
    const errors = []
    for (let i = 0; i < tickers.length; i++) {
      const sym = tickers[i]
      setProgress(`Fetching ${sym} (${i + 1}/${tickers.length})...`)

      try {
        const intradayMap = INTRADAY_TO_HISTORY[period]
        const effectivePeriod = intradayMap ? intradayMap.period : period
        // Use quotes endpoint when bid/ask fields are selected; history goes
        // through buildHistoryQuery (REQ FND-02). The quotes endpoint stays
        // inline for Phase 1 — different URL shape, out of scope here.
        const needsBidAsk = fields.has('bid') || fields.has('ask')
        let endpoint
        if (needsBidAsk) {
          const params = customStart && customEnd
            ? `start=${customStart}&end=${customEnd}&interval=${frequency}`
            : `period=${effectivePeriod}&interval=${frequency}`
          const adjustedParam = adjusted ? '' : '&adjusted=false'
          endpoint = `/api/research/asset/${sym}/quotes?${params}${adjustedParam}`
        } else {
          // useApi prepends /api; DataDownload uses raw fetch so prepend manually.
          const { url } = buildHistoryQuery({
            ticker: sym,
            period: effectivePeriod,
            customStart,
            customEnd,
            interval: frequency,
            adjusted,
          })
          endpoint = `/api${url}`
        }
        const resp = await fetch(endpoint)
        if (!resp.ok) {
          errors.push(`${sym}: HTTP ${resp.status}`)
          continue
        }
        const history = await resp.json()
        if (!history || history.length === 0) {
          errors.push(`${sym}: no data returned`)
          continue
        }
        for (const h of history) {
          const row = { ticker: sym, date: h.date }
          for (const f of fields) {
            row[f] = h[f] ?? ''
          }
          allData.push(row)
        }
      } catch (err) {
        errors.push(`${sym}: ${err.message || 'fetch failed'}`)
      }
    }

    setPreview(allData)
    if (errors.length > 0) {
      setError(errors.join('; '))
    }
    setProgress(allData.length > 0 ? `Done — ${allData.length} rows` : '')
    setLoading(false)
  }

  const handleExport = (format) => {
    if (!preview || preview.length === 0) return
    const filename = `market_data_${tickers.join('_')}_${period}`
    if (format === 'json') exportJSON(preview, `${filename}.json`)
    else exportCSV(preview, `${filename}.csv`)
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Data Download</h1>

      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-4">
        {/* Tickers */}
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-gray-400 text-xs uppercase font-semibold">Tickers</span>
          <SearchBar onSelect={addTicker} placeholder="Add ticker..." />
          {tickers.map(t => (
            <span key={t} className="flex items-center gap-1 bg-gray-700 rounded px-2 py-0.5 text-xs text-white font-mono">
              {t}
              <button onClick={() => removeTicker(t)} className="text-gray-400 hover:text-red-400">&times;</button>
            </span>
          ))}
        </div>

        {/* Bulk ticker input */}
        <div>
          <input
            type="text"
            placeholder="Type or paste tickers (e.g. AAPL, MSFT, GOOG) and press Enter"
            onKeyDown={e => {
              if (e.key === 'Enter') {
                const syms = e.target.value.split(/[,\s]+/).map(s => s.trim().toUpperCase()).filter(Boolean)
                if (syms.length > 0) {
                  setTickers(prev => [...new Set([...prev, ...syms])])
                  e.target.value = ''
                }
              }
            }}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
          />
        </div>

        {/* Period */}
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Period</span>
          <PeriodSelector
            period={period}
            onPeriodChange={p => { setPeriod(p); setCustomStart(''); setCustomEnd('') }}
            startDate={customStart}
            endDate={customEnd}
            onCustomRange={(s, e) => { setPeriod('custom'); setCustomStart(s); setCustomEnd(e) }}
          />
        </div>

        {/* Frequency + Provider */}
        <div className="flex items-center gap-6">
          <label className="text-gray-400 text-xs">
            Frequency:
            <select value={frequency} onChange={e => setFrequency(e.target.value)}
              className="ml-2 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-xs">
              {FREQUENCIES.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>
          <label className="text-gray-400 text-xs">
            Provider:
            <select value={provider} onChange={e => setProvider(e.target.value)}
              className="ml-2 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-xs">
              {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-gray-400 text-xs">
            <span>Adjusted Prices</span>
            <button
              type="button"
              onClick={() => {
                const next = !adjusted
                setAdjusted(next)
                setPreview(null)
                setFields(f => {
                  const updated = new Set(f)
                  if (next) {
                    updated.delete('adj_close')
                  } else {
                    updated.add('adj_close')
                  }
                  return updated
                })
              }}
              className={`relative w-9 h-5 rounded-full transition-colors ${
                adjusted ? 'bg-indigo-600' : 'bg-gray-600'
              }`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                adjusted ? 'translate-x-4' : ''
              }`} />
            </button>
          </label>
        </div>

        {/* Fields */}
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Fields</span>
          {availableFields.map(f => (
            <label key={f.key} className="flex items-center gap-1 text-xs text-gray-300 cursor-pointer">
              <input type="checkbox" checked={fields.has(f.key)} onChange={() => toggleField(f.key)}
                className="rounded bg-gray-700 border-gray-600" />
              {f.label}
            </label>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          <button onClick={fetchData} disabled={loading || tickers.length === 0}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-sm rounded-lg">
            {loading ? progress : 'Fetch Data'}
          </button>
          {tickers.length === 0 && !loading && (
            <span className="text-gray-500 text-xs">Add tickers above to enable download</span>
          )}
          {preview && preview.length > 0 && (
            <>
              <button onClick={() => handleExport('csv')}
                className="px-3 py-2 bg-green-700 hover:bg-green-600 text-white text-sm rounded-lg font-medium">
                Download CSV
              </button>
              <button onClick={() => handleExport('json')}
                className="px-3 py-2 bg-green-700 hover:bg-green-600 text-white text-sm rounded-lg font-medium">
                Download JSON
              </button>
              <span className="text-gray-400 text-xs">{preview.length} rows</span>
            </>
          )}
        </div>
        {error && (
          <p className="text-red-400 text-xs">{error}</p>
        )}
      </div>

      {/* Preview */}
      {preview && preview.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-white font-semibold mb-3">Preview (first 20 rows)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-gray-400">
                  {Object.keys(preview[0]).map(k => (
                    <th key={k} className="px-2 py-1 text-left">{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {preview.slice(0, 20).map((row, i) => (
                  <tr key={i} className="text-gray-300">
                    {Object.values(row).map((v, j) => (
                      <td key={j} className="px-2 py-1">{typeof v === 'number' ? v.toFixed(4) : v}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
