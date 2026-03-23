import { Link } from 'react-router-dom'

export default function TradingScreeners() {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-gray-300">Saved Screeners</h2>

      <div className="bg-gray-800 rounded-lg border border-gray-700 p-8 text-center">
        <p className="text-gray-400 mb-4">No saved screeners yet.</p>
        <p className="text-gray-500 text-sm mb-4">
          Use the Screener to filter assets, then save your filter settings here for quick access and live alerts.
        </p>
        <Link
          to="/screener"
          className="inline-block px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded font-medium transition-colors"
        >
          Go to Screener
        </Link>
      </div>
    </div>
  )
}
