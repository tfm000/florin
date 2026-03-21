import { useApi } from '../hooks/useApi'

export default function MarketHours() {
  const { data, loading } = useApi('/market/hours', { interval: 60000 }) // refresh every minute

  if (loading || !data) return null

  const markets = data.markets || []

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-white font-semibold mb-3">Market Hours</h3>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {markets.map(m => (
          <div key={m.name} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-900/50">
            <span className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${
              m.is_open ? 'bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.5)]' : 'bg-gray-600'
            }`} />
            <div className="min-w-0">
              <p className={`text-sm font-medium truncate ${m.is_open ? 'text-white' : 'text-gray-500'}`}>
                {m.name}
              </p>
              <p className="text-xs text-gray-500">
                {m.local_time} · {m.is_open ? 'Open' : 'Closed'}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
