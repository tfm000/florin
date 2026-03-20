import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Universe from './pages/Universe'
import Settings from './pages/Settings'
import Reports from './pages/Reports'
import TradeHistory from './pages/TradeHistory'
import Account from './pages/Account'
import Stats from './pages/Stats'

const NAV_ITEMS = [
  { path: '/', label: 'Dashboard' },
  { path: '/universe', label: 'Universe' },
  { path: '/reports', label: 'Reports' },
  { path: '/trades', label: 'Trades' },
  { path: '/account', label: 'Account' },
  { path: '/stats', label: 'Stats' },
  { path: '/settings', label: 'Settings' },
]

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-gray-100">
        {/* Nav Bar */}
        <nav className="bg-gray-800 border-b border-gray-700 px-4 py-3">
          <div className="max-w-7xl mx-auto flex items-center gap-6">
            <span className="text-white font-bold text-lg tracking-tight">Sentinel</span>
            <div className="flex gap-1">
              {NAV_ITEMS.map(item => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded text-sm ${
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
          </div>
        </nav>

        {/* Page Content */}
        <main className="max-w-7xl mx-auto px-4 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/universe" element={<Universe />} />
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
