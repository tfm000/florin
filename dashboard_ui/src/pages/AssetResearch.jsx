import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useApi, apiPost } from '../hooks/useApi'
import MetricsGrid from '../components/MetricsGrid'
import CumulativeReturnChart from '../components/CumulativeReturnChart'
import NewsCard from '../components/NewsCard'

export default function AssetResearch() {
  const { ticker } = useParams()
  const { data: info, loading } = useApi(`/research/asset/${ticker}`)
  const { data: news } = useApi(`/research/news?ticker=${ticker}`)
  const [analysis, setAnalysis] = useState(null)
  const [analysing, setAnalysing] = useState(false)
  const [watchStatus, setWatchStatus] = useState(null)
  const [monitorStatus, setMonitorStatus] = useState(null)

  const handleAnalyse = async () => {
    setAnalysing(true)
    try {
      const res = await apiPost(`/research/asset/${ticker}/analyse`, {})
      setAnalysis(res)
    } catch (e) {
      setAnalysis({ error: e.message })
    }
    setAnalysing(false)
  }

  const handleWatch = async () => {
    try {
      await apiPost('/watchlist', { ticker })
      setWatchStatus('Added to watchlist')
    } catch (e) {
      setWatchStatus(e.message)
    }
  }

  const handleMonitor = async () => {
    try {
      await apiPost('/monitor', { ticker })
      setMonitorStatus('Monitoring started')
    } catch (e) {
      setMonitorStatus(e.message)
    }
  }

  if (loading) return <p className="text-gray-500">Loading asset data...</p>
  if (!info) return <p className="text-gray-500">No data found for {ticker}</p>

  const metrics = [
    { label: 'Market Cap', value: info.market_cap, format: 'mcap' },
    { label: 'P/E Ratio', value: info.pe_ratio, format: 'number' },
    { label: 'Short Interest', value: info.short_interest ? info.short_interest * 100 : null, format: 'pct' },
    { label: 'Beta', value: info.beta, format: 'number' },
    { label: 'Sharpe', value: info.sharpe_ratio, format: 'number' },
    { label: 'Max Drawdown', value: info.max_drawdown_pct ? -info.max_drawdown_pct : null, format: 'pct' },
    { label: '1M Return', value: info.return_1m, format: 'pct', color: (info.return_1m || 0) >= 0 ? 'text-green-400' : 'text-red-400' },
    { label: '6M Return', value: info.return_6m, format: 'pct', color: (info.return_6m || 0) >= 0 ? 'text-green-400' : 'text-red-400' },
    { label: '1Y Return', value: info.return_1y, format: 'pct', color: (info.return_1y || 0) >= 0 ? 'text-green-400' : 'text-red-400' },
    { label: '3Y Return', value: info.return_3y, format: 'pct', color: (info.return_3y || 0) >= 0 ? 'text-green-400' : 'text-red-400' },
    { label: '52W High', value: info.fifty_two_week_high, format: 'dollar' },
    { label: '52W Low', value: info.fifty_two_week_low, format: 'dollar' },
  ]

  const recColor = {
    STRONG_BUY: 'bg-green-600', BUY: 'bg-green-700',
    HOLD: 'bg-yellow-600', AVOID: 'bg-red-700', STRONG_AVOID: 'bg-red-600',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <Link to="/research" className="text-gray-400 hover:text-white text-sm">&larr; Research</Link>
          </div>
          <h1 className="text-3xl font-bold text-white font-mono mt-1">{ticker}</h1>
          <p className="text-gray-400">
            {info.name} &middot; {info.exchange} &middot; {info.sector}
          </p>
          {info.current_price && (
            <p className="text-2xl font-mono text-white mt-1">${info.current_price.toFixed(2)}</p>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={handleWatch} className="px-3 py-1.5 rounded text-sm bg-gray-700 hover:bg-gray-600 text-white">
            Watch
          </button>
          <button onClick={handleMonitor} className="px-3 py-1.5 rounded text-sm bg-gray-700 hover:bg-gray-600 text-white">
            Monitor
          </button>
          <button
            onClick={handleAnalyse}
            disabled={analysing}
            className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 text-white"
          >
            {analysing ? 'Analysing...' : 'LLM Analyse'}
          </button>
        </div>
      </div>
      {watchStatus && <p className="text-xs text-gray-400">{watchStatus}</p>}
      {monitorStatus && <p className="text-xs text-gray-400">{monitorStatus}</p>}

      {/* Metrics */}
      <MetricsGrid metrics={metrics} />

      {/* Chart */}
      <CumulativeReturnChart ticker={ticker} />

      {/* LLM Analysis */}
      {analysis && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <div className="flex items-center gap-3">
            <h3 className="text-white font-semibold">LLM Analysis</h3>
            {analysis.recommendation && (
              <span className={`px-2 py-0.5 rounded text-xs text-white ${recColor[analysis.recommendation] || 'bg-gray-600'}`}>
                {analysis.recommendation}
              </span>
            )}
            {analysis.provider && (
              <span className="text-xs text-gray-500">via {analysis.provider}</span>
            )}
          </div>
          {analysis.error && <p className="text-red-400 text-sm">{analysis.error}</p>}
          {analysis.summary && <p className="text-gray-300 text-sm">{analysis.summary}</p>}
          {analysis.bullish_signals?.length > 0 && (
            <div>
              <p className="text-green-400 text-xs uppercase font-semibold mb-1">Bullish Signals</p>
              <ul className="text-sm text-gray-300 space-y-1">
                {analysis.bullish_signals.map((s, i) => <li key={i}>+ {s}</li>)}
              </ul>
            </div>
          )}
          {analysis.bearish_signals?.length > 0 && (
            <div>
              <p className="text-red-400 text-xs uppercase font-semibold mb-1">Bearish Signals</p>
              <ul className="text-sm text-gray-300 space-y-1">
                {analysis.bearish_signals.map((s, i) => <li key={i}>- {s}</li>)}
              </ul>
            </div>
          )}
          {analysis.key_factors?.length > 0 && (
            <div>
              <p className="text-gray-400 text-xs uppercase font-semibold mb-1">Key Factors</p>
              <ul className="text-sm text-gray-300 space-y-1">
                {analysis.key_factors.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}
          <div className="flex gap-4 text-xs text-gray-500">
            {analysis.sentiment_score != null && <span>Score: {analysis.sentiment_score.toFixed(1)}</span>}
            {analysis.confidence != null && <span>Confidence: {(analysis.confidence * 100).toFixed(0)}%</span>}
          </div>
        </div>
      )}

      {/* News */}
      {news && news.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-300 mb-3">Recent News</h2>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {news.map((article, i) => (
              <NewsCard key={i} article={article} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
