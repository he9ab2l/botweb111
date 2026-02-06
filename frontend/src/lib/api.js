// API helper
const BASE = '/api/v1'

async function api(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function createSession(title = 'New Chat') {
  return api('/sessions', { method: 'POST', body: { title } })
}

export async function listSessions() {
  return api('/sessions')
}

export async function getSession(id) {
  return api(`/sessions/${id}`)
}

export async function renameSession(id, title) {
  return api(`/sessions/${id}`, { method: 'PATCH', body: { title } })
}

export async function deleteSession(id) {
  return api(`/sessions/${id}`, { method: 'DELETE' })
}

export async function sendMessage(sessionId, content) {
  return api(`/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: { content },
  })
}

export async function cancelRun(sessionId) {
  return api(`/sessions/${sessionId}/cancel`, { method: 'POST' })
}

export async function getMemory() {
  return api('/memory')
}

export async function putMemory(key, value) {
  return api('/memory', { method: 'PUT', body: { key, value } })
}

export async function deleteMemory(key) {
  return api(`/memory/${encodeURIComponent(key)}`, { method: 'DELETE' })
}

export function connectSSE(sessionId, lastEventId, onEvent, onError) {
  let url = `${BASE}/sessions/${sessionId}/events`
  if (lastEventId) url += `?last_event_id=${encodeURIComponent(lastEventId)}`

  const es = new EventSource(url)

  es.addEventListener('chat_event', (e) => {
    try {
      const data = JSON.parse(e.data)
      onEvent(data, e.lastEventId || data.id)
    } catch (err) {
      console.error('SSE parse error:', err)
    }
  })

  es.addEventListener('heartbeat', () => {})

  es.onerror = (err) => {
    onError?.(err)
  }

  es.onopen = () => {}

  return es
}
