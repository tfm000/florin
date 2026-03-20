import { useNavigate } from 'react-router-dom'
import { useApi, apiDelete } from '../hooks/useApi'

export default function Watchlist() {
  const navigate = useNavigate()
  const { data, loading, refetch } = useApi('/watchlist')
  const items = data?.items || []

  const handleRemove = async (e, ticker) => {
    e.stopPropagation()
    try {
      await apiDelete(`/watchlist/${ticker}`)
      refetch()
    } catch { /* ignore */ }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-white">Watchlist</h1>
        {data && <span className="text-gray-400 text-sm">{data.total} assets</span>}
      </div>

      {loading && <p className="text-gray-500">Loading watchlist...</p>}

      {!loading && items.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <p className="mb-2">Your watchlist is empty</p>
          <button
            onClick={() => navigate('/research')}
            className="text-indigo-400 hover:text-indigo-300 text-sm underline"
          >
            Search for assets to watch
          </button>
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Ticker</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Name</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Type</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Notes</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase">Added</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {items.map(item => (
                <tr
                  key={item.ticker}
                  onClick={() => navigate(`/research/${item.ticker}`)}
                  className="hover:bg-gray-800/50 cursor-pointer"
                >
                  <td className="px-3 py-2 font-mono text-white font-semibold">{item.ticker}</td>
                  <td className="px-3 py-2 text-gray-300 truncate max-w-48">{item.name}</td>
                  <td className="px-3 py-2 text-gray-400 capitalize">{item.asset_type}</td>
                  <td className="px-3 py-2 text-gray-400 truncate max-w-40">{item.notes || '—'}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs">{new Date(item.added_at).toLocaleDateString()}</td>
                  <td className="px-3 py-2">
                    <button
                      onClick={(e) => handleRemove(e, item.ticker)}
                      className="text-red-500 hover:text-red-400 text-xs"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
