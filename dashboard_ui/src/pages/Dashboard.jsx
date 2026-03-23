import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import PositionCard from '../components/PositionCard'
import AlertFeed from '../components/AlertFeed'

export default function Dashboard() {
  const { data: positions, loading: posLoading } = useApi('/positions', { interval: 30000 })
  const { data: account, loading: accLoading } = useApi('/account', { interval: 30000 })
  const { data: stats } = useApi('/stats')
  const { data: health } = useApi('/health', { interval: 30000 })
  const { data: watchlist } = useApi('/watchlist?limit=1')
  const { data: monitor } = useApi('/monitor?limit=1')

  const unconfigured = health?.setup_checklist?.filter(item => !item.configured) || []

  return (
    <div className="space-y-6">
      {/* Setup Banner */}
      {unconfigured.length > 0 && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4">
          <h3 className="text-yellow-400 font-semibold mb-2">Setup Required</h3>
          <p className="text-yellow-300/80 text-sm mb-3">
            The data pipeline needs the following to be configured before stocks can be scanned:
          </p>
          <ul className="space-y-1 mb-3">
            {unconfigured.map(item => (
              <li key={item.key} className="text-sm text-yellow-300/70 flex items-start gap-2">
                <span className="text-yellow-500 mt-0.5">&#x2022;</span>
                <span><span className="text-yellow-300">{item.label}</span> — {item.description}</span>
              </li>
            ))}
          </ul>
          <Link
            to="/trading/settings"
            className="inline-block text-sm text-yellow-400 hover:text-yellow-300 underline"
          >
            Go to Settings &rarr;
          </Link>
        </div>
      )}

      {/* Quick Links */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <QuickLink to="/" label="Research" description="Search & analyse any asset" />
        <QuickLink to="/monitoring/watchlist" label="Watchlist" count={watchlist?.total} />
        <QuickLink to="/monitoring/live" label="Live Monitor" count={monitor?.total} />
        <QuickLink to="/screener" label="Screener" />
      </div>

      {/* Account Summary */}
      {account && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Cash" value={`$${account.cash_available.toFixed(2)}`} />
          <StatCard label="Invested" value={`$${account.invested_value.toFixed(2)}`} />
          <StatCard label="Total Value" value={`$${account.total_value.toFixed(2)}`} />
          <StatCard
            label="Unrealised P&L"
            value={`${account.unrealised_pnl >= 0 ? '+' : ''}$${account.unrealised_pnl.toFixed(2)}`}
            color={account.unrealised_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
          />
        </div>
      )}
      {accLoading && <p className="text-gray-500">Loading account...</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Positions */}
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-lg font-bold text-gray-300">Open Positions</h2>
          {posLoading && <p className="text-gray-500">Loading positions...</p>}
          {positions && positions.length === 0 && (
            <p className="text-gray-500">No open positions</p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(positions || []).map(p => (
              <PositionCard key={p.ticker} position={p} />
            ))}
          </div>
        </div>

        {/* Alert Feed */}
        <div>
          <AlertFeed />
        </div>
      </div>

      {/* Quick Stats */}
      {stats && stats.total_trades > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Total Trades" value={stats.total_trades} />
          <StatCard label="Win Rate" value={`${stats.win_rate}%`} color={stats.win_rate >= 50 ? 'text-green-400' : 'text-red-400'} />
          <StatCard label="Total P&L" value={`$${stats.total_pnl.toFixed(2)}`} color={stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'} />
          <StatCard label="Round Trips" value={stats.round_trip_trades} />
        </div>
      ) : stats && unconfigured.length === 0 && (
        <p className="text-gray-500 text-sm">
          No trades yet — the scanner is running and will generate alerts when momentum is detected.
        </p>
      )}
    </div>
  )
}

function StatCard({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
      <p className="text-gray-400 text-xs uppercase">{label}</p>
      <p className={`font-mono text-lg ${color}`}>{value}</p>
    </div>
  )
}

function QuickLink({ to, label, description, count }) {
  return (
    <Link
      to={to}
      className="bg-gray-800 rounded-lg p-3 border border-gray-700 hover:border-indigo-500 transition-colors block"
    >
      <div className="flex justify-between items-start">
        <p className="text-white font-semibold text-sm">{label}</p>
        {count != null && (
          <span className="text-xs text-gray-400 font-mono">{count}</span>
        )}
      </div>
      {description && <p className="text-gray-500 text-xs mt-1">{description}</p>}
    </Link>
  )
}
