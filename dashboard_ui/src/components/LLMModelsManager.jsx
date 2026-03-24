import { useState, useEffect, useCallback } from 'react'
import { useApi, apiPost, apiPut, apiDelete } from '../hooks/useApi'

/**
 * LLM Models Manager — register, edit, test, and delete LLM model configurations.
 *
 * Each model is a host + model name + API key combination that can be
 * assigned to analysis roles (announcement, sentiment, consensus leader).
 */
export default function LLMModelsManager() {
  const { data: models, loading, refetch } = useApi('/llm-models')
  const { data: hosts } = useApi('/llm-models/hosts')
  const [showAdd, setShowAdd] = useState(false)
  const [message, setMessage] = useState(null)

  const clearMessage = useCallback(() => {
    const timer = setTimeout(() => setMessage(null), 5000)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (message) return clearMessage()
  }, [message, clearMessage])

  const handleDelete = async (id, displayName) => {
    if (!confirm(`Delete model "${displayName}"?`)) return
    try {
      const result = await apiDelete(`/llm-models/${id}`)
      const warnings = result.warnings?.length
        ? ` Warning: ${result.warnings.join('; ')}`
        : ''
      setMessage({ type: 'success', text: `Deleted ${displayName}.${warnings}` })
      refetch()
    } catch (err) {
      setMessage({ type: 'error', text: err.message })
    }
  }

  const handleToggle = async (id, enabled) => {
    try {
      await apiPut(`/llm-models/${id}`, { enabled: !enabled })
      refetch()
    } catch (err) {
      setMessage({ type: 'error', text: err.message })
    }
  }

  const handleHealthCheck = async (id) => {
    setMessage({ type: 'info', text: 'Running health check...' })
    try {
      const result = await apiPost(`/llm-models/${id}/health-check`)
      if (result.ok) {
        setMessage({ type: 'success', text: 'Health check passed' })
      } else {
        setMessage({ type: 'error', text: `Health check failed: ${result.error || 'Unknown error'}` })
      }
    } catch (err) {
      setMessage({ type: 'error', text: err.message })
    }
  }

  if (loading) return <p className="text-gray-500 text-sm">Loading LLM models...</p>

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <div className="px-5 py-4 flex items-center justify-between border-b border-gray-700">
        <h2 className="text-lg font-bold text-gray-200">LLM Models</h2>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded font-medium transition-colors"
        >
          {showAdd ? 'Cancel' : '+ Add Model'}
        </button>
      </div>

      {message && (
        <div className={`mx-5 mt-3 px-3 py-2 rounded text-sm ${
          message.type === 'error' ? 'bg-red-900/50 text-red-300 border border-red-700'
          : message.type === 'info' ? 'bg-blue-900/50 text-blue-300 border border-blue-700'
          : 'bg-green-900/50 text-green-300 border border-green-700'
        }`}>
          {message.text}
        </div>
      )}

      {showAdd && (
        <AddModelForm
          hosts={hosts || []}
          onSuccess={() => { setShowAdd(false); refetch() }}
          onMessage={setMessage}
        />
      )}

      <div className="p-5 space-y-3">
        {(!models || models.length === 0) ? (
          <p className="text-gray-500 text-sm">No models registered. Click "+ Add Model" to get started.</p>
        ) : (
          models.map(model => (
            <ModelCard
              key={model.id}
              model={model}
              onDelete={handleDelete}
              onToggle={handleToggle}
              onHealthCheck={handleHealthCheck}
            />
          ))
        )}
      </div>
    </div>
  )
}


function ModelCard({ model, onDelete, onToggle, onHealthCheck }) {
  return (
    <div className={`flex items-center justify-between p-3 rounded-lg border ${
      model.enabled
        ? 'bg-gray-750 border-gray-600'
        : 'bg-gray-800/50 border-gray-700 opacity-60'
    }`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-white text-sm font-medium truncate">{model.display_name}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${
            model.enabled ? 'bg-green-900/50 text-green-400' : 'bg-gray-700 text-gray-400'
          }`}>
            {model.enabled ? 'Active' : 'Disabled'}
          </span>
        </div>
        <div className="text-gray-500 text-xs mt-0.5 font-mono">{model.api_key_masked}</div>
      </div>

      <div className="flex items-center gap-1.5 ml-3 shrink-0">
        <button
          onClick={() => onHealthCheck(model.id)}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
          title="Test connectivity"
        >
          Test
        </button>
        <button
          onClick={() => onToggle(model.id, model.enabled)}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
          title={model.enabled ? 'Disable' : 'Enable'}
        >
          {model.enabled ? 'Disable' : 'Enable'}
        </button>
        <button
          onClick={() => onDelete(model.id, model.display_name)}
          className="px-2 py-1 text-xs bg-red-900/50 hover:bg-red-800/50 text-red-400 rounded transition-colors"
          title="Delete model"
        >
          Delete
        </button>
      </div>
    </div>
  )
}


function AddModelForm({ hosts, onSuccess, onMessage }) {
  const [host, setHost] = useState(hosts[0]?.id || 'openai')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)

  const selectedHost = hosts.find(h => h.id === host)
  const hints = selectedHost?.models_hint || []

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!model.trim() || !apiKey.trim()) {
      onMessage({ type: 'error', text: 'Model name and API key are required' })
      return
    }

    setSaving(true)
    try {
      const created = await apiPost('/llm-models', {
        host,
        model: model.trim(),
        api_key: apiKey.trim(),
      })

      // Run health check on the newly created model
      onMessage({ type: 'info', text: `Added ${created.display_name}. Running health check...` })
      try {
        const check = await apiPost(`/llm-models/${created.id}/health-check`)
        if (check.ok) {
          onMessage({ type: 'success', text: `Added ${created.display_name} — health check passed` })
        } else {
          onMessage({ type: 'error', text: `Added ${created.display_name} — health check failed: ${check.error || 'Unknown error'}` })
        }
      } catch {
        onMessage({ type: 'success', text: `Added ${created.display_name} (health check skipped)` })
      }

      onSuccess()
    } catch (err) {
      onMessage({ type: 'error', text: err.message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mx-5 mt-3 p-4 bg-gray-900 rounded-lg border border-gray-600 space-y-3">
      <div>
        <label className="text-gray-400 text-xs block mb-1">Host</label>
        <select
          value={host}
          onChange={e => { setHost(e.target.value); setModel('') }}
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
        >
          {hosts.map(h => (
            <option key={h.id} value={h.id}>{h.name}</option>
          ))}
        </select>
        {selectedHost?.note && (
          <p className="text-gray-500 text-xs mt-1">{selectedHost.note}</p>
        )}
      </div>

      <div>
        <label className="text-gray-400 text-xs block mb-1">Model</label>
        <input
          type="text"
          value={model}
          onChange={e => setModel(e.target.value)}
          placeholder={hints[0] || 'Enter model identifier'}
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:border-blue-500 focus:outline-none"
        />
        {hints.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {hints.map(h => (
              <button
                key={h}
                type="button"
                onClick={() => setModel(h)}
                className="text-xs px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
              >
                {h}
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        <label className="text-gray-400 text-xs block mb-1">API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder="Enter API key"
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:border-blue-500 focus:outline-none"
        />
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={saving || !model.trim() || !apiKey.trim()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white text-sm rounded font-medium transition-colors"
        >
          {saving ? 'Adding...' : 'Add & Test'}
        </button>
      </div>
    </form>
  )
}
