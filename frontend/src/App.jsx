import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Settings,
  Search,
  Copy,
  Check,
  X,
} from 'lucide-react'
import { useEventStream } from './hooks/useEventStream'
import { useMediaQuery } from './hooks/useMediaQuery'
import {
  createSession,
  listSessions,
  deleteSession,
  getSession,
  getConfig,
  getSessionModel,
  setSessionModel,
  clearSessionModel,
  renameSession,
  sendMessage,
  cancelRun,
  resolvePermission,
  getDocs,
  getDocFile,
} from './lib/api'
import { cn, copyToClipboard } from './lib/utils'
import Sidebar from './components/Sidebar'
import ChatTimeline from './components/ChatTimeline'
import InputArea from './components/InputArea'
import Inspector from './components/Inspector'
import PermissionModal from './components/PermissionModal'
import ModelSettingsModal from './components/ModelSettingsModal'

export default function App() {
  const isMobile = useMediaQuery('(max-width: 768px)')

  // Session state
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const [viewMode, setViewMode] = useState('chat')
  const [historyMessages, setHistoryMessages] = useState([])
  const [pendingMessages, setPendingMessages] = useState({})
  const [localSendingSessionId, setLocalSendingSessionId] = useState(null)
  const [searchFocusTrigger, setSearchFocusTrigger] = useState(0)

  // Docs state
  const [docs, setDocs] = useState([])
  const [extraDocs, setExtraDocs] = useState([])
  const [docsExpanded, setDocsExpanded] = useState(false)
  const [activeDoc, setActiveDoc] = useState(null)
  const [docState, setDocState] = useState({
    content: '',
    loading: false,
    error: '',
    truncated: false,
  })
  const [docSearch, setDocSearch] = useState('')
  const [docCopied, setDocCopied] = useState(false)
  const docSearchRef = useRef(null)
  const docRequestId = useRef(0)

  // Model/config state
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [configSummary, setConfigSummary] = useState(null)
  const [sessionModelInfo, setSessionModelInfo] = useState(null)
  const [modelInput, setModelInput] = useState('')

  // SSE event stream for active session
  const eventState = useEventStream(activeSessionId)

  const reloadConfig = useCallback(() => {
    getConfig()
      .then(cfg => setConfigSummary(cfg))
      .catch(() => {})
  }, [])

  const reloadSessionModel = useCallback((sid) => {
    if (!sid) {
      setSessionModelInfo(null)
      return
    }
    getSessionModel(sid)
      .then(sm => setSessionModelInfo(sm))
      .catch(() => setSessionModelInfo(null))
  }, [])

  const reloadDocs = useCallback(() => {
    getDocs()
      .then(data => {
        const base = data?.default || []
        const extra = data?.extra || []
        setDocs(base)
        setExtraDocs(extra)
        if (!activeDoc && base.length > 0) {
          setActiveDoc({
            title: base[0].title || base[0].path,
            path: base[0].path,
          })
        }
      })
      .catch(() => {})
  }, [activeDoc])

  // Load sessions on mount
  useEffect(() => {
    listSessions()
      .then(list => setSessions(list))
      .catch(err => console.error('Failed to load sessions:', err))
  }, [])

  useEffect(() => {
    reloadConfig()
    reloadDocs()
  }, [reloadConfig, reloadDocs])

  // On mobile, default panels to closed.
  useEffect(() => {
    if (isMobile) {
      setSidebarOpen(false)
      setInspectorOpen(false)
      return
    }

    setSidebarOpen(true)
    setInspectorOpen(true)
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

  useEffect(() => {
    reloadSessionModel(activeSessionId)
  }, [activeSessionId, reloadSessionModel])

  useEffect(() => {
    const next = (sessionModelInfo?.effective_model || configSummary?.default_model || '').trim()
    setModelInput(next)
  }, [sessionModelInfo, configSummary])

  // Load active document content
  useEffect(() => {
    if (!activeDoc?.path) {
      setDocState({ content: '', loading: false, error: '', truncated: false })
      return
    }

    const reqId = ++docRequestId.current
    setDocState({ content: '', loading: true, error: '', truncated: false })

    getDocFile(activeDoc.path)
      .then(data => {
        if (reqId !== docRequestId.current) return
        setDocState({
          content: data?.content || '',
          loading: false,
          error: '',
          truncated: !!data?.truncated,
        })
      })
      .catch((e) => {
        if (reqId !== docRequestId.current) return
        setDocState({
          content: '',
          loading: false,
          error: e?.message || 'Failed to load document',
          truncated: false,
        })
      })
  }, [activeDoc])

  useEffect(() => {
    if (activeDoc?.path) setDocSearch(activeDoc.path)
  }, [activeDoc?.path])

  useEffect(() => {
    if (viewMode === 'agent') {
      setInspectorOpen(true)
      if (isMobile) setSidebarOpen(false)
    }
  }, [viewMode, isMobile])

  useEffect(() => {
    const handler = (e) => {
      const key = (e.key || '').toLowerCase()
      if ((e.ctrlKey || e.metaKey) && key === 'k') {
        e.preventDefault()
        setSidebarOpen(true)
        if (isMobile) setInspectorOpen(false)
        setSearchFocusTrigger(prev => prev + 1)
      }
      if ((e.ctrlKey || e.metaKey) && key === 'p') {
        e.preventDefault()
        docSearchRef.current?.focus()
        docSearchRef.current?.select()
      }
      if (e.key === 'Escape') {
        setInspectorOpen(false)
        setSettingsOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isMobile])

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

  // Create new session
  const handleNewSession = useCallback(async () => {
    try {
      const session = await createSession('New Chat')
      setSessions(prev => [session, ...prev])
      setActiveSessionId(session.id)

      const desired = (modelInput || '').trim()
      const defaultModel = (configSummary?.default_model || '').trim()
      if (desired && desired !== defaultModel) {
        try {
          await setSessionModel(session.id, desired)
        } catch (err) {
          console.error('Failed to set model override:', err)
        } finally {
          reloadSessionModel(session.id)
        }
      }
    } catch (err) {
      console.error('Failed to create session:', err)
    }
  }, [modelInput, configSummary, reloadSessionModel])

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

  const handleSelectDoc = useCallback((doc) => {
    if (!doc?.path) return
    setActiveDoc({ title: doc.title || doc.path, path: doc.path })
    if (isMobile) setSidebarOpen(false)
  }, [isMobile])

  const handleDocSearchSubmit = useCallback(() => {
    const q = (docSearch || '').trim()
    if (!q) return
    const allDocs = [...(docs || []), ...(extraDocs || [])]
    const lower = q.toLowerCase()
    let match = allDocs.find(d => d.path === q || d.title === q)
    if (!match) {
      match = allDocs.find(d =>
        String(d.path || '').toLowerCase().includes(lower) ||
        String(d.title || '').toLowerCase().includes(lower)
      )
    }
    if (match) {
      handleSelectDoc(match)
    }
  }, [docSearch, docs, extraDocs, handleSelectDoc])

  const handleCopyDocPath = useCallback(async () => {
    if (!activeDoc?.path) return
    const ok = await copyToClipboard(activeDoc.path)
    if (ok) {
      setDocCopied(true)
      setTimeout(() => setDocCopied(false), 1500)
    }
  }, [activeDoc])

  const handleApplyModel = useCallback(async () => {
    if (!activeSessionId) return
    const next = (modelInput || '').trim()
    if (!next) return
    try {
      await setSessionModel(activeSessionId, next)
      reloadSessionModel(activeSessionId)
    } catch (err) {
      console.error('Failed to set model:', err)
    }
  }, [activeSessionId, modelInput, reloadSessionModel])

  const handleClearModel = useCallback(async () => {
    if (!activeSessionId) return
    try {
      await clearSessionModel(activeSessionId)
      reloadSessionModel(activeSessionId)
    } catch (err) {
      console.error('Failed to clear model override:', err)
    }
  }, [activeSessionId, reloadSessionModel])

  // Send message
  const handleSend = useCallback(async (text) => {
    if (!activeSessionId) {
      // Auto-create a session first
      try {
        const session = await createSession('New Chat')
        const sid = session.id
        setSessions(prev => [session, ...prev])
        setActiveSessionId(sid)

        const desired = (modelInput || '').trim()
        const defaultModel = (configSummary?.default_model || '').trim()
        if (desired && desired !== defaultModel) {
          try {
            await setSessionModel(sid, desired)
          } catch (err) {
            console.error('Failed to set model override:', err)
          } finally {
            reloadSessionModel(sid)
          }
        }

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
  }, [activeSessionId, addPendingMessage, removePendingMessage, modelInput, configSummary, reloadSessionModel])

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

  const modelLabel = (sessionModelInfo?.effective_model || configSummary?.default_model || '').trim()

  const modelOptions = useMemo(() => {
    const opts = new Set()
    const providers = configSummary?.providers || {}
    const isConfigured = (name) => !!providers?.[name]?.configured
    const allow = (model) => {
      if (!configSummary) return true
      const m = String(model || '').toLowerCase()
      if (m.startsWith('zai/') || m.includes('glm') || m.includes('zhipu')) return isConfigured('zhipu')
      if (m.startsWith('openai/') || m.includes('gpt')) return isConfigured('openai')
      if (m.startsWith('anthropic/') || m.includes('claude')) return isConfigured('anthropic')
      if (m.startsWith('openrouter/')) return isConfigured('openrouter')
      if (m.startsWith('gemini/')) return isConfigured('gemini')
      if (m.startsWith('vllm/')) return isConfigured('vllm')
      if (m.startsWith('deepseek/')) return isConfigured('deepseek')
      if (m.startsWith('groq/')) return isConfigured('groq')
      if (m.startsWith('moonshot/') || m.includes('kimi')) return isConfigured('moonshot')
      return true
    }
    ;(configSummary?.recommended_models || []).forEach((m) => {
      if (m && allow(m)) opts.add(m)
    })
    if (configSummary?.default_model) opts.add(configSummary.default_model)
    if (sessionModelInfo?.effective_model) opts.add(sessionModelInfo.effective_model)
    if (sessionModelInfo?.override_model) opts.add(sessionModelInfo.override_model)
    return Array.from(opts)
  }, [configSummary, sessionModelInfo])

  const hasOverride = !!sessionModelInfo?.override_model

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

  const activeSession = sessions.find(s => s.id === activeSessionId)
  const docPayload = activeDoc ? {
    title: activeDoc.title,
    path: activeDoc.path,
    content: docState.content,
    loading: docState.loading,
    error: docState.error,
    truncated: docState.truncated,
  } : null

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
              docs={docs}
              extraDocs={extraDocs}
              activeDocPath={activeDoc?.path || ''}
              onSelectDoc={handleSelectDoc}
              docsExpanded={docsExpanded}
              onToggleDocs={() => setDocsExpanded(v => !v)}
              onOpenSettings={() => setSettingsOpen(true)}
            />
          </div>
        </>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between gap-3 px-3 py-1.5 pt-[calc(0.375rem+env(safe-area-inset-top))] border-b border-border bg-bg">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={toggleSidebar}
              className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-secondary transition-colors"
              title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
            >
              {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
            </button>

            <div className="min-w-0">
              <div className="text-xs text-text-primary truncate max-w-[220px]">
                {activeDoc?.title || activeSession?.title || 'fanfan'}
              </div>
              <div className="text-[10px] text-text-muted font-mono truncate max-w-[240px]">
                {activeDoc?.path || activeSessionId || 'Select a chat or document'}
              </div>
            </div>
          </div>

          <div className="flex-1 max-w-[420px]">
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                ref={docSearchRef}
                value={docSearch}
                onChange={(e) => setDocSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleDocSearchSubmit()
                  }
                }}
                placeholder="Search docs (Ctrl+P)"
                list="doc-search-list"
                className={cn(
                  'w-full pl-8 pr-8 py-1.5 rounded text-xs',
                  'bg-bg-secondary border border-border-soft text-text-primary',
                  'placeholder:text-text-muted',
                  'focus:outline-none focus:border-accent-blue'
                )}
              />
              {docSearch && (
                <button
                  onClick={() => setDocSearch('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                  aria-label="Clear search"
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <datalist id="doc-search-list">
              {[...docs, ...extraDocs].map((d) => (
                <option key={d.path} value={d.path}>{d.title || d.path}</option>
              ))}
            </datalist>
          </div>

          <div className="flex items-center gap-1">
            {activeDoc?.path && (
              <button
                onClick={handleCopyDocPath}
                className="flex items-center gap-1 px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-primary hover:border-border transition-colors"
                title="Copy path"
              >
                {docCopied ? <Check size={13} /> : <Copy size={13} />}
                <span className="hidden md:inline text-[11px]">Copy Path</span>
              </button>
            )}

            <button
              onClick={() => setSettingsOpen(true)}
              className="flex items-center gap-1 px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-primary hover:border-border transition-colors"
              title="Model & API Settings"
            >
              <Settings size={14} />
              <span className="text-[11px] font-mono max-w-[220px] truncate hidden md:inline">
                {modelLabel || 'Model'}
              </span>
            </button>

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
                onClick={() => setViewMode('docs')}
                className={cn(
                  'px-2 py-0.5 rounded text-xs transition-colors',
                  viewMode === 'docs'
                    ? 'bg-bg text-text-primary border border-border-soft'
                    : 'text-text-muted hover:text-text-secondary'
                )}
                title="Docs mode: show the active document"
              >
                Docs
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
          doc={docPayload}
        />

        {activeSessionId && (
          <InputArea
            onSend={handleSend}
            onCancel={handleCancel}
            isRunning={isRunning}
            modelValue={modelInput}
            modelOptions={modelOptions}
            onModelChange={setModelInput}
            onApplyModel={handleApplyModel}
            onClearModel={handleClearModel}
            hasOverride={hasOverride}
            onOpenSettings={() => setSettingsOpen(true)}
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

      <ModelSettingsModal
        open={settingsOpen}
        sessionId={activeSessionId}
        onClose={() => setSettingsOpen(false)}
        onUpdated={() => {
          reloadConfig()
          reloadDocs()
          reloadSessionModel(activeSessionId)
        }}
      />
    </div>
  )
}
