/**
 * ChartFrame — loading/error/stale/empty wrapper for all chart components.
 *
 * Closes PRIM-04 / CONTEXT D-04 / D-11.
 *
 * Consolidates the scattered inline loading and empty-state guards that previously
 * appeared in every chart component (e.g., CumulativeReturnChart.jsx:252, 475-477).
 * Also introduces a unified error/stale banner that surfaces the `stale` flag from
 * the Phase 1 useApi 4-tuple ({ data, loading, error, stale }) so chart consumers
 * never have to reinvent the error-banner UX.
 *
 * Render priority (D-04):
 *   1. loading → loading skeleton with animate-pulse
 *   2. error || stale → amber error banner
 *   3. empty → empty message paragraph
 *   4. (default) → children
 *
 * XSS note (T-02-02-01): The `error` string is rendered via React's JSX interpolation
 * `{error}` — React escapes the value by default. No unsafe HTML rendering is used.
 *
 * @module ChartFrame
 */

/**
 * Chart wrapper component that handles loading, error, stale, and empty states.
 *
 * @param {{ loading: boolean, empty: boolean, error: string|null,
 *           stale: boolean, emptyMessage: string, children: React.ReactNode }} props
 * @param {boolean} [props.loading=false] - When true, renders a pulsing loading skeleton
 *   and hides children.
 * @param {boolean} [props.empty=false] - When true (and no loading/error/stale), renders
 *   the emptyMessage text and hides children.
 * @param {string|null} [props.error=null] - Error string from useApi's 4-tuple. When
 *   non-null, the error banner is shown regardless of the `stale` flag.
 * @param {boolean} [props.stale=false] - When true, renders an error banner with the
 *   error string (or a generic stale message if no error string is set). Maps to the
 *   `stale` field of Phase 1's useApi 4-tuple.
 * @param {string} [props.emptyMessage="No data"] - Text shown when empty=true.
 * @param {React.ReactNode} [props.children] - Chart content rendered when no flags are set.
 * @returns {React.ReactElement} Outer dark-card div wrapping the appropriate state content.
 */
export function ChartFrame({
  loading = false,
  empty = false,
  error = null,
  stale = false,
  emptyMessage = 'No data',
  children,
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      {loading ? (
        // Priority 1: Loading skeleton — animate-pulse provides a stable CSS selector
        // for tests and a subtle shimmer for users.
        <p className="text-gray-500 text-sm py-8 text-center animate-pulse">Loading...</p>
      ) : error || stale ? (
        // Priority 2: Error or stale banner — amber accent signals degraded data.
        // Falls back to a generic message when stale=true but no error string is set.
        <div className="bg-amber-900/20 border border-amber-700/40 rounded text-amber-300 text-sm py-3 px-4 text-center">
          {error || 'Data may be stale'}
        </div>
      ) : empty ? (
        // Priority 3: Empty state — shown when data loaded but produced no rows.
        <p className="text-gray-500 text-sm py-8 text-center">{emptyMessage}</p>
      ) : (
        // Priority 4 (default): Render chart children.
        children
      )}
    </div>
  )
}
