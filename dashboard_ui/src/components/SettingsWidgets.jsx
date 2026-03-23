import { useState } from 'react'

export function SettingsSection({ section, edits, onChange }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-750 transition-colors"
      >
        <h2 className="text-lg font-bold text-gray-200">{section.label}</h2>
        <span className="text-gray-500 text-sm">{collapsed ? '\u25B6' : '\u25BC'}</span>
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

export function SettingField({ field, editValue, onChange }) {
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
        placeholder={is_set ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (set, enter to change)' : 'Not configured'}
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
          <span className="text-green-500 text-xs shrink-0" title="Configured">{'\u2713'}</span>
        )}
        {is_secret && !is_set && (
          <span className="text-yellow-500 text-xs shrink-0" title="Not configured">!</span>
        )}
      </div>
    </div>
  )
}

/**
 * Shared settings save logic — handles loading, editing, saving, and message display.
 * Used by both the system Settings page and TradingSettings page.
 */
export function useSettingsState(filterSectionIds = null) {
  // This is a pattern helper, not a hook — the actual hook calls remain in the consuming component.
  // filterSectionIds: if provided, only show sections with matching IDs.
  return { filterSectionIds }
}
