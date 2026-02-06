import { useState, useEffect, useCallback } from 'react'
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useEventStream } from './hooks/useEventStream'
import { useMediaQuery } from './hooks/useMediaQuery'
import { createSession, listSessions, deleteSession, getSession, renameSession, sendMessage, cancelRun, resolvePermission } from './lib/api'
import { cn } from './lib/utils'
import Sidebar from './components/Sidebar'
import ChatTimeline from './components/ChatTimeline'
import InputArea from './components/InputArea'
import Inspector from './components/Inspector'
import PermissionModal from './components/PermissionModal'

export default function App() {
  const isMobile = useMediaQuery('(max-width: 768px)')

  // Session state
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [viewMode, setViewMode] = useState('chat')
  const [historyMessages, setHistoryMessages] = useState([])
  const [pendingMessages, setPendingMessages] = useState({})
  const [localSendingSessionId, setLocalSendingSessionId] = useState(null)
  const [searchFocusTrigger, setSearchFocusTrigger] = useState(0)

  // SSE event stream for active session
  const eventState = useEventStream(activeSessionId)

  // Load sessions on mount
  useEffect(() => {
    listSessions()
      .then(list => setSessions(list))
      .catch(err => console.error('Failed to load sessions:', err))
  }, [])

  // On mobile, default panels to closed.
  useEffect(() => {
    if (isMobile) {
      setSidebarOpen(false)
      setInspectorOpen(false)
      return
    }

    setSidebarOpen(true)
  }, [isMobile])

  // Reload session list periodically to catch auto-naming updates
  useEffect(() => {
    const interval = setInterval(() => {
      listSessions()
        .then(list => setSessions(list))
        .catch(() => {})
    }, 5000)
    return () => clearInterval(interval)
  }, [])

  // Load session history when switching sessions
  useEffect(() => {
    if (!activeSessionId) {
      setHistoryMessages([])
      setLocalSendingSessionId(null)
      return
    }
    let cancelled = false
    const sid = activeSessionId

    getSession(sid)
      .then(data => {
        if (cancelled) return
        const msgs = (data.messages || []).map((m, i) => ({
          id: m.id || `hist_${i}`,
          type: m.role === 'user' ? 'user' : 'assistant',
          text: m.content,
          ts: m.ts,
        }))
        setHistoryMessages(msgs)
        // Clear local optimistic messages after persisted history is loaded.
        setPendingMessages(prev => ({ ...prev, [sid]: [] }))
      })
      .catch(() => {
        if (!cancelled) setHistoryMessages([])
      })

    return () => {
      cancelled = true
    }
  }, [activeSessionId])

  const addPendingMessage = useCallback((sessionId, text) => {
    const localId = `local_user_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const localMsg = {
      id: localId,
      type: 'user',
      text,
      ts: Date.now() / 1000,
    }
    setPendingMessages(prev => ({
      ...prev,
      [sessionId]: [...(prev[sessionId] || []), localMsg],
    }))
    return localId
  }, [])

  const removePendingMessage = useCallback((sessionId, localId) => {
    setPendingMessages(prev => ({
      ...prev,
      [sessionId]: (prev[sessionId] || []).filter(m => m.id !== localId),
    }))
  }, [])

  useEffect(() => {
    if (viewMode === 'agent') {
      setInspectorOpen(true)
      if (isMobile) setSidebarOpen(false)
    }
  }, [viewMode, isMobile])

  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSidebarOpen(true)
        if (isMobile) setInspectorOpen(false)
        setSearchFocusTrigger(prev => prev + 1)
      }
      if (e.key === 'Escape') {
        setInspectorOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isMobile])

  // Create new session
  const handleNewSession = useCallback(async () => {
    try {
      const session = await createSession('New Chat')
      setSessions(prev => [session, ...prev])
      setActiveSessionId(session.id)
    } catch (err) {
      console.error('Failed to create session:', err)
    }
  }, [])

  // Select session
  const handleSelectSession = useCallback((id) => {
    setActiveSessionId(id)
    if (isMobile) setSidebarOpen(false)
  }, [isMobile])

  // Delete session
  const handleDeleteSession = useCallback(async (id) => {
    try {
      await deleteSession(id)
      setSessions(prev => prev.filter(s => s.id !== id))
      if (activeSessionId === id) {
        setActiveSessionId(null)
      }
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }, [activeSessionId])

  // Rename session
  const handleRenameSession = useCallback(async (id, newTitle) => {
    try {
      const updated = await renameSession(id, newTitle)
      setSessions(prev => prev.map(s => s.id === id ? { ...s, title: updated.title || newTitle } : s))
    } catch (err) {
      console.error('Failed to rename session:', err)
    }
  }, [])

  // Send message
  const handleSend = useCallback(async (text) => {
    if (!activeSessionId) {
      // Auto-create a session first
      try {
        const session = await createSession('New Chat')
        const sid = session.id
        setSessions(prev => [session, ...prev])
        setActiveSessionId(sid)

        const localId = addPendingMessage(sid, text)
        setLocalSendingSessionId(sid)
        try {
          await sendMessage(sid, text)
        } catch (err) {
          removePendingMessage(sid, localId)
          console.error('Failed to send message:', err)
        } finally {
          setTimeout(() => {
            setLocalSendingSessionId(prev => (prev === sid ? null : prev))
          }, 1200)
        }
      } catch (err) {
        console.error('Failed to create session:', err)
      }
      return
    }

    const sid = activeSessionId
    const localId = addPendingMessage(sid, text)
    setLocalSendingSessionId(sid)

    try {
      await sendMessage(sid, text)
    } catch (err) {
      removePendingMessage(sid, localId)
      console.error('Failed to send message:', err)
    } finally {
      setTimeout(() => {
        setLocalSendingSessionId(prev => (prev === sid ? null : prev))
      }, 1200)
    }
  }, [activeSessionId, addPendingMessage, removePendingMessage])

  // Cancel run
  const handleCancel = useCallback(async () => {
    if (!activeSessionId) return
    try {
      await cancelRun(activeSessionId)
      setLocalSendingSessionId(null)
    } catch (err) {
      console.error('Failed to cancel:', err)
    }
  }, [activeSessionId])

  const isRunning = eventState.status === 'running' || localSendingSessionId === activeSessionId

  // Merge history messages with live SSE blocks
  const pendingForActive = activeSessionId ? (pendingMessages[activeSessionId] || []) : []
  const allBlocks = [...historyMessages, ...pendingForActive, ...eventState.blocks]

  const toggleSidebar = () => {
    setSidebarOpen(o => {
      const next = !o
      if (isMobile && next) setInspectorOpen(false)
      return next
    })
  }

  const toggleInspector = () => {
    setInspectorOpen(o => {
      const next = !o
      if (isMobile && next) setSidebarOpen(false)
      return next
    })
  }

  return (
    <div className="flex h-dvh bg-bg text-text-primary overflow-hidden">
      {sidebarOpen && (
        <>
          {isMobile && (
            <button
              className="fixed inset-0 z-40 bg-black/20"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
            />
          )}

          <div
            className={cn(
              isMobile
                ? 'fixed inset-y-0 left-0 z-50 w-[min(20rem,85vw)] shadow-xl'
                : 'w-64 shrink-0'
            )}
          >
            <Sidebar
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSelectSession={handleSelectSession}
              onNewSession={handleNewSession}
              onDeleteSession={handleDeleteSession}
              onRenameSession={handleRenameSession}
              searchFocusTrigger={searchFocusTrigger}
            />
          </div>
        </>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between px-3 py-1.5 pt-[calc(0.375rem+env(safe-area-inset-top))] border-b border-border bg-bg">
          <div className="flex items-center gap-2">
            <button
              onClick={toggleSidebar}
              className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-secondary transition-colors"
              title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
            >
              {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
            </button>

            {activeSessionId && (
              <span className="text-xs text-text-secondary truncate max-w-xs">
                {sessions.find(s => s.id === activeSessionId)?.title || 'Untitled'}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1">
            <div className="flex items-center bg-bg-secondary rounded border border-border-soft p-0.5">
              <button
                onClick={() => setViewMode('chat')}
                className={cn(
                  'px-2 py-0.5 rounded text-xs transition-colors',
                  viewMode === 'chat'
                    ? 'bg-bg text-text-primary border border-border-soft'
                    : 'text-text-muted hover:text-text-secondary'
                )}
                title="Chat mode: clean conversation view"
              >
                Chat
              </button>
              <button
                onClick={() => setViewMode('agent')}
                className={cn(
                  'px-2 py-0.5 rounded text-xs transition-colors',
                  viewMode === 'agent'
                    ? 'bg-bg text-text-primary border border-border-soft'
                    : 'text-text-muted hover:text-text-secondary'
                )}
                title="Agent mode: full execution timeline"
              >
                Agent
              </button>
            </div>

            <button
              onClick={toggleInspector}
              className={cn(
                'p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-secondary transition-colors ml-1',
                inspectorOpen && 'text-text-primary bg-bg-secondary'
              )}
              title={inspectorOpen ? 'Close inspector' : 'Open inspector'}
            >
              {inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
            </button>

            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full ml-1',
                eventState.connectionStatus === 'connected' ? 'bg-status-success'
                  : eventState.connectionStatus === 'connecting' ? 'bg-status-pending animate-pulse-dot'
                  : 'bg-text-muted'
              )}
              title={`SSE: ${eventState.connectionStatus}`}
            />
          </div>
        </div>

        <ChatTimeline
          blocks={allBlocks}
          streamingText={eventState.streamingText}
          streamingBlockId={eventState.streamingMessageId}
          viewMode={viewMode}
          status={isRunning ? 'running' : eventState.status}
        />

        {activeSessionId && (
          <InputArea
            onSend={handleSend}
            onCancel={handleCancel}
            isRunning={isRunning}
          />
        )}

        {!activeSessionId && (
          <div className="border-t border-border bg-bg p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
            <div className="max-w-chat mx-auto">
              <button
                onClick={handleNewSession}
                className="w-full py-2 rounded border border-border-soft text-text-secondary hover:text-text-primary hover:border-border transition-colors text-sm"
              >
                Start a new chat
              </button>
            </div>
          </div>
        )}
      </div>

      {inspectorOpen && (
        <>
          {isMobile && (
            <button
              className="fixed inset-0 z-40 bg-black/20"
              onClick={() => setInspectorOpen(false)}
              aria-label="Close inspector"
            />
          )}

          <div
            className={cn(
              isMobile
                ? 'fixed inset-y-0 right-0 z-50 w-[min(22rem,85vw)] shadow-xl'
                : 'w-80 shrink-0'
            )}
          >
            <Inspector
              sessionId={activeSessionId}
              toolCalls={eventState.toolCalls}
              usage={eventState.usage}
              connectionStatus={eventState.connectionStatus}
              status={eventState.status}
              blocks={allBlocks}
            />
          </div>
        </>
      )}

      <PermissionModal
        request={eventState.pendingPermission}
        onApprove={async (scope) => {
          if (!eventState.pendingPermission) return
          await resolvePermission(eventState.pendingPermission.requestId, 'approved', scope)
          eventState.clearPendingPermission()
        }}
        onDeny={async () => {
          if (!eventState.pendingPermission) return
          await resolvePermission(eventState.pendingPermission.requestId, 'denied', 'once')
          eventState.clearPendingPermission()
        }}
        onClose={() => eventState.clearPendingPermission()}
      />
    </div>
  )
}
