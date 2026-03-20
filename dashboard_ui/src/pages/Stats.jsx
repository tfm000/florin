import { useApi } from '../hooks/useApi'
import StatsCharts from '../components/StatsCharts'

export default function Stats() {
  const { data: stats, loading, error } = useApi('/stats')

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Trading Statistics</h1>

      {loading && <p className="text-gray-500">Loading statistics...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}

      {stats && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Total Trades" value={stats.total_trades} />
            <StatCard label="Round Trips" value={stats.round_trip_trades} />
            <StatCard
              label="Win Rate"
              value={`${stats.win_rate}%`}
              color={stats.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}
            />
            <StatCard
              label="Total P&L"
              value={`$${stats.total_pnl.toFixed(2)}`}
              color={stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
            />
            <StatCard label="Avg P&L/Trade" value={`$${stats.avg_pnl_per_trade.toFixed(2)}`} />
            <StatCard
              label="Best Trade"
              value={`$${stats.best_trade_pnl.toFixed(2)}`}
              color="text-green-400"
            />
            <StatCard
              label="Worst Trade"
              value={`$${stats.worst_trade_pnl.toFixed(2)}`}
              color="text-red-400"
            />
            <StatCard label="Winning" value={stats.winning_trades} />
          </div>

          {/* Charts */}
          <StatsCharts stats={stats} />
        </>
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
