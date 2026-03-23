import { useState, useEffect } from 'react'
import { useApi, apiPut } from '../hooks/useApi'
import { SettingsSection } from '../components/SettingsWidgets'

// Only show these section IDs on the Trading settings page
const TRADING_SECTION_IDS = new Set(['trading', 'broker', 'telegram'])

export default function TradingSettings() {
  const { data, loading, refetch } = useApi('/settings')
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    setEdits({})
  }, [data])

  if (loading) return <p className="text-gray-500">Loading settings...</p>

  const sections = (data?.sections || []).filter(s => TRADING_SECTION_IDS.has(s.id))

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
        <h2 className="text-lg font-semibold text-gray-300">Trading Settings</h2>
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
