import { describe, it, expect } from 'vitest'
import { safeDomain } from './safeDomain'

describe('safeDomain — PRIM-02 NaN handling', () => {
  it('returns [0, 1] for empty array', () => {
    const [lo, hi] = safeDomain([])
    expect(lo).toBe(0)
    expect(hi).toBe(1)
  })

  it('returns [0, 1] for array with no finite values', () => {
    const [lo, hi] = safeDomain([NaN, NaN, null, undefined])
    expect(lo).toBe(0)
    expect(hi).toBe(1)
  })

  it('filters NaN and null from mixed array, bounds finite values with padding', () => {
    const [lo, hi] = safeDomain([NaN, 10, 20, null, 30])
    // Finite values are 10, 20, 30; padding = (30-10)*0.05 = 1
    expect(lo).toBeLessThan(10)
    expect(hi).toBeGreaterThan(30)
  })

  it('single value gets non-zero padding so recharts axis renders', () => {
    const [lo, hi] = safeDomain([100])
    expect(lo).toBeLessThan(100)
    expect(hi).toBeGreaterThan(100)
  })

  it('respects custom paddingFactor', () => {
    // [10, 20] with paddingFactor=0.1 → padding = (20-10)*0.1 = 1
    const [lo, hi] = safeDomain([10, 20], 0.1)
    expect(lo).toBe(9)
    expect(hi).toBe(21)
  })

  it('handles Infinity values (not finite) as if absent', () => {
    const [lo, hi] = safeDomain([Infinity, -Infinity, 5, 10])
    expect(lo).toBeLessThan(5)
    expect(hi).toBeGreaterThan(10)
  })

  it('symmetric padding: lo and hi are equidistant from min and max', () => {
    const [lo, hi] = safeDomain([0, 100], 0.05)
    const padding = 100 * 0.05 // 5
    expect(lo).toBe(-5)
    expect(hi).toBe(105)
  })
})
