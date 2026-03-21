/**
 * CSV/JSON data export utilities.
 *
 * Usage:
 *   exportCSV(data, 'filename.csv')
 *   exportJSON(data, 'filename.json')
 */

/**
 * Export an array of objects as a CSV file download.
 * Columns are derived from the keys of the first object.
 */
export function exportCSV(data, filename = 'export.csv', columns = null) {
  if (!data || data.length === 0) return

  const cols = columns || Object.keys(data[0])
  const header = cols.join(',')
  const rows = data.map(row =>
    cols.map(col => {
      const val = row[col]
      if (val == null) return ''
      const str = String(val)
      // Quote if contains comma, quote, or newline
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`
      }
      return str
    }).join(',')
  )

  const csv = [header, ...rows].join('\n')
  downloadBlob(csv, filename, 'text/csv;charset=utf-8;')
}

/**
 * Export data as a JSON file download.
 */
export function exportJSON(data, filename = 'export.json') {
  const json = JSON.stringify(data, null, 2)
  downloadBlob(json, filename, 'application/json')
}

function downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Reusable export button component helper.
 * Returns a click handler that exports the provided data.
 */
export function makeExportHandler(getData, filename, format = 'csv') {
  return () => {
    const data = typeof getData === 'function' ? getData() : getData
    if (!data || data.length === 0) return
    if (format === 'json') {
      exportJSON(data, filename)
    } else {
      exportCSV(data, filename)
    }
  }
}
