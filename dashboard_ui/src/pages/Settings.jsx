import { useApi } from '../hooks/useApi'

export default function Settings() {
  const { data: scannerSettings, loading } = useApi('/universe/settings')

  if (loading) return <p className="text-gray-500">Loading settings...</p>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      {/* Scanner Settings (read-only for now — configured via .env) */}
      <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
        <h2 className="text-lg font-bold text-gray-300 mb-4">Scanner Configuration</h2>
        <p className="text-gray-500 text-xs mb-4">
          These settings are loaded from .env. Restart the application to apply changes.
        </p>
        {scannerSettings && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <SettingRow label="Price Threshold" value={`$${scannerSettings.price_threshold}`} />
            <SettingRow label="Momentum Threshold" value={`${scannerSettings.momentum_threshold}%`} />
            <SettingRow label="Scan Interval" value={`${scannerSettings.scan_interval_seconds}s`} />
            <SettingRow label="Cooldown" value={`${scannerSettings.cooldown_minutes} min`} />
            <SettingRow label="Min Volume" value={scannerSettings.min_volume.toLocaleString()} />
          </div>
        )}
      </div>
    </div>
  )
}

function SettingRow({ label, value }) {
  return (
    <div className="flex justify-between items-center bg-gray-900 rounded px-3 py-2">
      <span className="text-gray-400 text-sm">{label}</span>
      <span className="text-white font-mono text-sm">{value}</span>
    </div>
  )
}
