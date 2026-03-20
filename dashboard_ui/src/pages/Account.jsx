import { useApi } from '../hooks/useApi'
import TradeForm from '../components/TradeForm'

export default function Account() {
  const { data: account, loading, error, refetch } = useApi('/account', { interval: 30000 })
  const { data: pending, refetch: refetchPending } = useApi('/orders/pending', { interval: 10000 })

  const handleOrderComplete = () => {
    refetch()
    refetchPending()
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Account</h1>

      {loading && <p className="text-gray-500">Loading account...</p>}
      {error && <p className="text-red-400">Error: {error}</p>}

      {account && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <InfoCard label="Cash Available" value={`$${account.cash_available.toFixed(2)}`} />
          <InfoCard label="Invested Value" value={`$${account.invested_value.toFixed(2)}`} />
          <InfoCard label="Total Value" value={`$${account.total_value.toFixed(2)}`} />
          <InfoCard
            label="Unrealised P&L"
            value={`$${account.unrealised_pnl.toFixed(2)}`}
            color={account.unrealised_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
          />
          <InfoCard label="Realised P&L" value={`$${account.realised_pnl.toFixed(2)}`}
            color={account.realised_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
          />
          <InfoCard label="Reserved for Orders" value={`$${account.reserved_for_orders.toFixed(2)}`} />
          <InfoCard label="Currency" value={account.currency} />
          <InfoCard label="Account ID" value={account.account_id || 'N/A'} />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Trade Form */}
        <TradeForm onComplete={handleOrderComplete} />

        {/* Pending Orders */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-white font-bold mb-3">Pending Orders</h3>
          {pending && pending.length > 0 ? (
            <div className="space-y-2">
              {pending.map((order, i) => (
                <div key={i} className="bg-gray-900 rounded p-2 text-sm flex justify-between">
                  <span className="text-white">{JSON.stringify(order)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-sm">No pending orders</p>
          )}
        </div>
      </div>
    </div>
  )
}

function InfoCard({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
      <p className="text-gray-400 text-xs uppercase">{label}</p>
      <p className={`font-mono text-lg ${color}`}>{value}</p>
    </div>
  )
}
