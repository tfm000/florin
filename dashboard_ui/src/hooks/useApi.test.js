import { renderHook, waitFor, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useApi } from './useApi'

// Helper: build a fetch mock that returns the queued responses in order.
function queueFetch(responses) {
  const fn = vi.fn()
  for (const r of responses) {
    fn.mockResolvedValueOnce({
      ok: r.ok ?? r.status < 400,
      status: r.status,
      statusText: r.statusText ?? '',
      json: async () => r.body ?? {},
    })
  }
  return fn
}

describe('useApi — FND-05 fail-loud (stale flag + data preservation)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('preserves data and sets stale=true on non-2xx response (D-08 contract)', async () => {
    globalThis.fetch = queueFetch([
      { status: 200, statusText: 'OK', body: { x: 1 } },
      { status: 500, statusText: 'Server Error', body: {} },
    ])

    const { result } = renderHook(() => useApi('/foo'))

    // First fetch: 200 -> data populated, no error, not stale
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual({ x: 1 })
    expect(result.current.error).toBeNull()
    expect(result.current.stale).toBe(false)

    // Second fetch: 500 -> data PRESERVED, error set, stale=true
    await act(async () => {
      await result.current.refetch()
    })
    expect(result.current.data).toEqual({ x: 1 }) // NOT cleared — D-08
    expect(result.current.stale).toBe(true)
    expect(result.current.error).toMatch(/500/)
    expect(result.current.loading).toBe(false)
  })

  it('clears stale on successful refetch after error (200 -> 500 -> 200)', async () => {
    globalThis.fetch = queueFetch([
      { status: 200, statusText: 'OK', body: { x: 1 } },
      { status: 500, statusText: 'Server Error', body: {} },
      { status: 200, statusText: 'OK', body: { x: 2 } },
    ])

    const { result } = renderHook(() => useApi('/foo'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(async () => {
      await result.current.refetch()
    })
    expect(result.current.stale).toBe(true)

    await act(async () => {
      await result.current.refetch()
    })
    expect(result.current.data).toEqual({ x: 2 })
    expect(result.current.stale).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('null path clears data and resets stale', async () => {
    globalThis.fetch = vi.fn()

    const { result } = renderHook(() => useApi(null))
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toBeNull()
    expect(result.current.stale).toBe(false)
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
