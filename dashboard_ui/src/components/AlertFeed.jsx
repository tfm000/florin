import { useState, useCallback } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

export default function AlertFeed() {
  const [alerts, setAlerts] = useState([])

  const handleMessage = useCallback((msg) => {
    if (msg.channel === 'alerts') {
      setAlerts(prev => [msg.data, ...prev].slice(0, 50))
    }
  }, [])

  const { connected } = useWebSocket(handleMessage)

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-white font-bold">Live Alerts</h3>
        <span className={`text-xs px-2 py-1 rounded ${connected ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'}`}>
          {connected ? 'LIVE' : 'DISCONNECTED'}
        </span>
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {alerts.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">Waiting for alerts...</p>
        )}
        {alerts.map((alert, i) => (
          <div key={i} className="bg-gray-900 rounded p-2 text-sm">
            <div className="flex justify-between">
              <span className="text-white font-mono">{alert.payload?.ticker || 'N/A'}</span>
              <span className="text-gray-400 text-xs">{alert.event_type}</span>
            </div>
            <p className="text-gray-400 text-xs mt-1">{alert.timestamp}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
