import { useState } from 'react'
import { useParams, Link, NavLink, Outlet } from 'react-router-dom'
import { useApi, apiPost } from '../hooks/useApi'

export default function AssetLayout() {
  const { ticker } = useParams()
  const { data: info, loading } = useApi(`/research/asset/${ticker}`)
  const exchangeCode = info?.exchange || ''
  const { data: marketStatus } = useApi(
    `/market/status/${exchangeCode || '_'}`,
    { autoFetch: !!exchangeCode }
  )
  const [watchStatus, setWatchStatus] = useState(null)
  const [monitorStatus, setMonitorStatus] = useState(null)

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

  const tabs = [
    { path: `/research/${ticker}`, label: 'Overview', end: true },
    { path: `/research/${ticker}/quantitative`, label: 'Quantitative' },
    { path: `/research/${ticker}/options`, label: 'Options' },
    { path: `/research/${ticker}/holders`, label: 'Holders' },
    { path: `/research/${ticker}/broker`, label: 'Broker' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <Link to="/research" className="text-gray-400 hover:text-white text-sm">&larr; Research</Link>
          </div>
          <h1 className="text-3xl font-bold text-white font-mono mt-1">{ticker}</h1>
          <p className="text-gray-400 flex items-center gap-1.5">
            {info.name} &middot; {info.exchange}
            {marketStatus && (
              <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${
                marketStatus.is_open
                  ? 'bg-green-900/40 text-green-400'
                  : 'bg-gray-700 text-gray-400'
              }`}>
                <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                  marketStatus.is_open ? 'bg-green-400' : 'bg-gray-500'
                }`} />
                {marketStatus.is_open ? 'Open' : 'Closed'}
              </span>
            )}
            &middot; {info.sector}
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
        </div>
      </div>
      {watchStatus && <p className="text-xs text-gray-400">{watchStatus}</p>}
      {monitorStatus && <p className="text-xs text-gray-400">{monitorStatus}</p>}

      {/* Tab navigation */}
      <div className="flex gap-1 border-b border-gray-700">
        {tabs.map(tab => (
          <NavLink
            key={tab.path}
            to={tab.path}
            end={tab.end}
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
      <Outlet context={{ info, ticker }} />
    </div>
  )
}
