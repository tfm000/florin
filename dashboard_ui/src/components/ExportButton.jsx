import { exportCSV, exportJSON } from '../utils/export'

/**
 * Reusable export button. Place next to any data table or chart.
 *
 * Props:
 *   data: array of objects to export (or a function that returns it)
 *   filename: base filename (without extension)
 *   label: button text (default "Export")
 *   columns: optional column whitelist
 */
export default function ExportButton({ data, filename = 'export', label = 'Export', columns }) {
  const handleExport = (format) => {
    const rows = typeof data === 'function' ? data() : data
    if (!rows || rows.length === 0) return
    if (format === 'json') {
      exportJSON(rows, `${filename}.json`)
    } else {
      exportCSV(rows, `${filename}.csv`, columns)
    }
  }

  return (
    <div className="inline-flex rounded overflow-hidden">
      <button
        onClick={() => handleExport('csv')}
        className="px-2 py-1 text-xs bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white"
      >
        {label} CSV
      </button>
      <button
        onClick={() => handleExport('json')}
        className="px-2 py-1 text-xs bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white border-l border-gray-600"
      >
        JSON
      </button>
    </div>
  )
}
