/**
 * Control surface for the Options chart: view / tenor / model toggles +
 * ticker entry and expiry selector. Pure presentational component — all
 * state lives in the parent reducer.
 */

const VIEWS = [
  { key: 'rnd', label: 'RND' },
  { key: 'iv', label: 'IV Curve' },
  { key: 'spread', label: 'Spread' },
]

const TENORS = [
  { key: 'single', label: 'Single' },
  { key: 'overlay', label: 'Overlay 2D' },
  { key: 'surface3d', label: 'Surface 3D' },
]

const SPREAD_CHART_TYPES = [
  { key: 'bar', label: 'Bars' },
  { key: 'line', label: 'Line' },
]

function ToggleGroup({ options, selected, onChange, label }) {
  return (
    <div className="flex items-center gap-1">
      {label && <span className="text-xs text-gray-400 mr-1">{label}</span>}
      {options.map(o => (
        <button
          key={o.key}
          onClick={() => onChange(o.key)}
          className={`px-2 py-1 text-xs rounded transition-colors ${
            selected === o.key
              ? 'bg-indigo-600 text-white'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export default function ChartControls({
  state,
  dispatch,
  expiries = [],
  onTickerSubmit,
  inputTicker,
  onInputChange,
}) {
  const tenorVisible = state.view === 'rnd' || state.view === 'iv'
  const spreadToggleVisible = state.view === 'spread'

  return (
    <div className="flex flex-col gap-2">
      {/* Row 1: ticker, expiry, model, GP band */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <form
          onSubmit={e => {
            e.preventDefault()
            onTickerSubmit()
          }}
          className="flex gap-1"
        >
          <input
            type="text"
            value={inputTicker}
            onChange={e => onInputChange(e.target.value.toUpperCase())}
            className="w-20 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-center font-mono"
          />
          <button
            type="submit"
            className="px-2 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-500"
          >
            Go
          </button>
        </form>

        {expiries.length > 0 && tenorVisible && state.tenor === 'single' && (
          <label className="text-gray-400">
            Expiry:
            <select
              value={state.expiry || ''}
              onChange={e =>
                dispatch({ type: 'set', payload: { expiry: e.target.value || null } })
              }
              className="ml-1 bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-white"
            >
              <option value="">Auto</option>
              {expiries.map(e => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
        )}

        <ToggleGroup
          label="Model:"
          options={[
            { key: 'ssvi', label: 'SSVI' },
            { key: 'sabr', label: 'SABR' },
          ]}
          selected={state.model}
          onChange={m => dispatch({ type: 'set', payload: { model: m } })}
        />

        <label className="flex items-center gap-1 text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={state.gp_band}
            onChange={e =>
              dispatch({ type: 'set', payload: { gp_band: e.target.checked } })
            }
          />
          GP band
        </label>
      </div>

      {/* Row 2: view */}
      <div className="flex items-center gap-3">
        <ToggleGroup
          label="View:"
          options={VIEWS}
          selected={state.view}
          onChange={v => dispatch({ type: 'set', payload: { view: v } })}
        />
      </div>

      {/* Row 3: tenor (RND / IV only) or spread-chart-type (Spread only) */}
      {tenorVisible && (
        <div className="flex items-center gap-3">
          <ToggleGroup
            label="Tenor:"
            options={TENORS}
            selected={state.tenor}
            onChange={t => dispatch({ type: 'set', payload: { tenor: t } })}
          />
        </div>
      )}
      {spreadToggleVisible && (
        <div className="flex items-center gap-3">
          <ToggleGroup
            label="Chart:"
            options={SPREAD_CHART_TYPES}
            selected={state.spread_chart}
            onChange={c => dispatch({ type: 'set', payload: { spread_chart: c } })}
          />
        </div>
      )}
    </div>
  )
}
