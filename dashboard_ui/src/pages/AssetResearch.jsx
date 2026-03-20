import { useState, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useApi, apiPost } from '../hooks/useApi'
import MetricsGrid from '../components/MetricsGrid'
import PeriodSelector from '../components/PeriodSelector'
import CumulativeReturnChart from '../components/CumulativeReturnChart'
import ReturnsHistogram from '../components/ReturnsHistogram'
import SearchBar from '../components/SearchBar'
import NewsCard from '../components/NewsCard'

export default function AssetResearch() {
  const { ticker } = useParams()
  const { data: info, loading } = useApi(`/research/asset/${ticker}`)
  const { data: news } = useApi(`/research/news?ticker=${ticker}`)
  const [analysis, setAnalysis] = useState(null)
  const [analysing, setAnalysing] = useState(false)
  const [watchStatus, setWatchStatus] = useState(null)
  const [monitorStatus, setMonitorStatus] = useState(null)

  // Shared period state for charts + stats
  const [period, setPeriod] = useState('1y')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')

  // Comparison overlays
  const [compareTickers, setCompareTickers] = useState([])

  const handlePeriodChange = (p) => {
    setPeriod(p)
    setCustomStart('')
    setCustomEnd('')
  }

  const handleCustomRange = (start, end) => {
    setPeriod('custom')
    setCustomStart(start)
    setCustomEnd(end)
  }

  const handleAddCompare = (item) => {
    const sym = item.ticker.toUpperCase()
    if (sym !== ticker && !compareTickers.includes(sym)) {
      setCompareTickers(prev => [...prev, sym].slice(0, 4))
    }
  }

  const handleRemoveCompare = (sym) => {
    setCompareTickers(prev => prev.filter(t => t !== sym))
  }

  // Build history query string shared by charts
  const historyQuery = customStart && customEnd
    ? `start=${customStart}&end=${customEnd}&interval=1d`
    : `period=${period}&interval=1d`

  // Fetch history for the primary ticker (used for period-aware stats)
  const { data: history } = useApi(`/research/asset/${ticker}/history?${historyQuery}`)

  // Compute period-aware stats from the history data
  const periodStats = useMemo(() => {
    if (!history || history.length < 2) return null
    const closes = history.map(h => h.close).filter(v => v > 0)
    if (closes.length < 2) return null

    const returns = []
    for (let i = 1; i < closes.length; i++) {
      returns.push((closes[i] - closes[i - 1]) / closes[i - 1])
    }

    const mean = returns.reduce((s, r) => s + r, 0) / returns.length
    const std = Math.sqrt(returns.reduce((s, r) => s + (r - mean) ** 2, 0) / returns.length)
    const sharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0

    let peak = closes[0], maxDd = 0
    for (const c of closes) {
      if (c > peak) peak = c
      const dd = (peak - c) / peak
      if (dd > maxDd) maxDd = dd
    }

    const totalReturn = ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100

    return {
      totalReturn: totalReturn.toFixed(2),
      sharpe: sharpe.toFixed(2),
      maxDrawdown: (maxDd * 100).toFixed(2),
      volatility: (std * Math.sqrt(252) * 100).toFixed(2),
      tradingDays: closes.length,
    }
  }, [history])

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

  const showReturns = !ticker.startsWith('^') && !ticker.includes('=')

  // Static metrics from yfinance info
  const staticMetrics = [
    { label: 'Market Cap', value: info.market_cap, format: 'mcap' },
    { label: 'P/E Ratio', value: info.pe_ratio, format: 'number' },
    { label: 'Short Interest', value: info.short_interest ? info.short_interest * 100 : null, format: 'pct' },
    { label: 'Beta', value: info.beta, format: 'number' },
    { label: '52W High', value: info.fifty_two_week_high, format: 'dollar' },
    { label: '52W Low', value: info.fifty_two_week_low, format: 'dollar' },
  ]

  // Period-aware metrics (recalculated from selected range)
  const periodMetrics = periodStats ? [
    { label: 'Return', value: Number(periodStats.totalReturn), format: 'pct',
      color: Number(periodStats.totalReturn) >= 0 ? 'text-green-400' : 'text-red-400' },
    { label: 'Sharpe', value: Number(periodStats.sharpe), format: 'number' },
    { label: 'Max Drawdown', value: -Number(periodStats.maxDrawdown), format: 'pct' },
    { label: 'Ann. Volatility', value: Number(periodStats.volatility), format: 'pct' },
  ] : []

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

      {/* Static metrics */}
      <MetricsGrid metrics={staticMetrics} />

      {/* Shared period selector + compare search */}
      <div className="bg-gray-800 rounded-lg p-3 border border-gray-700 space-y-3">
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Period</span>
          <PeriodSelector
            period={period}
            onPeriodChange={handlePeriodChange}
            startDate={customStart}
            endDate={customEnd}
            onCustomRange={handleCustomRange}
          />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs uppercase font-semibold">Compare</span>
          <SearchBar onSelect={handleAddCompare} placeholder="Add overlay..." />
          {compareTickers.map(sym => (
            <span key={sym} className="flex items-center gap-1 bg-gray-700 rounded px-2 py-0.5 text-xs text-white font-mono">
              {sym}
              <button onClick={() => handleRemoveCompare(sym)} className="text-gray-400 hover:text-red-400 ml-1">&times;</button>
            </span>
          ))}
        </div>
      </div>

      {/* Period-aware stats */}
      {periodMetrics.length > 0 && (
        <MetricsGrid metrics={periodMetrics} />
      )}

      {/* Price chart with overlays */}
      <CumulativeReturnChart
        ticker={ticker}
        period={period}
        customStart={customStart}
        customEnd={customEnd}
        compareTickers={compareTickers}
      />

      {/* Returns histogram with overlays */}
      {showReturns && (
        <ReturnsHistogram
          ticker={ticker}
          period={period}
          customStart={customStart}
          customEnd={customEnd}
          compareTickers={compareTickers}
        />
      )}

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
