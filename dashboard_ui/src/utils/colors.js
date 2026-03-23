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
