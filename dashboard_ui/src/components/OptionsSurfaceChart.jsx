import { useEffect, useMemo, useReducer, useState, lazy, Suspense } from 'react'
import {
  useOptionsSurface,
  useOptionsSurfaceMulti,
  useOptionsSpreadCurve,
} from '../hooks/useOptionsSurface'
import ChartControls from './optionsViews/ChartControls'
import SurfaceDiagnosticsPanel from './SurfaceDiagnosticsPanel'
import {
  cropRangeFromDensity,
  cropRangeFromMultiDensity,
} from './optionsViews/moneynessUtil'

// Heavy view modules — code-split via React.lazy so Plotly only loads
// when the Options page is actually visited.
const RNDView = lazy(() => import('./optionsViews/RNDView'))
const IVCurveView = lazy(() => import('./optionsViews/IVCurveView'))
const SpreadCurveView = lazy(() => import('./optionsViews/SpreadCurveView'))
const Overlay2DView = lazy(() => import('./optionsViews/Overlay2DView'))
const Surface3DView = lazy(() => import('./optionsViews/Surface3DView'))

const INITIAL_STATE = (initialTicker = 'SPY') => ({
  view: 'rnd',
  tenor: 'single',
  spread_chart: 'bar',
  model: 'ssvi',
  gp_band: true,
  ticker: initialTicker,
  expiry: null,
})

function reducer(state, action) {
  switch (action.type) {
    case 'set':
      return { ...state, ...action.payload }
    case 'reset':
      return INITIAL_STATE(action.ticker)
    default:
      return state
  }
}

/**
 * Top-level Options chart: handles view-state, fetches the right
 * endpoint(s) per view, and dispatches to a sub-view component for
 * rendering. Exposes the implied risk-free rate up to the parent via
 * the ``onSurfaceLoaded`` callback so GreeksTable can consume it.
 */
