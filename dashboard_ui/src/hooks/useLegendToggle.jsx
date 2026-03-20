import { useState, useCallback } from 'react'

/**
 * Hook for toggling line/bar visibility via Recharts legend clicks.
 *
 * Usage:
 *   const { hidden, handleLegendClick, isHidden, legendProps } = useLegendToggle()
 *
 *   <Legend onClick={handleLegendClick} {...legendProps} />
 *   <Line dataKey="foo" hide={isHidden('foo')} />
 */
export function useLegendToggle() {
  const [hidden, setHidden] = useState(new Set())

  const handleLegendClick = useCallback((entry) => {
    const key = entry.dataKey || entry.value
    setHidden(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  const isHidden = useCallback((key) => hidden.has(key), [hidden])

  // Style hidden legend entries with strikethrough + dim opacity
  const legendFormatter = useCallback((value, entry) => {
    const key = entry.dataKey || entry.value
    const dimmed = hidden.has(key)
    return (
      <span style={{
        textDecoration: dimmed ? 'line-through' : 'none',
        opacity: dimmed ? 0.4 : 1,
        cursor: 'pointer',
      }}>
        {value}
      </span>
    )
  }, [hidden])

  return { hidden, handleLegendClick, isHidden, legendFormatter }
}
