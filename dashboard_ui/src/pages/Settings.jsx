import { useState, useEffect } from 'react'
import { useApi, apiPut } from '../hooks/useApi'

export default function Settings() {
  const { data, loading, refetch } = useApi('/settings')
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  // Reset edits when data loads
  useEffect(() => {
    setEdits({})
  }, [data])

  if (loading) return <p className="text-gray-500">Loading settings...</p>

  const sections = data?.sections || []

  const handleChange = (key, value) => {
    setEdits(prev => ({ ...prev, [key]: value }))
  }

  const hasChanges = Object.keys(edits).length > 0

  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const settings = Object.entries(edits).map(([key, value]) => ({
        key,
        value: String(value),
      }))
      const result = await apiPut('/settings', { settings })
      setEdits({})
      setMessage(
        result.restart_required
          ? `Saved ${result.updated.length} setting(s). Some changes require a restart to take effect.`
          : `Saved ${result.updated.length} setting(s).`
      )
      refetch()
    } catch (err) {
      setMessage(`Error: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        {hasChanges && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white text-sm rounded font-medium transition-colors"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        )}
      </div>

      {message && (
        <div className={`px-4 py-3 rounded text-sm ${
          message.startsWith('Error') ? 'bg-red-900/50 text-red-300 border border-red-700' : 'bg-green-900/50 text-green-300 border border-green-700'
        }`}>
          {message}
        </div>
      )}

      {sections.map(section => (
        <SettingsSection
          key={section.id}
          section={section}
          edits={edits}
          onChange={handleChange}
        />
      ))}

      {hasChanges && (
        <div className="sticky bottom-4">
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white rounded font-medium transition-colors"
          >
            {saving ? 'Saving...' : `Save ${Object.keys(edits).length} Change(s)`}
          </button>
        </div>
      )}
    </div>
  )
}

function SettingsSection({ section, edits, onChange }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-750 transition-colors"
      >
        <h2 className="text-lg font-bold text-gray-200">{section.label}</h2>
        <span className="text-gray-500 text-sm">{collapsed ? '▶' : '▼'}</span>
      </button>

      {!collapsed && (
        <div className="px-5 pb-5 space-y-3">
          {section.fields.map(field => (
            <SettingField
              key={field.key}
              field={field}
              editValue={edits[field.key]}
              onChange={onChange}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SettingField({ field, editValue, onChange }) {
  const { key, value, is_secret, is_set, type, choices } = field
  const displayValue = editValue !== undefined ? editValue : value

  const label = key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/Llm/g, 'LLM')
    .replace(/Api/g, 'API')
    .replace(/T212/g, 'T212')
    .replace(/Url/g, 'URL')
    .replace(/Pct/g, '%')

  const inputClasses = 'w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:border-blue-500 focus:outline-none'

  let input
  if (choices) {
    input = (
      <select
        value={displayValue}
        onChange={e => onChange(key, e.target.value)}
        className={inputClasses}
      >
        {choices.map(c => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    )
  } else if (is_secret) {
    input = (
      <input
        type="password"
        value={editValue !== undefined ? editValue : ''}
        placeholder={is_set ? '••••••• (set, enter to change)' : 'Not configured'}
        onChange={e => onChange(key, e.target.value)}
        className={inputClasses}
      />
    )
  } else if (type === 'textarea') {
    input = (
      <textarea
        value={displayValue}
        onChange={e => onChange(key, e.target.value)}
        className={inputClasses + ' min-h-[80px] resize-y'}
        rows={3}
        placeholder="Enter guidance for LLM analysis..."
      />
    )
  } else if (type === 'number') {
    input = (
      <input
        type="number"
        value={displayValue}
        onChange={e => onChange(key, e.target.value)}
        className={inputClasses}
        step={key.includes('threshold') || key.includes('pct') || key.includes('size') ? '0.1' : '1'}
      />
    )
  } else {
    input = (
      <input
        type="text"
        value={displayValue}
        onChange={e => onChange(key, e.target.value)}
        className={inputClasses}
      />
    )
  }

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
      <label className="text-gray-400 text-sm w-48 shrink-0">{label}</label>
      <div className="flex-1 flex items-center gap-2">
        {input}
        {is_secret && is_set && (
          <span className="text-green-500 text-xs shrink-0" title="Configured">✓</span>
        )}
        {is_secret && !is_set && (
          <span className="text-yellow-500 text-xs shrink-0" title="Not configured">!</span>
        )}
      </div>
    </div>
  )
}
