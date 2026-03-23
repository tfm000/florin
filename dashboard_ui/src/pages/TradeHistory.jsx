import { useApi } from '../hooks/useApi'
import ExportButton from '../components/ExportButton'

export default function TradeHistory() {
  const { data: trades, loading, error } = useApi('/trades')

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold text-gray-300">Trade History</h2>
        <div className="flex items-center gap-3">
          {trades && <span className="text-gray-400 text-sm">{trades.length} trades</span>}
          {trades?.length > 0 && <ExportButton data={trades} filename="trades" />}
        </div>
      </div>

      {loading && <p className="text-gray-500">Loading trades...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}

      {trades && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Date</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Ticker</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Side</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Qty</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Price</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Value</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">P&L</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {trades.map(t => (
                <tr key={t.id} className="hover:bg-gray-800/50">
                  <td className="px-3 py-2 text-gray-400 text-xs">{t.executed_at}</td>
                  <td className="px-3 py-2 font-mono text-white">{t.ticker}</td>
                  <td className={`px-3 py-2 font-bold text-xs ${t.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                    {t.side}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-300">{t.quantity}</td>
                  <td className="px-3 py-2 font-mono text-gray-300">${t.price.toFixed(2)}</td>
                  <td className="px-3 py-2 font-mono text-gray-300">${t.total_value.toFixed(2)}</td>
                  <td className={`px-3 py-2 font-mono ${
                    t.realised_pnl == null ? 'text-gray-500' :
                    t.realised_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {t.realised_pnl != null ? `$${t.realised_pnl.toFixed(2)}` : '-'}
                  </td>
                  <td className="px-3 py-2 text-gray-400 text-xs">{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length === 0 && (
            <p className="text-gray-500 text-center py-8">No trades executed yet</p>
          )}
        </div>
      )}
    </div>
  )
}
