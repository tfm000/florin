import { Suspense, useMemo } from 'react'
import Plot from './plotlyLazy'

/**
 * 2-D overlay of IV or RND across expiries, one line per expiry on a
 * shared percent-moneyness axis. Lines coloured by T (viridis-like
 * ordering).
 *
 * X axis: ``(K/F − 1) × 100`` — the multi-expiry payload's
 * ``moneyness_grid`` ships as K/F ratios in [_MONEYNESS_LO,
 * _MONEYNESS_HI] (≈ [0.6, 1.4]); we render ``(m − 1) × 100`` and
 * crop to the ``xRange`` passed by the parent.
 *
 * @param {object} data  MultiSurfaceFitResponse payload.
 * @param {'iv'|'rnd'} variable
 * @param {[number, number] | null} xRange  percent-moneyness crop.
 */
export default function Overlay2DView({ data, variable = 'iv', xRange }) {
  const traces = useMemo(() => {
    if (!data || !data.iv_surface) return []
    const isIv = variable === 'iv'
    const surface = isIv ? data.iv_surface : data.rnd_surface
    const moneynessPct = (data.moneyness_grid || []).map(m => (m - 1) * 100)
    const nT = data.expiries.length

    return surface.map((row, i) => {
      const t = (i + 1) / (nT + 1) // 0..1 for viridis-like ramp
      const h = Math.round(280 - 280 * t) // hue from violet → green-yellow
      const s = 70
      const l = 55
      const color = `hsl(${h},${s}%,${l}%)`
      return {
        x: moneynessPct,
        y: row.map(v => (isIv ? v * 100 : v)),
        type: 'scatter',
        mode: 'lines',
        line: { color, width: 2 },
        name: data.expiries[i],
        hovertemplate:
          `${data.expiries[i]} (T=${data.T_values[i].toFixed(2)} y)<br>` +
          'mny=%{x:.2f}%<br>' +
          (isIv ? 'σ=%{y:.2f}%' : 'q=%{y:.5f}') +
          '<extra></extra>',
      }
    })
  }, [data, variable])

  const layout = useMemo(
    () => ({
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#9CA3AF', size: 11 },
      margin: { l: 50, r: 20, t: 10, b: 40 },
      xaxis: {
        title: { text: 'Moneyness (K/F − 1)', font: { size: 11 } },
        gridcolor: '#374151',
        ticksuffix: '%',
        range: xRange ?? undefined,
      },
      yaxis: {
        title: { text: variable === 'iv' ? 'IV (%)' : 'q(K)', font: { size: 11 } },
        gridcolor: '#374151',
        ticksuffix: variable === 'iv' ? '%' : '',
      },
      legend: {
        orientation: 'v',
        x: 1.02,
        xanchor: 'left',
        y: 1,
        yanchor: 'top',
        font: { size: 10 },
      },
    }),
    [variable, xRange]
  )

  if (!data) {
    return (
      <p className="text-gray-500 text-sm text-center py-8">
        Multi-expiry data unavailable.
      </p>
    )
  }
  return (
    <Suspense fallback={<div className="h-80 flex items-center justify-center text-gray-500">Loading chart…</div>}>
      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: 400 }}
        useResizeHandler
      />
    </Suspense>
  )
}
