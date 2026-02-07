import type { EventEnvelope, SessionRecord } from './types'

type FetchLike = typeof fetch

export type Client = {
  baseUrl: string
  createSession: (title?: string) => Promise<SessionRecord>
  listSessions: () => Promise<SessionRecord[]>
  getSession: (id: string) => Promise<any>
  renameSession: (id: string, title: string) => Promise<any>
  deleteSession: (id: string) => Promise<any>
  createTurn: (sessionId: string, content: string) => Promise<any>
  cancelRun: (sessionId: string) => Promise<any>

  getConfig: () => Promise<any>
  updateConfig: (body: any) => Promise<any>

  getSessionModel: (sessionId: string) => Promise<any>
  setSessionModel: (sessionId: string, model: string) => Promise<any>
  clearSessionModel: (sessionId: string) => Promise<any>

  getDocs: () => Promise<any>
  getDocFile: (path: string) => Promise<any>

  getPermissionMode: () => Promise<any>
  setPermissionMode: (mode: string) => Promise<any>

  getEvents: (sessionId: string, opts?: { since?: number; since_seq?: number }) => Promise<EventEnvelope[]>
  subscribeEvents: (opts: {
    sessionId: string
    since?: number | null
    onEvent: (evt: EventEnvelope, lastEventId: string | null) => void
    onConnected?: (evt: EventEnvelope) => void
    onHeartbeat?: () => void
    onError?: (err: any) => void
  }) => EventSource

  fsTree: (sessionId: string) => Promise<any>
  fsRead: (sessionId: string, path: string) => Promise<any>
  fsVersions: (sessionId: string, path: string) => Promise<any[]>
  fsGetVersion: (sessionId: string, versionId: string) => Promise<any>
  fsRollback: (sessionId: string, path: string, versionId: string) => Promise<any>

  listFileChanges: (sessionId: string) => Promise<any[]>
  listTerminal: (sessionId: string) => Promise<any[]>
  listContext: (sessionId: string) => Promise<any[]>
  pinContext: (sessionId: string, contextId: string) => Promise<any>
  unpinContext: (sessionId: string, contextId: string) => Promise<any>

  setContextPinnedRef: (sessionId: string, body: { kind: string; title?: string; content_ref: string; pinned: boolean }) => Promise<any>

  listPendingPermissions: (sessionId: string) => Promise<any[]>
  resolvePermission: (requestId: string, status: 'approved' | 'denied', scope: 'once' | 'session' | 'always') => Promise<any>

  // Provider/Model management
  listProviders: () => Promise<any>
  updateProvider: (providerId: string, data: { api_key?: string; api_base?: string | null }) => Promise<any>
  disconnectProvider: (providerId: string) => Promise<any>
  listModels: () => Promise<any>
  setModel: (model: string) => Promise<any>
}

