import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'

const COLORS = ['#22c55e', '#ef4444']

export default function StatsCharts({ stats }) {
  if (!stats || stats.total_trades === 0) {
    return <p className="text-gray-500 text-center py-8">No trading data yet</p>
  }

  const winLossData = [
    { name: 'Wins', value: stats.winning_trades },
    { name: 'Losses', value: stats.losing_trades },
  ]

  const pnlData = [
    { name: 'Total P&L', value: stats.total_pnl },
    { name: 'Avg/Trade', value: stats.avg_pnl_per_trade },
    { name: 'Best', value: stats.best_trade_pnl },
    { name: 'Worst', value: stats.worst_trade_pnl },
  ]

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {/* Win/Loss Pie */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h4 className="text-gray-400 text-sm mb-3">Win/Loss Ratio</h4>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={winLossData}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              dataKey="value"
              label={({ name, value }) => `${name}: ${value}`}
            >
              {winLossData.map((_, i) => (
                <Cell key={i} fill={COLORS[i]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
        <p className="text-center text-white font-mono mt-2">{stats.win_rate}% Win Rate</p>
      </div>

      {/* P&L Bar Chart */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h4 className="text-gray-400 text-sm mb-3">P&L Summary</h4>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={pnlData}>
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 12 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} />
            <Tooltip />
            <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
