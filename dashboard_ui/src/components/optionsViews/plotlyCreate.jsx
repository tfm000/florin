/**
 * Minimal Plotly React wrapper — vendored locally so we don't depend
 * on ``react-plotly.js``.
 *
 * Why vendor: ``react-plotly.js`` (both the main entry and the factory
 * sub-entry) is Babel-compiled CJS that uses
 * ``Object.defineProperty(exports, "__esModule", {value: true}); exports["default"] = X``.
 * Rolldown 1.x (Vite 8's bundler) does not interop that shape
 * reliably — depending on the entry chosen, the default export either
 * comes back as ``undefined`` (causing ``r.default is not a function``)
 * or as an object without ``.default`` resolving to the component
 * class (causing React error #306: "Lazy element type must resolve
 * to a class or function").
 *
 * Reproducing react-plotly.js's API surface in ~40 lines of code
 * sidesteps the bundler bug entirely. We support the prop subset our
 * view components use: ``data``, ``layout``, ``config``, ``style``,
 * ``useResizeHandler``. (No ``onInitialized`` / ``onUpdate`` hooks,
 * which the views don't currently consume.)
 *
 * This file is only imported via the ``React.lazy`` wrapper in
 * ``plotlyLazy.js``, so Vite still splits Plotly into a dedicated
 * chunk that loads on first Options-page mount.
 */
import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist-min'

export default function Plot({
  data,
  layout,
  config,
  style,
  useResizeHandler = false,
}) {
  const ref = useRef(null)

  // Mount Plotly once; tear it down on unmount.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    Plotly.newPlot(el, data, layout, config)

    let onResize
    if (useResizeHandler) {
      onResize = () => Plotly.Plots.resize(el)
      window.addEventListener('resize', onResize)
    }

    return () => {
      if (onResize) window.removeEventListener('resize', onResize)
      Plotly.purge(el)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Re-render on prop change. Plotly.react diffs internally so this is
  // cheap on identical-data renders.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    Plotly.react(el, data, layout, config)
  }, [data, layout, config])

  return <div ref={ref} style={style} />
}
