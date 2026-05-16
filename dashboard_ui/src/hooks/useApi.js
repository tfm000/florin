import { useState, useEffect, useCallback } from 'react'

const API_BASE = '/api'

export function useApi(path, options = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [stale, setStale] = useState(false)
  const { autoFetch = true, interval = null } = options

  const fetchData = useCallback(async () => {
    if (!path) { setLoading(false); setData(null); setStale(false); return }
    try {
      setLoading(true)
      const res = await fetch(`${API_BASE}${path}`)
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`)
      }
      const json = await res.json()
      setData(json)
      setError(null)
      setStale(false)
    } catch (err) {
      // Intentionally do NOT setData(null) — last successful response is preserved
      // so callers can choose between "show stale + banner" and "show error only" via
      // the new `stale` flag. See CONTEXT.md D-08, D-09. ChartFrame (Phase 2 PRIM-04)
      // will wire stale-aware rendering uniformly.
      setError(err.message)
      setStale(true)
    } finally {
      setLoading(false)
    }
  }, [path])

  useEffect(() => {
    if (autoFetch) fetchData()
  }, [path, autoFetch, fetchData])

  useEffect(() => {
    if (!interval || !autoFetch) return
    const id = setInterval(fetchData, interval)
    return () => clearInterval(id)
  }, [interval, autoFetch, fetchData])

  return { data, loading, error, stale, refetch: fetchData }
}

export async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Request failed')
  return data
}

export async function apiPut(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Request failed')
  return data
}

export async function apiDelete(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Request failed')
  return data
}

export async function apiFetch(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}
