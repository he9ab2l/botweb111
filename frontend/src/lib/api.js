import { createClient } from '../sdk/client'

// Single entry point for REST + SSE
export const client = createClient()

export const createSession = client.createSession
export const listSessions = client.listSessions
export const getSession = client.getSession
export const renameSession = client.renameSession
export const deleteSession = client.deleteSession

// v2: sending a message creates a turn
export async function sendMessage(sessionId, content) {
  return client.createTurn(sessionId, content)
}

export const cancelRun = client.cancelRun

export const fsTree = client.fsTree
export const fsRead = client.fsRead
export const fsVersions = client.fsVersions
export const fsGetVersion = client.fsGetVersion
export const fsRollback = client.fsRollback


// v1 memory endpoints are kept on the backend; expose them only if needed later.
export async function getMemory() {
  const res = await fetch(`/api/v1/memory`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
export async function putMemory(key, value) {
  const res = await fetch(`/api/v1/memory`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
export async function deleteMemory(key) {
  const res = await fetch(`/api/v1/memory/${encodeURIComponent(key)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function connectSSE(sessionId, lastEventId, onEvent, onError) {
  const since = lastEventId != null && lastEventId !== '' ? Number(lastEventId) : null
  return client.subscribeEvents({
    sessionId,
    since: Number.isFinite(since) ? since : null,
    onEvent,
    onError,
  })
}

export const listFileChanges = client.listFileChanges
export const listTerminal = client.listTerminal
export const listContext = client.listContext
export const pinContext = client.pinContext
export const unpinContext = client.unpinContext
export const listPendingPermissions = client.listPendingPermissions
export const resolvePermission = client.resolvePermission
