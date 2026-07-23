const BASE = ''

const OPS_KEY =
  (typeof import.meta !== 'undefined' &&
    (import.meta as ImportMeta & { env?: Record<string, string> }).env
      ?.VITE_CONNOR_OPS_API_KEY) ||
  ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (OPS_KEY) {
    headers['X-Connor-Ops-Key'] = OPS_KEY
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail?.detail?.message || detail?.detail || res.statusText)
  }
  return res.json() as Promise<T>
}

export const api = {
  overview: () => request<any>('/api/console/overview'),
  annotationMeta: () => request<any>('/api/console/meta/annotation'),
  runs: () => request<any[]>('/api/console/runs?limit=50'),
  run: (id: string) => request<any>(`/api/console/runs/${id}`),
  candidates: (id: string) => request<any>(`/api/console/runs/${id}/candidates`),
  selection: (id: string) => request<any>(`/api/console/runs/${id}/selection`),
  versions: (id: string) => request<any>(`/api/console/runs/${id}/versions`),
  errors: (id: string) => request<any>(`/api/console/runs/${id}/errors`),
  annotations: () => request<any[]>('/api/console/annotations'),
  createAnnotation: (source_run_id: string) =>
    request<any>('/api/console/annotations', {
      method: 'POST',
      body: JSON.stringify({ source_run_id, annotator: 'console' }),
    }),
  annotation: (id: string) => request<any>(`/api/console/annotations/${id}`),
  annotationItems: (id: string) => request<any>(`/api/console/annotations/${id}/items`),
  patchItem: (runId: string, itemId: string, body: Record<string, unknown>) =>
    request<any>(`/api/console/annotations/${runId}/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  complete: (id: string) =>
    request<any>(`/api/console/annotations/${id}/complete`, { method: 'POST' }),
  reopen: (id: string) =>
    request<any>(`/api/console/annotations/${id}/reopen`, { method: 'POST' }),
  cancel: (id: string) =>
    request<any>(`/api/console/annotations/${id}/cancel`, { method: 'POST' }),
  diff: (id: string) => request<any>(`/api/console/annotations/${id}/diff`),
  watchlist: () => request<any>('/api/console/watchlist'),
  watchlistAudits: () => request<any[]>('/api/console/watchlist/audits?limit=30'),
  watchlistAudit: (id: string) => request<any>(`/api/console/watchlist/audits/${id}`),
  startWatchlistAudit: (body: Record<string, unknown>) =>
    request<any>('/api/console/watchlist/audits', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  analyticsSummary: (days = 7) =>
    request<any>(`/api/console/analytics/summary?days=${days}`),
  analyticsTimeseries: (days = 7) =>
    request<any>(`/api/console/analytics/timeseries?days=${days}`),
  analyticsPaths: (days = 7, limit = 20) =>
    request<any>(`/api/console/analytics/paths?days=${days}&limit=${limit}`),
  analyticsHours: (days = 7) =>
    request<any>(`/api/console/analytics/hours?days=${days}`),
}
