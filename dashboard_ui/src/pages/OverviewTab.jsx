import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useApi, apiPost } from '../hooks/useApi'
import MetricsGrid from '../components/MetricsGrid'
import NewsCard from '../components/NewsCard'

export default function OverviewTab() {
  const { info, ticker } = useOutletContext()
  const { data: news } = useApi(`/research/news?ticker=${ticker}`)
  const [analysis, setAnalysis] = useState(null)
  const [analysing, setAnalysing] = useState(false)
  const [analysisMode, setAnalysisMode] = useState(null)

  const handleAnalyse = async (mode) => {
    setAnalysing(true)
    setAnalysisMode(mode)
    try {
      const res = await apiPost(`/research/asset/${ticker}/analyse?mode=${mode}`, {})
      setAnalysis(res)
    } catch (e) {
      setAnalysis({ error: e.message })
    }
    setAnalysing(false)
  }

  const metrics = [
    { label: 'Market Cap', value: info.market_cap, format: 'mcap' },
    { label: 'P/E Ratio', value: info.pe_ratio, format: 'number' },
    { label: 'Forward P/E', value: info.forward_pe, format: 'number' },
    { label: 'PEG Ratio', value: info.peg_ratio, format: 'number' },
    { label: 'P/B', value: info.price_to_book, format: 'number' },
    { label: 'P/S', value: info.price_to_sales, format: 'number' },
    { label: 'EV', value: info.enterprise_value, format: 'mcap' },
    { label: 'EV/Revenue', value: info.enterprise_to_revenue, format: 'number' },
    { label: 'EV/EBITDA', value: info.enterprise_to_ebitda, format: 'number' },
    { label: 'Trailing EPS', value: info.trailing_eps, format: 'dollar' },
    { label: 'Forward EPS', value: info.forward_eps, format: 'dollar' },
    { label: 'Book Value', value: info.book_value, format: 'dollar' },
    { label: 'Dividend Yield', value: info.dividend_yield ? info.dividend_yield * 100 : null, format: 'pct' },
    { label: 'Beta', value: info.beta, format: 'number' },
    { label: 'Short Interest', value: info.short_interest ? info.short_interest * 100 : null, format: 'pct' },
    { label: '52W High', value: info.fifty_two_week_high, format: 'dollar' },
    { label: '52W Low', value: info.fifty_two_week_low, format: 'dollar' },
    { label: 'Shares Outstanding', value: info.shares_outstanding, format: 'mcap' },
    { label: 'Avg Volume', value: info.average_volume, format: 'mcap' },
  ].filter(m => m.value != null)

  const fmtBigNum = (v) => {
    if (v == null) return '—'
    const neg = v < 0
    const a = Math.abs(v)
    let s
    if (a >= 1e12) s = `$${(a / 1e12).toFixed(2)}T`
    else if (a >= 1e9) s = `$${(a / 1e9).toFixed(2)}B`
    else if (a >= 1e6) s = `$${(a / 1e6).toFixed(1)}M`
    else if (a >= 1e3) s = `$${(a / 1e3).toFixed(0)}K`
    else s = `$${a.toLocaleString()}`
    return neg ? `-${s}` : s
  }

  const fmtPct = (v) => v != null ? `${(v * 100).toFixed(1)}%` : '—'

  const fmtPay = (v) => {
    if (!v) return ''
    if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
    if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
    return `$${v.toLocaleString()}`
  }

  const financialMetrics = [
    { label: 'Revenue', value: info.revenue, fmt: fmtBigNum },
    { label: 'Net Income', value: info.net_income, fmt: fmtBigNum },
    { label: 'EBITDA', value: info.ebitda, fmt: fmtBigNum },
    { label: 'Gross Profits', value: info.gross_profits, fmt: fmtBigNum },
    { label: 'Free Cash Flow', value: info.free_cash_flow, fmt: fmtBigNum },
    { label: 'Operating Cash Flow', value: info.operating_cashflow, fmt: fmtBigNum },
    { label: 'Profit Margin', value: info.profit_margin, fmt: fmtPct },
    { label: 'Operating Margin', value: info.operating_margin, fmt: fmtPct },
    { label: 'Gross Margin', value: info.gross_margins, fmt: fmtPct },
    { label: 'EBITDA Margin', value: info.ebitda_margins, fmt: fmtPct },
    { label: 'Return on Equity', value: info.return_on_equity, fmt: fmtPct },
    { label: 'Return on Assets', value: info.return_on_assets, fmt: fmtPct },
    { label: 'Debt/Equity', value: info.debt_to_equity, fmt: v => v != null ? v.toFixed(1) : '—' },
    { label: 'Revenue Growth', value: info.revenue_growth, fmt: fmtPct },
    { label: 'Earnings Growth', value: info.earnings_growth, fmt: fmtPct },
    { label: 'Rev/Share', value: info.revenue_per_share, fmt: v => v != null ? `$${v.toFixed(2)}` : '—' },
  ].filter(m => m.value != null)

  const balanceSheet = [
    { label: 'Total Cash', value: info.total_cash, fmt: fmtBigNum },
    { label: 'Total Debt', value: info.total_debt, fmt: fmtBigNum },
    { label: 'Current Ratio', value: info.current_ratio, fmt: v => v != null ? v.toFixed(2) : '—' },
    { label: 'Quick Ratio', value: info.quick_ratio, fmt: v => v != null ? v.toFixed(2) : '—' },
  ].filter(m => m.value != null)

  const location = [info.city, info.state, info.country].filter(Boolean).join(', ')

  const profileFields = [
    { label: 'Sector', value: info.sector },
    { label: 'Industry', value: info.industry },
    { label: 'Exchange', value: info.exchange },
    { label: 'Currency', value: info.currency !== 'USD' ? info.currency : null },
  ].filter(f => f.value)

  const hasAnalyst = info.target_mean_price != null || info.analyst_count != null

  const recColor = {
    STRONG_BUY: 'bg-green-600', BUY: 'bg-green-700',
    buy: 'bg-green-700', strong_buy: 'bg-green-600',
    HOLD: 'bg-yellow-600', hold: 'bg-yellow-600',
    AVOID: 'bg-red-700', STRONG_AVOID: 'bg-red-600',
    sell: 'bg-red-700', strong_sell: 'bg-red-600',
    underperform: 'bg-red-700',
  }

  const recLabel = {
    buy: 'BUY', strong_buy: 'STRONG BUY', hold: 'HOLD',
    sell: 'SELL', strong_sell: 'STRONG SELL', underperform: 'UNDERPERFORM',
  }

  return (
    <div className="space-y-6">
      {/* Company profile */}
      {(profileFields.length > 0 || location || info.full_time_employees || info.website || info.long_business_summary) && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <h3 className="text-white font-semibold">Company Profile</h3>
          {(profileFields.length > 0 || location || info.full_time_employees || info.website) && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2 text-sm">
              {profileFields.map(f => (
                <div key={f.label}>
                  <span className="text-gray-500">{f.label}:</span>{' '}
                  <span className="text-white">{f.value}</span>
                </div>
              ))}
              {location && (
                <div>
                  <span className="text-gray-500">HQ:</span>{' '}
                  <span className="text-white">{location}</span>
                </div>
              )}
              {info.full_time_employees && (
                <div>
                  <span className="text-gray-500">Employees:</span>{' '}
                  <span className="text-white">{info.full_time_employees.toLocaleString()}</span>
                </div>
              )}
              {info.website && (
                <div>
                  <span className="text-gray-500">Website:</span>{' '}
                  <a href={info.website} target="_blank" rel="noopener noreferrer"
                    className="text-indigo-400 hover:text-indigo-300 underline">
                    {info.website.replace(/^https?:\/\/(www\.)?/, '')}
                  </a>
                </div>
              )}
            </div>
          )}

          {/* Business summary */}
          {info.long_business_summary && (
            <p className="text-gray-300 text-sm leading-relaxed">
              {info.long_business_summary}
            </p>
          )}
        </div>
      )}

      {/* Key People */}
      {info.company_officers?.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-white font-semibold mb-3">Key People</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-900/50">
                <tr className="text-gray-400">
                  <th className="px-3 py-2 text-left text-xs font-medium uppercase">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium uppercase">Title</th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase">Age</th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase">Total Pay</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {info.company_officers.map((o, i) => (
                  <tr key={i} className="hover:bg-gray-700/30">
                    <td className="px-3 py-2 text-white">{o.name}</td>
                    <td className="px-3 py-2 text-gray-400">{o.title}</td>
                    <td className="px-3 py-2 text-right text-gray-400 font-mono">{o.age || '—'}</td>
                    <td className="px-3 py-2 text-right text-gray-300 font-mono">{fmtPay(o.total_pay) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Valuation metrics */}
      {metrics.length > 0 && <MetricsGrid metrics={metrics} />}

      {/* Financial metrics */}
      {financialMetrics.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-white font-semibold mb-3">Financials</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {financialMetrics.map(m => (
              <div key={m.label} className="bg-gray-900/50 rounded-lg p-2.5">
                <p className="text-gray-500 text-xs uppercase">{m.label}</p>
                <p className={`text-white font-mono text-sm ${
                  m.value < 0 ? 'text-red-400' : ''
                }`}>
                  {m.fmt(m.value)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Balance sheet */}
      {balanceSheet.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-white font-semibold mb-3">Balance Sheet</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {balanceSheet.map(m => (
              <div key={m.label} className="bg-gray-900/50 rounded-lg p-2.5">
                <p className="text-gray-500 text-xs uppercase">{m.label}</p>
                <p className={`text-white font-mono text-sm ${
                  m.value < 0 ? 'text-red-400' : ''
                }`}>
                  {m.fmt(m.value)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Analyst consensus */}
      {hasAnalyst && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <div className="flex items-center gap-3">
            <h3 className="text-white font-semibold">Analyst Consensus</h3>
            {info.recommendation && (
              <span className={`px-2 py-0.5 rounded text-xs font-bold text-white ${
                recColor[info.recommendation] || 'bg-gray-600'
              }`}>
                {recLabel[info.recommendation] || info.recommendation.toUpperCase()}
              </span>
            )}
            {info.analyst_count != null && (
              <span className="text-gray-500 text-xs">{info.analyst_count} analysts</span>
            )}
          </div>
          {info.target_mean_price != null && (() => {
            const targets = [
              info.target_low_price != null && { label: 'Target Low', value: info.target_low_price, color: 'text-red-400' },
              { label: 'Target Mean', value: info.target_mean_price, color: 'text-white' },
              info.target_high_price != null && { label: 'Target High', value: info.target_high_price, color: 'text-green-400' },
            ].filter(Boolean)
            return (
              <div className={`grid gap-4 ${
                targets.length === 3 ? 'grid-cols-3' :
                targets.length === 2 ? 'grid-cols-2' : 'grid-cols-1'
              }`}>
                {targets.map(t => (
                  <div key={t.label} className="bg-gray-900/50 rounded-lg p-2.5">
                    <p className="text-gray-500 text-xs uppercase">{t.label}</p>
                    <p className={`${t.color} font-mono text-sm`}>${t.value.toFixed(2)}</p>
                  </div>
                ))}
              </div>
            )
          })()}
        </div>
      )}

      {/* LLM Analysis */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <h3 className="text-white font-semibold">LLM Analysis</h3>
        <div className="flex gap-2">
          <button
            onClick={() => handleAnalyse('all')}
            disabled={analysing}
            className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 text-white"
          >
            {analysing && analysisMode === 'all' ? 'Analysing...' : 'Analyse (All Sources)'}
          </button>
          <button
            onClick={() => handleAnalyse('legitimate')}
            disabled={analysing}
            className="px-3 py-1.5 rounded text-sm bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-600 text-white"
          >
            {analysing && analysisMode === 'legitimate' ? 'Analysing...' : 'Analyse (Legitimate Only)'}
          </button>
        </div>
        <p className="text-gray-500 text-xs">
          "All Sources" includes Reddit, StockTwits, SEC filings, and news.
          "Legitimate Only" uses SEC filings and news only.
        </p>
      </div>

      {/* Analysis result */}
      {analysis && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <div className="flex items-center gap-3">
            <h3 className="text-white font-semibold">Analysis Result</h3>
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
