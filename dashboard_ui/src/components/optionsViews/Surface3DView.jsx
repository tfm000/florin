import { Suspense, useMemo } from 'react'
import Plot from './plotlyLazy'

/**
 * Interactive 3-D surface (IV or RND vs (moneyness, T)). Drag-to-rotate
 * comes built-in with Plotly's Surface trace.
 *
 * X axis: percent moneyness ``(K/F − 1) × 100``, cropped to the
 * ``xRange`` window passed by the parent.
 *
 * @param {object} data  MultiSurfaceFitResponse payload.
 * @param {'iv'|'rnd'} variable
 * @param {[number, number] | null} xRange  percent-moneyness crop.
 */
export default function Surface3DView({ data, variable = 'iv', xRange }) {
  const { x, y, z, zLabel } = useMemo(() => {
    if (!data) return { x: [], y: [], z: [], zLabel: '' }
    const isIv = variable === 'iv'
    const surface = isIv ? data.iv_surface : data.rnd_surface
    const z = (surface || []).map(row => row.map(v => (isIv ? v * 100 : v))) // IV → %
    return {
      x: (data.moneyness_grid || []).map(m => (m - 1) * 100),
      y: data.T_values || [],
      z,
      zLabel: isIv ? 'Implied vol (%)' : 'Risk-neutral density q(K)',
    }
  }, [data, variable])

  const trace = useMemo(
    () => ({
      type: 'surface',
      x,
      y,
      z,
      colorscale: 'Viridis',
      contours: {
        z: { show: false },
      },
      hovertemplate:
        'moneyness=%{x:.2f}%<br>T=%{y:.3f} yrs<br>' +
        (variable === 'iv' ? 'σ=%{z:.2f}%' : 'q=%{z:.5f}') +
        '<extra></extra>',
    }),
    [x, y, z, variable]
  )

  const layout = useMemo(
    () => ({
      paper_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#9CA3AF', size: 11 },
      margin: { l: 0, r: 0, t: 10, b: 0 },
      scene: {
        xaxis: {
          title: 'Moneyness (K/F − 1) %',
          gridcolor: '#374151',
          backgroundcolor: 'rgba(0,0,0,0)',
          range: xRange ?? undefined,
        },
        yaxis: {
          title: 'T (yrs)',
          gridcolor: '#374151',
          backgroundcolor: 'rgba(0,0,0,0)',
        },
        zaxis: {
          title: zLabel,
          gridcolor: '#374151',
          backgroundcolor: 'rgba(0,0,0,0)',
        },
        camera: { eye: { x: 1.8, y: -1.5, z: 0.9 } },
      },
    }),
    [zLabel, xRange]
  )

  if (!data || !data.iv_surface) {
    return (
      <p className="text-gray-500 text-sm text-center py-8">
        Multi-expiry data unavailable.
      </p>
    )
  }
  return (
    <Suspense fallback={<div className="h-96 flex items-center justify-center text-gray-500">Loading 3-D chart…</div>}>
      <Plot
        data={[trace]}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: 480 }}
        useResizeHandler
      />
    </Suspense>
  )
}
