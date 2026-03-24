import { useState, useEffect } from 'react'
import { useApi, apiPut } from '../hooks/useApi'

/**
 * LLM Analysis Configuration — mode toggle and model assignment dropdowns.
 *
 * Allows users to:
 * - Select single vs consensus mode
 * - Assign specific registered models to announcement/sentiment analysis
 * - In consensus mode, assign a leader model
 * - Set optional user context included in all prompts
 */
export default function LLMAnalysisConfig() {
  const { data: settings, loading: loadingSettings, refetch } = useApi('/llm-settings')
  const { data: models, loading: loadingModels } = useApi('/llm-models')
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  // Reset edits when data loads
  useEffect(() => {
    setEdits({})
  }, [settings])

  if (loadingSettings || loadingModels) {
    return <p className="text-gray-500 text-sm">Loading analysis configuration...</p>
  }

  if (!settings) return null

  const enabledModels = (models || []).filter(m => m.enabled)
  const currentMode = edits.mode ?? settings.mode
  const hasChanges = Object.keys(edits).length > 0

  const handleChange = (key, value) => {
    setEdits(prev => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const result = await apiPut('/llm-settings', edits)
      setEdits({})
      setMessage({ type: 'success', text: `Updated ${result.updated.length} setting(s).` })
      refetch()
    } catch (err) {
      setMessage({ type: 'error', text: err.message })
    } finally {
      setSaving(false)
    }
  }

  const modelOptions = enabledModels.map(m => ({ value: m.id, label: m.display_name }))
  // Add "None" option for optional fields
  const optionalModelOptions = [{ value: '', label: '(None)' }, ...modelOptions]

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-700 flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-200">Analysis Configuration</h2>
        {hasChanges && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white text-sm rounded font-medium transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        )}
      </div>

      {message && (
        <div className={`mx-5 mt-3 px-3 py-2 rounded text-sm ${
          message.type === 'error'
            ? 'bg-red-900/50 text-red-300 border border-red-700'
            : 'bg-green-900/50 text-green-300 border border-green-700'
        }`}>
          {message.text}
        </div>
      )}

      <div className="p-5 space-y-4">
        {/* Mode toggle */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
          <label className="text-gray-400 text-sm w-48 shrink-0">Analysis Mode</label>
          <select
            value={currentMode}
            onChange={e => handleChange('mode', e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="single">Single Model</option>
            <option value="consensus">Consensus (Multi-Model)</option>
          </select>
        </div>

        {currentMode === 'single' && (
          <>
            <p className="text-gray-500 text-xs">
              In single mode, one model handles each analysis type.
            </p>

            {/* Announcement model */}
            <ModelSelector
              label="Announcement Model"
              description="Analyses Form 8-K filings"
              value={edits.announcement_model_id ?? settings.announcement_model_id}
              options={optionalModelOptions}
              onChange={v => handleChange('announcement_model_id', v)}
            />

            {/* Sentiment model */}
            <ModelSelector
              label="Sentiment Model"
              description="Analyses social media, news, and web data"
              value={edits.sentiment_model_id ?? settings.sentiment_model_id}
              options={optionalModelOptions}
              onChange={v => handleChange('sentiment_model_id', v)}
            />
          </>
        )}

        {currentMode === 'consensus' && (
          <>
            <p className="text-gray-500 text-xs">
              In consensus mode, all enabled models run the same analysis, then a leader model synthesises the results.
            </p>

            {/* Leader model */}
            <ModelSelector
              label="Consensus Leader"
              description="Synthesises individual analyst reports into a consensus view"
              value={edits.consensus_leader_model_id ?? settings.consensus_leader_model_id}
              options={optionalModelOptions}
              onChange={v => handleChange('consensus_leader_model_id', v)}
            />

            <div className="text-gray-500 text-xs bg-gray-900/50 rounded p-3 border border-gray-700">
              <strong className="text-gray-300">Participating models:</strong>{' '}
              {enabledModels.length === 0
                ? 'No enabled models'
                : enabledModels.map(m => m.display_name).join(', ')
              }
            </div>
          </>
        )}

        {/* User context */}
        <div className="pt-2 border-t border-gray-700">
          <label className="text-gray-400 text-sm block mb-1">User Context</label>
          <p className="text-gray-500 text-xs mb-2">
            Optional notes included in all LLM prompts (e.g. "Focus on biotech catalysts").
          </p>
          <textarea
            value={edits.user_context ?? settings.user_context ?? ''}
            onChange={e => handleChange('user_context', e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:border-blue-500 focus:outline-none min-h-[80px] resize-y"
            rows={3}
            placeholder="Enter guidance for LLM analysis..."
          />
        </div>

        {/* Save button (bottom) */}
        {hasChanges && (
          <div className="pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white text-sm rounded font-medium transition-colors"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}


function ModelSelector({ label, description, value, options, onChange }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
      <div className="w-48 shrink-0">
        <label className="text-gray-400 text-sm">{label}</label>
        {description && <p className="text-gray-600 text-xs">{description}</p>}
      </div>
      <select
        value={value || ''}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}
