import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import SearchBar from '../components/SearchBar'
import NewsCard from '../components/NewsCard'
import YieldCurveChart from '../components/YieldCurveChart'
import OptionsSurfaceChart from '../components/OptionsSurfaceChart'
import MetricsGrid from '../components/MetricsGrid'
import SectorPerformanceChart from '../components/SectorPerformanceChart'
import PresetCorrelationMatrix from '../components/PresetCorrelationMatrix'
import CorrelationMatrix, { CORR_METHODS, CORR_PERIODS } from '../components/CorrelationMatrix'
import MarketBreadth from '../components/MarketBreadth'
import MarketHours from '../components/MarketHours'

export default function Research() {
  const navigate = useNavigate()
  const { data: news, loading: newsLoading } = useApi('/research/news', { interval: 300000 }) // 5 min
  const { data: rates } = useApi('/research/policy-rates')
  const { data: macro } = useApi('/research/macro', { interval: 60000 }) // 60 sec auto-refresh

  // Shared correlation state
  const [corrMethod, setCorrMethod] = useState('pearson')
  const [corrPeriod, setCorrPeriod] = useState('1y')

  const handleSelect = (item) => {
    navigate(`/research/${item.ticker}`)
  }

  // Categorize macro indicators
  const categories = {
    'Indices': ['VIX', 'DXY', 'S&P 500', 'NASDAQ', 'Dow Jones', 'Russell 2000'],
    'Commodities': ['Crude Oil', 'Gold', 'Silver', 'Nat Gas'],
    'Fixed Income': ['10Y Yield'],
    'Crypto': ['Bitcoin', 'Ethereum', 'Solana'],
    'FX': ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD'],
  }

  const buildMetrics = (keys) => {
    if (!macro?.indicators) return []
    return keys
      .filter(k => macro.indicators[k])
      .map(label => {
        const v = macro.indicators[label]
        const isFx = label.includes('/')
        const isYield = label.includes('Yield') || label === 'VIX'
        return {
          label,
          value: v.price,
          format: isYield ? 'number' : isFx ? 'number' : 'dollar',
          color: v.change_pct >= 0 ? 'text-green-400' : 'text-red-400',
          ticker: v.ticker,
          changePct: v.change_pct,
        }
      })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold text-white">Research</h1>
        <SearchBar onSelect={handleSelect} placeholder="Search any asset..." />
      </div>

      {/* Market Hours */}
      <MarketHours />

      {/* Market Overview — categorised sections */}
      {macro?.indicators && Object.entries(categories).map(([cat, keys]) => {
        const metrics = buildMetrics(keys)
        if (metrics.length === 0) return null
        return (
          <div key={cat}>
            <h2 className="text-lg font-semibold text-gray-300 mb-3">{cat}</h2>
            <MetricsGrid metrics={metrics} />
          </div>
        )
      })}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* News Feed */}
        <div>
          <h2 className="text-lg font-semibold text-gray-300 mb-3">Market News</h2>
          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {newsLoading && <p className="text-gray-500 text-sm">Loading news...</p>}
            {(news || []).map((article, i) => (
              <NewsCard key={i} article={article} />
            ))}
            {!newsLoading && (news || []).length === 0 && (
              <p className="text-gray-500 text-sm">No news available</p>
            )}
          </div>
        </div>

        {/* Yield Curve */}
        <div>
          <YieldCurveChart />
        </div>
      </div>

      {/* Market Breadth */}
      <MarketBreadth />

      {/* Sector Performance */}
      <SectorPerformanceChart />

      {/* Correlation Matrices — unified controls */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-300">Correlation Matrices</h2>
          <div className="flex items-center gap-2">
            <select value={corrMethod} onChange={e => setCorrMethod(e.target.value)}
              className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white">
              {CORR_METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            <select value={corrPeriod} onChange={e => setCorrPeriod(e.target.value)}
              className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white">
              {CORR_PERIODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <PresetCorrelationMatrix
            title="Cross-Asset Correlation"
            tickers={['SPY', '^FTSE', '^GDAXI', 'GC=F', 'CL=F', 'NG=F']}
            labels={['S&P 500', 'FTSE 100', 'DAX', 'Gold', 'Oil', 'Nat Gas']}
            method={corrMethod}
            period={corrPeriod}
          />
          <PresetCorrelationMatrix
            title="S&P 500 Sector Correlation"
            tickers={['XLK', 'XLV', 'XLF', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE', 'XLC']}
            labels={['Tech', 'Health', 'Fin', 'Disc', 'Stpl', 'Energy', 'Ind', 'Mat', 'Util', 'RE', 'Comm']}
            method={corrMethod}
            period={corrPeriod}
          />
        </div>

        <CorrelationMatrix method={corrMethod} period={corrPeriod} hideControls />
      </div>

      {/* Options surface — SSVI/SABR + GP-residual + RND, pinned to
          SPY. Falls back to lastPrice off-hours with a stale-data
          banner; full pipeline runs during US market hours. */}
      <OptionsSurfaceChart initialTicker="SPY" />

      {/* G10 Policy Rates */}
      {rates && (
        <div>
          <h2 className="text-lg font-semibold text-gray-300 mb-3">G10 Policy Rates</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-800">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Country</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Central Bank</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Rate</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Currency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {rates.map(r => (
                  <tr key={r.country} className="hover:bg-gray-800/50">
                    <td className="px-3 py-2 text-white">{r.country}</td>
                    <td className="px-3 py-2 text-gray-400">{r.central_bank}</td>
                    <td className="px-3 py-2 text-right font-mono text-white">{r.rate.toFixed(2)}%</td>
                    <td className="px-3 py-2 text-gray-400 font-mono">{r.currency}</td>
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
