import { useState, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useApi, apiPost, apiPut } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

export default function Filings13F() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // URL-synced state (survives browser back)
  const searchTerm = searchParams.get('q') || ''
  const selectedCik = searchParams.get('cik') || ''
  const selectedFilerName = searchParams.get('filer') || ''
  const selectedAccession = searchParams.get('accession') || ''

  // Ephemeral typing state (initialized from URL)
  const [searchQuery, setSearchQuery] = useState(searchTerm)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  const { data: filers, loading: searchLoading } = useApi(
    searchTerm ? `/13f/search?q=${encodeURIComponent(searchTerm)}` : null,
    { autoFetch: !!searchTerm }
  )
  const { data: filings, loading: filingsLoading } = useApi(
    selectedCik ? `/13f/filings?cik=${selectedCik}` : null,
    { autoFetch: !!selectedCik }
  )
  const { data: holdings, loading: holdingsLoading } = useApi(
    selectedAccession ? `/13f/holdings?cik=${selectedCik}&accession=${selectedAccession}` : null,
    { autoFetch: !!selectedAccession }
  )
  const { data: portfolios, refetch: refetchPortfolios } = useApi('/portfolios')

  // Derive the filing date from the filings list
  const filingDate = useMemo(() => {
    if (!filings || !selectedAccession) return ''
    const f = filings.find(f => f.accession === selectedAccession)
    return f?.date || ''
  }, [filings, selectedAccession])

  // Check if this filing has already been saved as a portfolio
  const portfolioName = selectedFilerName && filingDate
    ? `${selectedFilerName} - ${filingDate}` : ''
  const existingPortfolio = useMemo(() => {
    if (!portfolios || !portfolioName) return null
    return portfolios.find(p => p.name === portfolioName)
  }, [portfolios, portfolioName])

  const handleSearch = (e) => {
    e.preventDefault()
    setSearchParams({ q: searchQuery })
  }

  const selectFiler = (filer) => {
    setSearchParams({ q: searchTerm, cik: filer.cik, filer: filer.name })
  }

  const selectFiling = (filing) => {
    setSearchParams({
      q: searchTerm, cik: selectedCik, filer: selectedFilerName,
      accession: filing.accession,
    })
  }

  const saveAsPortfolio = async () => {
    if (!holdings || !portfolioName) return
    setSaving(true)
    setSaveMsg('')
    try {
      const mapped = holdings
        .filter(h => h.ticker)
        .map(h => ({ ticker: h.ticker, weight: h.weight }))
      if (mapped.length === 0) {
        setSaveMsg('No tickers mapped — cannot save')
        setSaving(false)
        return
      }
      const portfolio = await apiPost('/portfolios', { name: portfolioName, group: '13F' })
      await apiPut(`/portfolios/${portfolio.id}/holdings`, mapped)
      setSaveMsg('Saved!')
      refetchPortfolios()
    } catch (e) {
      if (e.message.includes('already exists')) {
        setSaveMsg('Portfolio already exists')
      } else {
        setSaveMsg(`Error: ${e.message}`)
      }
    }
    setSaving(false)
  }

  function formatValue(val) {
    if (!val) return '—'
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
    if (val >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
    if (val >= 1e3) return `$${(val / 1e3).toFixed(0)}K`
    return `$${val.toLocaleString()}`
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">13F Filings</h1>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search fund name (e.g. Bridgewater, Citadel, Renaissance)..."
          className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500"
        />
        <button type="submit" className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg">
          Search
        </button>
      </form>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Filers */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="text-white font-semibold mb-3">Filers</h2>
          {searchLoading && <p className="text-gray-500 text-sm">Searching...</p>}
          {filers && filers.length === 0 && <p className="text-gray-500 text-sm">No filers found</p>}
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {(filers || []).map((f, i) => (
              <div key={i} onClick={() => selectFiler(f)}
                className={`p-2 rounded cursor-pointer text-sm ${
                  selectedCik === f.cik ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-300 hover:bg-gray-700'
                }`}>
                <p className="font-medium truncate">{f.name}</p>
                <p className="text-xs text-gray-500">CIK: {f.cik} · {f.filing_date}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Filings */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="text-white font-semibold mb-3">
            {selectedFilerName ? `Filings — ${selectedFilerName}` : 'Filings'}
          </h2>
          {!selectedCik && <p className="text-gray-500 text-sm">Select a filer</p>}
          {filingsLoading && <p className="text-gray-500 text-sm">Loading filings...</p>}
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {(filings || []).map((f, i) => (
              <div key={i} onClick={() => selectFiling(f)}
                className={`p-2 rounded cursor-pointer text-sm ${
                  selectedAccession === f.accession ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-300 hover:bg-gray-700'
                }`}>
                <p className="font-mono">{f.date}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Holdings summary */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="text-white font-semibold mb-3">Summary</h2>
          {holdings && holdings.length > 0 ? (
            <div className="space-y-2 text-sm">
              <p className="text-gray-400">Positions: <span className="text-white">{holdings.length}</span></p>
              <p className="text-gray-400">Total Value: <span className="text-white">
                {formatValue(holdings.reduce((s, h) => s + h.value, 0))}
              </span></p>
              <p className="text-gray-400">Top 5:</p>
              {holdings.slice(0, 5).map((h, i) => (
                <div key={i} className="flex justify-between text-xs">
                  <span className="text-white font-mono">{h.ticker || h.name || h.cusip}</span>
                  <span className="text-gray-400">{h.weight.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-sm">Select a filing to view holdings</p>
          )}
        </div>
      </div>

      {/* Holdings table */}
      {holdings && holdings.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold">Holdings ({holdings.length})</h2>
            <div className="flex gap-2 items-center">
              {existingPortfolio ? (
                <button
                  onClick={() => navigate('/portfolio')}
                  className="px-2 py-1 text-xs bg-emerald-700 text-white hover:bg-emerald-600 rounded"
                >
                  View Portfolio
                </button>
              ) : (
                <button
                  onClick={saveAsPortfolio}
                  disabled={saving}
                  className="px-2 py-1 text-xs bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-gray-600 rounded"
                >
                  {saving ? 'Saving...' : 'Save as Portfolio'}
                </button>
              )}
              {saveMsg && <span className="text-xs text-gray-400">{saveMsg}</span>}
              <a
                href={`/api/13f/holdings/download?cik=${selectedCik}&accession=${selectedAccession}`}
                className="px-2 py-1 text-xs bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white rounded"
              >
                Download CSV
              </a>
              <ExportButton data={holdings} filename={`13f_${selectedCik}`} />
            </div>
          </div>
          {holdingsLoading && <p className="text-gray-500 text-sm">Loading holdings...</p>}
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-750 sticky top-0">
                <tr className="text-gray-400">
                  <th className="px-2 py-1 text-left">Ticker</th>
                  <th className="px-2 py-1 text-left">Name</th>
                  <th className="px-2 py-1 text-left">CUSIP</th>
                  <th className="px-2 py-1 text-right">Shares</th>
                  <th className="px-2 py-1 text-right">Value</th>
                  <th className="px-2 py-1 text-right">Weight</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {holdings.map((h, i) => (
                  <tr key={i}
                    onClick={() => h.ticker && navigate(`/research/${h.ticker}`)}
                    className={`hover:bg-gray-700/30 ${h.ticker ? 'cursor-pointer' : ''}`}>
                    <td className="px-2 py-1 font-mono text-white font-semibold">
                      {h.ticker || <span className="text-gray-500">{h.name || h.cusip}</span>}
                    </td>
                    <td className="px-2 py-1 text-gray-300 truncate max-w-40">{h.name}</td>
                    <td className="px-2 py-1 text-gray-500 font-mono">{h.cusip}</td>
                    <td className="px-2 py-1 text-right text-gray-300 font-mono">{h.shares.toLocaleString()}</td>
                    <td className="px-2 py-1 text-right text-white font-mono">{formatValue(h.value)}</td>
                    <td className="px-2 py-1 text-right text-gray-400 font-mono">{h.weight.toFixed(2)}%</td>
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
