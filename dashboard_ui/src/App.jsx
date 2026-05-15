import { useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useParams } from 'react-router-dom'
import { useApi } from './hooks/useApi'
import { ChartColorProvider } from './hooks/useChartColors'
import Dashboard from './pages/Dashboard'
import Research from './pages/Research'
import AssetLayout from './pages/AssetLayout'
import OverviewTab from './pages/OverviewTab'
import QuantitativeTab from './pages/QuantitativeTab'
import OptionsTab from './pages/OptionsTab'
import HoldersTab from './pages/HoldersTab'
import BrokerTab from './pages/BrokerTab'
import Watchlist from './pages/Watchlist'
import LiveMonitor from './pages/LiveMonitor'
import MonitoringLayout from './pages/MonitoringLayout'
import TradingLayout from './pages/TradingLayout'
import TradingSettings from './pages/TradingSettings'
import TradingScreeners from './pages/TradingScreeners'
import Settings from './pages/Settings'
import Reports from './pages/Reports'
import TradeHistory from './pages/TradeHistory'
import Account from './pages/Account'
import Stats from './pages/Stats'
import NewsLayout from './pages/NewsLayout'
import EconomicCalendar from './pages/EconomicCalendar'
import EarningsCalendar from './pages/EarningsCalendar'
import Screener from './pages/Screener'
import Filings13F from './pages/Filings13F'
import MonitorAsset from './pages/MonitorAsset'
import DataDownload from './pages/DataDownload'
import MarketNews from './pages/MarketNews'
import Portfolio from './pages/Portfolio'
import PortfolioDetail from './pages/PortfolioDetail'

const NAV_ITEMS = [
  { path: '/', label: 'Research' },
  { path: '/monitoring', label: 'Monitoring' },
  { path: '/screener', label: 'Screener' },
  { path: '/13f', label: '13F' },
  { path: '/news', label: 'News' },
  { path: '/reports', label: 'Reports' },
  { path: '/portfolio', label: 'Portfolio' },
  { path: '/data', label: 'Data' },
  { path: '/trading', label: 'Trading' },
]

