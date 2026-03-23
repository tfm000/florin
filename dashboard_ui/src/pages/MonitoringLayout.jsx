import { NavLink, Outlet } from 'react-router-dom'

const TABS = [
  { path: '/monitoring/watchlist', label: 'Watchlist' },
  { path: '/monitoring/live', label: 'Live Monitor' },
]

export default function MonitoringLayout() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Monitoring</h1>

      {/* Sub-tab navigation */}
      <div className="flex gap-1 border-b border-gray-700">
        {TABS.map(tab => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) =>
              `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-indigo-500 text-white'
                  : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-600'
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </div>

      {/* Active tab content */}
      <Outlet />
    </div>
  )
}
