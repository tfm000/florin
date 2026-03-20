import { useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { useApi } from './hooks/useApi'
import Dashboard from './pages/Dashboard'
import Research from './pages/Research'
import AssetResearch from './pages/AssetResearch'
import Watchlist from './pages/Watchlist'
import LiveMonitor from './pages/LiveMonitor'
import Universe from './pages/Universe'
import Settings from './pages/Settings'
import Reports from './pages/Reports'
import TradeHistory from './pages/TradeHistory'
import Account from './pages/Account'
import Stats from './pages/Stats'

const NAV_ITEMS = [
  { path: '/', label: 'Dashboard' },
  { path: '/research', label: 'Research' },
  { path: '/watchlist', label: 'Watchlist' },
  { path: '/monitor', label: 'Live Monitor' },
  { path: '/penny-stocks', label: 'Penny Stocks' },
  { path: '/reports', label: 'Reports' },
  { path: '/trades', label: 'Trades' },
  { path: '/account', label: 'Account' },
  { path: '/stats', label: 'Stats' },
  { path: '/settings', label: 'Settings' },
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

export default function App() {
  const [terminating, setTerminating] = useState(false)

  const handleTerminate = async () => {
    if (!confirm('Shut down Sentinel? This will stop all services.')) return
    setTerminating(true)
    try {
      await fetch('/api/terminate', { method: 'POST' })
    } catch {
      // Server is shutting down, connection may drop
    }
  }

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-gray-100">
        {/* Nav Bar */}
        <nav className="bg-gray-800 border-b border-gray-700 px-4 py-3">
          <div className="max-w-7xl mx-auto flex items-center gap-4">
            <span className="text-white font-bold text-lg tracking-tight font-mono">Sentinel Terminal</span>
            <TradingModeBadge />
            <div className="flex gap-1 flex-1 overflow-x-auto">
              {NAV_ITEMS.map(item => (
                <NavLink
                  key={item.path}
                  to={item.path}
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
            <Route path="/" element={<Dashboard />} />
            <Route path="/research" element={<Research />} />
            <Route path="/research/:ticker" element={<AssetResearch />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/monitor" element={<LiveMonitor />} />
            <Route path="/penny-stocks" element={<Universe />} />
            <Route path="/universe" element={<Navigate to="/penny-stocks" replace />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/trades" element={<TradeHistory />} />
            <Route path="/account" element={<Account />} />
            <Route path="/stats" element={<Stats />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
