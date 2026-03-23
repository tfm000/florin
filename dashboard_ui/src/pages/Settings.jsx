import { useState, useEffect } from 'react'
import { useApi, apiPut } from '../hooks/useApi'
import { useColorblindToggle } from '../hooks/useChartColors'
import { SettingsSection } from '../components/SettingsWidgets'

// System settings — exclude trading/broker/telegram (in TradingSettings) and scanner (removed)
const EXCLUDED_SECTION_IDS = new Set(['trading', 'broker', 'telegram', 'scanner'])

export default function Settings() {
  const { data, loading, refetch } = useApi('/settings')
  const [colorblind, setColorblind] = useColorblindToggle()
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null) // { type: 'success' | 'error', text }

  // Reset edits when data loads
  useEffect(() => {
    setEdits({})
  }, [data])

  if (loading) return <p className="text-gray-500">Loading settings...</p>

  const sections = (data?.sections || []).filter(s => !EXCLUDED_SECTION_IDS.has(s.id))

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
      const text = result.restart_required
        ? `Saved ${result.updated.length} setting(s). Some changes require a restart to take effect.`
        : `Saved ${result.updated.length} setting(s).`
      setMessage({ type: 'success', text })
      refetch()
    } catch (err) {
      setMessage({ type: 'error', text: err.message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">System Settings</h1>
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
          message.type === 'error' ? 'bg-red-900/50 text-red-300 border border-red-700' : 'bg-green-900/50 text-green-300 border border-green-700'
        }`}>
          {message.text}
        </div>
      )}

      {/* Display Preferences (client-side) */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
        <div className="px-4 py-3 bg-gray-750 border-b border-gray-700">
          <h2 className="text-white font-semibold">Display</h2>
        </div>
        <div className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white text-sm">Colorblind-friendly charts</p>
              <p className="text-gray-500 text-xs">Replaces red/green with blue/orange for deuteranopia/protanopia</p>
            </div>
            <button
              onClick={() => setColorblind(!colorblind)}
              className={`relative w-11 h-6 rounded-full transition-colors ${
                colorblind ? 'bg-indigo-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                  colorblind ? 'translate-x-5' : ''
                }`}
              />
            </button>
          </div>
          {colorblind && (
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span>Active palette:</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#2563EB' }} /> Blue (positive)</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#EF4444' }} /> Red (negative)</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#14B8A6' }} /> Teal</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#F59E0B' }} /> Amber</span>
            </div>
          )}
        </div>
      </div>

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
