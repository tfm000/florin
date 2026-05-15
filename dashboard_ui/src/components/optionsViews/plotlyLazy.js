import { lazy } from 'react'

/**
 * Lazy-loaded Plotly component. Points at the vendored ``plotlyCreate``
 * wrapper (a ~40-line minimal React class around ``plotly.js-dist-min``)
 * rather than ``react-plotly.js`` directly — the third-party package's
 * Babel-compiled CJS exports cannot be interop'd by Rolldown 1.x and
 * produce React #306 at runtime. See ``plotlyCreate.js`` for the full
 * write-up.
 */
const Plot = lazy(() => import('./plotlyCreate'))

export default Plot
