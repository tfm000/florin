/**
 * Shared color utilities for data visualization.
 *
 * All semantic coloring should use these helpers (or the useChartColors hook
 * directly) to ensure consistent color scheme and colorblind support.
 */

/**
 * Map a correlation coefficient (-1 to +1) to a background color.
 * Blue for positive, red for negative, transparent for zero or null.
 */
export function corrColor(val) {
  if (val == null) return 'transparent'
  const abs = Math.min(Math.abs(val), 1)
  if (val > 0) return `rgba(59, 130, 246, ${abs * 0.8})`
  if (val < 0) return `rgba(239, 68, 68, ${abs * 0.8})`
  return 'transparent'
}

/**
 * Return the semantic color for a numeric value.
 *
 * Positive → colors.positive (green / blue in colorblind mode)
 * Negative → colors.negative (red / orange in colorblind mode)
 * Zero/null → colors.neutral (gray)
 *
 * @param {number|null} value — the numeric value to color
 * @param {object} colors — palette from useChartColors()
 * @returns {string} hex color string
 */
export function valueColor(value, colors) {
  if (value == null || value === 0) return colors.neutral
  return value > 0 ? colors.positive : colors.negative
}

/**
 * Return the semantic color for a risk level.
 *
 * low → colors.positive (green / blue)
 * medium → colors.warning (yellow / amber)
 * high → colors.negative (red / orange)
 *
 * @param {'low'|'medium'|'high'} level
 * @param {object} colors — palette from useChartColors()
 * @returns {string} hex color string
 */
export function riskColor(level, colors) {
  if (level === 'low') return colors.positive
  if (level === 'medium') return colors.warning
  return colors.negative
}