export function createClient(opts: { baseUrl?: string; fetch?: FetchLike } = {}): Client {
  const baseUrl = opts.baseUrl || window.location.origin
  const f = opts.fetch || fetch

  const apiBase = `${baseUrl}/api/v2`

  async function api(path: string, init: RequestInit & { body?: any } = {}) {
    const res = await f(`${apiBase}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
      ...init,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  }

  function subscribeEvents({
    sessionId,
    since,
    onEvent,
    onConnected,
    onHeartbeat,
    onError,
  }: {
    sessionId: string
    since?: number | null
    onEvent: (evt: EventEnvelope, lastEventId: string | null) => void
    onConnected?: (evt: EventEnvelope) => void
    onHeartbeat?: () => void
    onError?: (err: any) => void
  }): EventSource {
    let url = `${baseUrl}/event?session_id=${encodeURIComponent(sessionId)}`
    if (since != null) url += `&since=${encodeURIComponent(String(since))}`

    const es = new EventSource(url)

    es.addEventListener('connected', (e: any) => {
      try {
        const data = JSON.parse(e.data)
        onConnected?.(data)
      } catch {}
    })

    es.addEventListener('heartbeat', () => {
      onHeartbeat?.()
    })

    es.addEventListener('event', (e: any) => {
      try {
        const data = JSON.parse(e.data)
        onEvent(data, e.lastEventId || data.id || null)
      } catch (err) {
        console.error('SSE parse error:', err)
      }
    })

    es.onerror = (err) => {
      onError?.(err)
    }

    return es
  }

  return {
    baseUrl,
    createSession: (title = 'New Chat') => api('/sessions', { method: 'POST', body: { title } }),
    listSessions: () => api('/sessions'),
    getSession: (id) => api(`/sessions/${encodeURIComponent(id)}`),
    renameSession: (id, title) => api(`/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', body: { title } }),
    deleteSession: (id) => api(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    createTurn: (sessionId, content) =>
      api(`/sessions/${encodeURIComponent(sessionId)}/turns`, { method: 'POST', body: { content } }),
    cancelRun: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/cancel`, { method: 'POST' }),

    getConfig: () => api('/config'),
    updateConfig: (body) => api('/config', { method: 'POST', body }),

    getSessionModel: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/model`),
    setSessionModel: (sessionId, model) =>
      api(`/sessions/${encodeURIComponent(sessionId)}/model`, { method: 'POST', body: { model } }),
    clearSessionModel: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/model`, { method: 'DELETE' }),

    getDocs: () => api('/docs'),
    getDocFile: (path) => api(`/docs/file?path=${encodeURIComponent(path)}`),

    getPermissionMode: () => api(`/permissions/mode`),
    setPermissionMode: (mode) => api(`/permissions/mode`, { method: "POST", body: { mode } }),

    getEvents: (sessionId, opts2 = {}) => {
      const q = new URLSearchParams()
      if (opts2.since != null) q.set('since', String(opts2.since))
      if (opts2.since_seq != null) q.set('since_seq', String(opts2.since_seq))
      const qs = q.toString()
      return api(`/sessions/${encodeURIComponent(sessionId)}/events${qs ? `?${qs}` : ''}`)
    },

    subscribeEvents,

    fsTree: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/fs/tree`),
    fsRead: (sessionId, path) => api(`/sessions/${encodeURIComponent(sessionId)}/fs/read?path=${encodeURIComponent(path)}`),
    fsVersions: (sessionId, path) => api(`/sessions/${encodeURIComponent(sessionId)}/fs/versions?path=${encodeURIComponent(path)}`),
    fsGetVersion: (sessionId, versionId) => api(`/sessions/${encodeURIComponent(sessionId)}/fs/version/${encodeURIComponent(versionId)}`),
    fsRollback: (sessionId, path, versionId) =>
      api(`/sessions/${encodeURIComponent(sessionId)}/fs/rollback`, { method: 'POST', body: { path, version_id: versionId } }),

    listFileChanges: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/file_changes`),
    listTerminal: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/terminal`),
    listContext: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/context`),
    pinContext: (sessionId, contextId) =>
      api(`/sessions/${encodeURIComponent(sessionId)}/context/pin`, { method: 'POST', body: { context_id: contextId } }),
    unpinContext: (sessionId, contextId) =>
      api(`/sessions/${encodeURIComponent(sessionId)}/context/unpin`, { method: 'POST', body: { context_id: contextId } }),

    setContextPinnedRef: (sessionId, body) =>
      api(`/sessions/${encodeURIComponent(sessionId)}/context/set_pinned_ref`, { method: 'POST', body }),

    listPendingPermissions: (sessionId) => api(`/sessions/${encodeURIComponent(sessionId)}/permissions/pending`),
    resolvePermission: (requestId, status, scope) =>
      api(`/permissions/${encodeURIComponent(requestId)}/resolve`, { method: 'POST', body: { status, scope } }),

    // Provider/Model management
    listProviders: () => api('/providers'),
    updateProvider: (providerId, data) =>
      api(`/providers/${encodeURIComponent(providerId)}`, { method: 'PUT', body: data }),
    disconnectProvider: (providerId) =>
      api(`/providers/${encodeURIComponent(providerId)}`, { method: 'DELETE' }),
    listModels: () => api('/models'),
    setModel: (model) => api('/model', { method: 'PUT', body: { model } }),
  }
}
