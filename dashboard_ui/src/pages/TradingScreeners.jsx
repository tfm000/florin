import { useNavigate } from 'react-router-dom'
import { useApi, apiDelete } from '../hooks/useApi'

export default function TradingScreeners() {
  const navigate = useNavigate()
  const { data: screeners, loading, refetch } = useApi('/screener/saved')

  const handleDelete = async (e, id, name) => {
    e.stopPropagation()
    if (!confirm(`Delete screener "${name}"?`)) return
    try {
      await apiDelete(`/screener/saved/${id}`)
      refetch()
    } catch { /* ignore */ }
  }

  const items = screeners || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-300">Saved Screeners</h2>
        <button
          onClick={() => navigate('/screener')}
          className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded font-medium transition-colors"
        >
          New Screener
        </button>
      </div>

      {loading && <p className="text-gray-500 text-sm">Loading...</p>}

      {!loading && items.length === 0 && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-8 text-center">
          <p className="text-gray-400 mb-4">No saved screeners yet.</p>
          <p className="text-gray-500 text-sm">
            Use the Screener to filter assets, then save your filter settings here for quick access and live alerts.
          </p>
        </div>
      )}

      {items.length > 0 && (
        <div className="space-y-2">
          {items.map(s => (
            <div
              key={s.id}
              onClick={() => navigate(`/screener?preset=${s.id}`)}
              className="bg-gray-800 rounded-lg border border-gray-700 p-4 hover:border-indigo-500 cursor-pointer transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-white font-semibold">{s.name}</h3>
                  <p className="text-gray-500 text-xs mt-1">
                    {_summarizeFilters(s.filters)}
                  </p>
                  <p className="text-gray-600 text-xs mt-0.5">
                    Created: {s.created_at?.slice(0, 10)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {/* Alert status — greyed out placeholder for Phase 7 */}
                  <span className="text-xs text-gray-600" title="Live alerts (coming soon)">
                    {s.is_alert_active ? 'Alerting' : 'No alerts'}
                  </span>
                  <button
                    onClick={(e) => handleDelete(e, s.id, s.name)}
                    className="px-2 py-1 text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded text-xs transition-colors"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function _summarizeFilters(filters) {
  if (!filters || typeof filters !== 'object') return 'No filters'
  const parts = []
  if (filters.price_min || filters.price_max) {
    const min = filters.price_min || '0'
    const max = filters.price_max || '\u221E'
    parts.push(`Price: $${min}-$${max}`)
  }
  if (filters.sector) parts.push(filters.sector)
  if (filters.asset_type) parts.push(filters.asset_type)
  if (filters.momentum_period) parts.push(`Momentum: ${filters.momentum_period}`)
  return parts.length > 0 ? parts.join(' \u00B7 ') : 'All US equities'
}
