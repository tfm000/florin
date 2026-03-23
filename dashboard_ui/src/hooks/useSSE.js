import { useState, useEffect, useRef, useCallback } from 'react'

const API_BASE = '/api'

/**
 * React hook for Server-Sent Events with cache-then-refresh pattern.
 *
 * @param {string|null} path - SSE endpoint path (null to disable)
 * @param {Object} options
 * @param {boolean} options.autoFetch - Connect on mount (default true)
 * @returns {{ data, loading, stale, error, reconnect }}
 */
export function useSSE(path, options = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [stale, setStale] = useState(false)
  const [error, setError] = useState(null)
  const sourceRef = useRef(null)
  const { autoFetch = true } = options

  const connect = useCallback(() => {
    if (!path) {
      setLoading(false)
      setData(null)
      return
    }
    setLoading(true)
    setError(null)

    // Close any existing connection
    if (sourceRef.current) {
      sourceRef.current.close()
    }

    const es = new EventSource(`${API_BASE}${path}`)
    sourceRef.current = es

    es.addEventListener('cached', (e) => {
      setData(JSON.parse(e.data))
      setLoading(false)
      setStale(true)
    })

    es.addEventListener('loading', () => {
      // No cache — keep loading=true until fresh data arrives
    })

    es.addEventListener('fresh', (e) => {
      setData(JSON.parse(e.data))
      setLoading(false)
      setStale(false)
    })

    es.addEventListener('error', (e) => {
      try {
        const payload = JSON.parse(e.data)
        setError(payload.error || 'SSE error')
      } catch {
        setError('SSE error')
      }
      setLoading(false)
    })

    es.addEventListener('done', () => {
      es.close()
      sourceRef.current = null
    })

    es.onerror = () => {
      // EventSource auto-reconnects on error; close to prevent loops
      setError('SSE connection failed')
      setLoading(false)
      es.close()
      sourceRef.current = null
    }
  }, [path])

  useEffect(() => {
    if (autoFetch) connect()
    return () => {
      if (sourceRef.current) {
        sourceRef.current.close()
        sourceRef.current = null
      }
    }
  }, [connect, autoFetch])

  return { data, loading, stale, error, reconnect: connect }
}
