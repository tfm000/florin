import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, apiDelete, apiPut } from '../hooks/useApi'
import { useChartColors } from '../hooks/useChartColors'
import { valueColor } from '../utils/colors'
import { EXCHANGE_LABELS } from '../utils/exchanges'

const INTERVAL_OPTIONS = [
  { value: 60, label: '1 min' },
  { value: 300, label: '5 min' },
  { value: 900, label: '15 min' },
  { value: 1800, label: '30 min' },
  { value: 3600, label: '1 hour' },
]

export default function TradingScreeners() {
  const navigate = useNavigate()
  const { data: screeners, loading, error, refetch } = useApi('/screener/saved')
  const [expandedId, setExpandedId] = useState(null)
  const [actionError, setActionError] = useState(null)

  const handleDelete = async (e, id, name) => {
    e.stopPropagation()
    if (!confirm(`Delete screener "${name}"?`)) return
    try {
      setActionError(null)
      await apiDelete(`/screener/saved/${id}`)
      refetch()
    } catch (err) {
      setActionError(`Failed to delete "${name}": ${err.message}`)
    }
  }

  const handleToggleAlert = async (e, id, currentState) => {
    e.stopPropagation()
    try {
      setActionError(null)
      await apiPut(`/screener/saved/${id}/alerts`, {
        is_alert_active: !currentState,
      })
      refetch()
    } catch (err) {
      setActionError(`Failed to toggle alerts: ${err.message}`)
    }
  }

  const handleUpdateAlertSetting = async (id, field, value) => {
    try {
      setActionError(null)
      await apiPut(`/screener/saved/${id}/alerts`, { [field]: value })
      refetch()
    } catch (err) {
      setActionError(`Failed to update setting: ${err.message}`)
    }
  }

  const toggleExpand = (e, id) => {
    e.stopPropagation()
    setExpandedId(prev => prev === id ? null : id)
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

      {actionError && (
        <div className="px-4 py-3 rounded text-sm bg-red-900/50 text-red-300 border border-red-700">
          {actionError}
        </div>
      )}

      {loading && <p className="text-gray-500 text-sm">Loading...</p>}

      {error && !loading && (
        <div className="bg-gray-800 rounded-lg border border-red-700 p-8 text-center">
          <p className="text-red-400 mb-2">Failed to load screeners</p>
          <p className="text-gray-500 text-sm">{error}</p>
        </div>
      )}

      {!loading && !error && items.length === 0 && (
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
            <div key={s.id} className="bg-gray-800 rounded-lg border border-gray-700 transition-colors">
              {/* Main row */}
              <div
                onClick={() => navigate(`/screener?preset=${s.id}`)}
                className="p-4 hover:border-indigo-500 cursor-pointer"
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold">{s.name}</h3>
                    <p className="text-gray-500 text-xs mt-1">
                      {_summarizeFilters(s.filters)}
                    </p>
                    <p className="text-gray-600 text-xs mt-0.5">
                      Created: {s.created_at?.slice(0, 10)}
                      {s.last_run_at && ` · Last run: ${s.last_run_at.slice(0, 19)}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    {/* Alert toggle */}
                    <button
                      onClick={(e) => handleToggleAlert(e, s.id, s.is_alert_active)}
                      className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                        s.is_alert_active
                          ? 'bg-green-900/40 text-green-400 hover:bg-green-900/60'
                          : 'bg-gray-700 text-gray-500 hover:bg-gray-600 hover:text-gray-300'
                      }`}
                      title={s.is_alert_active ? 'Click to disable alerts' : 'Click to enable alerts'}
                    >
                      {s.is_alert_active ? 'Alerting' : 'Alerts Off'}
                    </button>
                    {/* Expand settings */}
                    <button
                      onClick={(e) => toggleExpand(e, s.id)}
                      className="px-2 py-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded text-xs transition-colors"
                      title="Alert settings"
                    >
                      {expandedId === s.id ? '▲' : '▼'}
                    </button>
                    <button
                      onClick={(e) => handleDelete(e, s.id, s.name)}
                      className="px-2 py-1 text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded text-xs transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>

              {/* Expanded alert settings */}
              {expandedId === s.id && (
                <div
                  className="border-t border-gray-700 px-4 py-3 space-y-3"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <label className="text-gray-400 block mb-1">Run Interval</label>
                      <select
                        value={s.run_interval_seconds}
                        onChange={(e) => handleUpdateAlertSetting(s.id, 'run_interval_seconds', Number(e.target.value))}
                        className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-white"
                      >
                        {INTERVAL_OPTIONS.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-gray-400 block mb-1">Max Alerts/Day</label>
                      <input
                        type="number"
                        defaultValue={s.max_alerts_per_day}
                        onBlur={(e) => {
                          const val = Math.max(1, Number(e.target.value))
                          if (val !== s.max_alerts_per_day) {
                            handleUpdateAlertSetting(s.id, 'max_alerts_per_day', val)
                          }
                        }}
                        min="1" max="100"
                        className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-white"
                      />
                    </div>
                    <div className="flex items-end">
                      <label className="flex items-center gap-2 text-gray-400 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={s.include_llm_report}
                          onChange={(e) => handleUpdateAlertSetting(s.id, 'include_llm_report', e.target.checked)}
                          className="rounded bg-gray-700 border-gray-600"
                        />
                        <span>Include LLM Report</span>
                      </label>
                    </div>
                  </div>

                  {/* Analysis type selection (only shown when LLM report enabled) */}
                  {s.include_llm_report && (
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-gray-500">Analysis types:</span>
                      {['announcement', 'sentiment'].map(t => {
                        const types = s.analysis_types || ['announcement', 'sentiment']
                        const checked = types.includes(t)
                        return (
                          <label key={t} className="flex items-center gap-1.5 text-gray-400 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                const next = checked
                                  ? types.filter(x => x !== t)
                                  : [...types, t]
                                // Don't allow empty — must have at least one
                                if (next.length > 0) {
                                  handleUpdateAlertSetting(s.id, 'analysis_types', next)
                                }
                              }}
                              className="rounded bg-gray-700 border-gray-600"
                            />
                            <span>{t === 'announcement' ? 'Announcements (8-K)' : 'Sentiment'}</span>
                          </label>
                        )
                      })}
                    </div>
                  )}

                  {/* Alert log */}
                  <AlertLog screenerId={s.id} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AlertLog({ screenerId }) {
  const colors = useChartColors()
  const { data: alerts, loading, error } = useApi(`/screener/saved/${screenerId}/alerts?limit=20`)

  if (loading) return <p className="text-gray-600 text-xs">Loading alerts...</p>
  if (error) return <p className="text-red-400 text-xs">Failed to load alerts: {error}</p>
  if (!alerts || alerts.length === 0) {
    return <p className="text-gray-600 text-xs">No alerts sent yet.</p>
  }

  return (
    <div>
      <h4 className="text-gray-400 text-xs font-medium mb-1">Recent Alerts</h4>
      <div className="max-h-40 overflow-y-auto space-y-1">
        {alerts.map(a => (
          <div key={a.id} className="flex items-center justify-between text-xs bg-gray-900/50 rounded px-2 py-1">
            <div className="flex items-center gap-2">
              <span className="text-white font-mono font-semibold">{a.ticker}</span>
              {a.price != null && <span className="text-gray-400">${a.price.toFixed(2)}</span>}
              {a.change_pct != null && (
                <span style={{ color: valueColor(a.change_pct, colors) }}>
                  {a.change_pct >= 0 ? '+' : ''}{a.change_pct.toFixed(2)}%
                </span>
              )}
            </div>
            <span className="text-gray-600">{a.sent_at?.slice(0, 16)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const ASSET_TYPE_LABELS = {
  EQUITY: 'Stocks', ETF: 'ETFs', MUTUALFUND: 'Mutual Funds',
  INDEX: 'Indices', CRYPTOCURRENCY: 'Crypto',
}

function _summarizeFilters(filters) {
  if (!filters || typeof filters !== 'object') return 'No filters'
  const parts = []
  if (filters.price_min != null || filters.price_max != null) {
    const min = filters.price_min ?? '0'
    const max = filters.price_max ?? '\u221E'
    parts.push(`Price: $${min}-$${max}`)
  }
  if (filters.sector) parts.push(filters.sector)
  if (filters.asset_type) parts.push(ASSET_TYPE_LABELS[filters.asset_type] || filters.asset_type)
  if (filters.exchange) parts.push(EXCHANGE_LABELS[filters.exchange] || filters.exchange)
  if (filters.currency) parts.push(filters.currency)
  if (filters.momentum_period) parts.push(`Momentum: ${filters.momentum_period}`)
  return parts.length > 0 ? parts.join(' \u00B7 ') : 'All US assets'
}