function TradingModeBadge() {
  const { data: health } = useApi('/health', { interval: 30000 })
  if (!health) return null
  const isPaper = health.paper_trading
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold ${
      isPaper ? 'bg-yellow-800 text-yellow-300' : 'bg-red-800 text-red-300'
    }`}>
      {isPaper ? 'PAPER' : 'LIVE'}
    </span>
  )
}

/** Redirect preserving the :ticker param from the old /monitor/:ticker path. */
function RedirectWithParams({ to }) {
  const { ticker } = useParams()
  return <Navigate to={`${to}/${ticker}`} replace />
}

/** Gear icon SVG for the settings button. */
function GearIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
      <path fillRule="evenodd" d="M7.84 1.804A1 1 0 0 1 8.82 1h2.36a1 1 0 0 1 .98.804l.331 1.652a6.993 6.993 0 0 1 1.929 1.115l1.598-.54a1 1 0 0 1 1.186.447l1.18 2.044a1 1 0 0 1-.205 1.251l-1.267 1.113a7.047 7.047 0 0 1 0 2.228l1.267 1.113a1 1 0 0 1 .206 1.25l-1.18 2.045a1 1 0 0 1-1.187.447l-1.598-.54a6.993 6.993 0 0 1-1.929 1.115l-.33 1.652a1 1 0 0 1-.98.804H8.82a1 1 0 0 1-.98-.804l-.331-1.652a6.993 6.993 0 0 1-1.929-1.115l-1.598.54a1 1 0 0 1-1.186-.447l-1.18-2.044a1 1 0 0 1 .205-1.251l1.267-1.114a7.05 7.05 0 0 1 0-2.227L1.821 7.773a1 1 0 0 1-.206-1.25l1.18-2.045a1 1 0 0 1 1.187-.447l1.598.54A6.992 6.992 0 0 1 7.51 3.456l.33-1.652ZM10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" clipRule="evenodd" />
    </svg>
  )
}

export default function App() {
  const [terminating, setTerminating] = useState(false)

  const handleTerminate = async () => {
    if (!confirm('Shut down the terminal? This will stop all services.')) return
    setTerminating(true)
    try {
      await fetch('/api/terminate', { method: 'POST' })
    } catch {
      // Server is shutting down, connection may drop
    }
  }

  return (
    <ChartColorProvider>
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-gray-100">
        {/* Nav Bar */}
        <nav className="bg-gray-800 border-b border-gray-700 px-4 py-3">
          <div className="max-w-7xl mx-auto flex items-center gap-4">
            <img src="/florin.png" alt="Florin" className="h-7 w-auto" />
            <span className="text-white font-bold text-lg tracking-tight font-mono">Florin Terminal</span>
            <TradingModeBadge />
            <div className="flex gap-1 flex-1 overflow-x-auto">
              {NAV_ITEMS.map(item => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  end={item.path === '/'}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded text-sm whitespace-nowrap ${
                      isActive
                        ? 'bg-indigo-600 text-white'
                        : 'text-gray-400 hover:text-white hover:bg-gray-700'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
            {/* Settings gear icon */}
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                `p-1.5 rounded transition-colors ${
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-700'
                }`
              }
              title="System Settings"
            >
              <GearIcon />
            </NavLink>
            <button
              onClick={handleTerminate}
              disabled={terminating}
              className="px-3 py-1.5 rounded text-sm font-medium bg-red-700 hover:bg-red-600 disabled:bg-gray-600 text-white transition-colors"
            >
              {terminating ? 'Shutting down...' : 'Terminate'}
            </button>
          </div>
        </nav>

        {/* Page Content */}
        <main className="max-w-7xl mx-auto px-4 py-6">
          <Routes>
            {/* Research is the home page */}
            <Route path="/" element={<Research />} />
            <Route path="/research" element={<Navigate to="/" replace />} />
            <Route path="/research/:ticker" element={<AssetLayout />}>
              <Route index element={<OverviewTab />} />
              <Route path="quantitative" element={<QuantitativeTab />} />
              <Route path="options" element={<OptionsTab />} />
              <Route path="holders" element={<HoldersTab />} />
              <Route path="broker" element={<BrokerTab />} />
            </Route>

            {/* Monitoring — Watchlist + Live Monitor */}
            <Route path="/monitoring" element={<MonitoringLayout />}>
              <Route index element={<Navigate to="watchlist" replace />} />
              <Route path="watchlist" element={<Watchlist />} />
              <Route path="live" element={<LiveMonitor />} />
            </Route>
            <Route path="/monitoring/live/:ticker" element={<MonitorAsset />} />

            {/* Screener */}
            <Route path="/screener" element={<Screener />} />

            {/* Trading — Overview, Account, Trades, Stats, Screeners, Settings */}
            <Route path="/trading" element={<TradingLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="account" element={<Account />} />
              <Route path="trades" element={<TradeHistory />} />
              <Route path="stats" element={<Stats />} />
              <Route path="screeners" element={<TradingScreeners />} />
              <Route path="settings" element={<TradingSettings />} />
            </Route>

            {/* Standalone pages */}
            <Route path="/13f" element={<Filings13F />} />
            <Route path="/news" element={<NewsLayout />}>
              <Route index element={<MarketNews />} />
              <Route path="economic" element={<EconomicCalendar />} />
              <Route path="earnings" element={<EarningsCalendar />} />
            </Route>
            <Route path="/calendar" element={<Navigate to="/news/economic" replace />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/portfolio/:portfolioId" element={<PortfolioDetail />} />
            <Route path="/data" element={<DataDownload />} />
            <Route path="/settings" element={<Settings />} />

            {/* Redirects for old paths */}
            <Route path="/watchlist" element={<Navigate to="/monitoring/watchlist" replace />} />
            <Route path="/monitor" element={<Navigate to="/monitoring/live" replace />} />
            <Route path="/monitor/:ticker" element={<RedirectWithParams to="/monitoring/live" />} />
            <Route path="/account" element={<Navigate to="/trading/account" replace />} />
            <Route path="/trades" element={<Navigate to="/trading/trades" replace />} />
            <Route path="/stats" element={<Navigate to="/trading/stats" replace />} />
            <Route path="/penny-stocks" element={<Navigate to="/screener" replace />} />
            <Route path="/universe" element={<Navigate to="/screener" replace />} />
            <Route path="/insiders" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
    </ChartColorProvider>
  )
}