export default function OptionsSurfaceChart({
  initialTicker = 'SPY',
  onSurfaceLoaded = null,
}) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE(initialTicker))
  const [inputTicker, setInputTicker] = useState(initialTicker)

  // Single-expiry fit — required for RND/IV single, also drives diagnostics.
  const singleEnabled =
    (state.view === 'rnd' || state.view === 'iv') && state.tenor === 'single'
  const { data: surface, loading: surfaceLoading, error: surfaceError } = useOptionsSurface(
    state.ticker,
    state.expiry,
    {
      model: state.model,
      enabled: singleEnabled || state.view === 'rnd' || state.view === 'iv',
      // Single-expiry surface is also needed for the diagnostics panel
      // and to expose the option-implied r upward.
    }
  )

  // Multi-expiry surface — overlay 2D or surface 3D.
  const multiEnabled =
    (state.view === 'rnd' || state.view === 'iv') &&
    (state.tenor === 'overlay' || state.tenor === 'surface3d')
  const { data: multi, loading: multiLoading } = useOptionsSurfaceMulti(state.ticker, {
    model: state.model,
    enabled: multiEnabled,
  })

  // Spread curve is lightweight, only fetched on demand.
  const spreadEnabled = state.view === 'spread'
  const { data: spreadData, loading: spreadLoading } = useOptionsSpreadCurve(state.ticker, {
    enabled: spreadEnabled,
  })

  // Notify parent when a single-expiry fit arrives — used to wire the
  // option-implied r into GreeksTable.
  useEffect(() => {
    if (surface && onSurfaceLoaded) onSurfaceLoaded(surface)
  }, [surface, onSurfaceLoaded])

  const onTickerSubmit = () => {
    dispatch({ type: 'set', payload: { ticker: inputTicker, expiry: null } })
  }

  const expiries = surface?.available_expiries ?? multi?.expiries ?? []

  // Crop the percent-moneyness X-axis range to where the RND density
  // is meaningfully above zero. One window for single-expiry views
  // (derived from surface.rnd) and one for multi-expiry views
  // (per-K max across all expiries). When data is missing we fall
  // through to Plotly autorange.
  const xRangeSingle = useMemo(() => {
    if (!surface?.rnd?.length || !surface?.F) return null
    return cropRangeFromDensity(
      surface.rnd.map(p => p.strike),
      surface.rnd.map(p => p.density_median),
      surface.F,
    )
  }, [surface])

  const xRangeMulti = useMemo(() => {
    if (!multi?.moneyness_grid?.length || !multi?.rnd_surface?.length) return null
    return cropRangeFromMultiDensity(multi.moneyness_grid, multi.rnd_surface)
  }, [multi])

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
      <ChartControls
        state={state}
        dispatch={dispatch}
        expiries={expiries}
        inputTicker={inputTicker}
        onInputChange={setInputTicker}
        onTickerSubmit={onTickerSubmit}
      />

      {/* Off-hours stale-data banner. yfinance returns settlement
          chains with bid=ask=0 when the US market is closed; our
          serializer falls back to lastPrice as mid, so the GP
          credible bands and RND uncertainty are degraded. */}
      {surface?.is_stale && (
        <div className="rounded border border-amber-700/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-200">
          <span className="font-semibold">Stale chain.</span>{' '}
          {(surface.stale_fraction * 100).toFixed(0)}% of quotes have no live
          bid/ask — pipeline is using last-traded prices as mid. GP credible
          bands and RND uncertainty are degraded; re-fit during US market hours
          (14:30–21:00 UTC) for the live view.
        </div>
      )}

      {/* Status caption. ``r`` is always the externally-resolved SOFR
          (the pipeline no longer extracts a rate from the chain — sub-
          cent bid-ask noise amplifies into double-digit rate errors on
          short-DTE chains). The chain-implied value is still exposed as
          ``surface.parity.r_implied_raw`` for quants who want to see how
          far the chain drifts from the true rate. */}
      <div className="text-xs text-gray-400 flex items-center gap-3 flex-wrap">
        {surface && state.tenor === 'single' && (
          <span>
            {surface.expiry} · spot ${surface.spot} · F ${surface.F?.toFixed(2)} ·{' '}
            r {(surface.r * 100).toFixed(2)}% (SOFR)
          </span>
        )}
        {(surfaceLoading || multiLoading || spreadLoading) && (
          <span className="text-gray-500">Fitting…</span>
        )}
        {surfaceError && <span className="text-red-400">Error: {surfaceError}</span>}
      </div>

      {/* The chart */}
      <Suspense
        fallback={<div className="h-80 flex items-center justify-center text-gray-500">Loading chart…</div>}
      >
        {state.view === 'rnd' && state.tenor === 'single' && (
          <RNDView
            data={surface?.rnd}
            spot={surface?.spot}
            F={surface?.F}
            gpBand={state.gp_band}
            xRange={xRangeSingle}
          />
        )}
        {state.view === 'iv' && state.tenor === 'single' && (
          // IVCurveView intentionally ignores ``xRange`` and hard-fixes
          // ±15 % — the smile-curvature is the whole point of this
          // view and the RND-mass crop is typically too narrow.
          <IVCurveView
            data={surface?.iv_curve}
            spot={surface?.spot}
            F={surface?.F}
            gpBand={state.gp_band}
            xRange={xRangeSingle}
          />
        )}
        {(state.view === 'rnd' || state.view === 'iv') && state.tenor === 'overlay' && (
          <Overlay2DView data={multi} variable={state.view} xRange={xRangeMulti} />
        )}
        {(state.view === 'rnd' || state.view === 'iv') && state.tenor === 'surface3d' && (
          <Surface3DView data={multi} variable={state.view} xRange={xRangeMulti} />
        )}
        {state.view === 'spread' && (
          <SpreadCurveView data={spreadData?.spread_curve} mode={state.spread_chart} />
        )}
      </Suspense>

      {/* Diagnostics: only shown for single-expiry views (where the full
          fit is available). */}
      {state.tenor === 'single' && (state.view === 'rnd' || state.view === 'iv') && (
        <SurfaceDiagnosticsPanel surface={surface} />
      )}
    </div>
  )
}
