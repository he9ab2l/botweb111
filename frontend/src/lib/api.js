import { createClient } from '../sdk/client'

export const client = createClient()

export const createSession = client.createSession
export const listSessions = client.listSessions
export const getSession = client.getSession
export const renameSession = client.renameSession
export const deleteSession = client.deleteSession

export async function sendMessage(sessionId, content) {
  return client.createTurn(sessionId, content)
}

export const cancelRun = client.cancelRun

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

// Provider/Model API
export const listProviders = client.listProviders
export const updateProvider = client.updateProvider
export const disconnectProvider = client.disconnectProvider
export const listModels = client.listModels
export const setModel = client.setModel
