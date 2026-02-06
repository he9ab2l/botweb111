import { useEffect, useMemo, useState } from 'react'
import { Clock, RefreshCw, Wifi, WifiOff, ShieldAlert, FileCode, TerminalSquare, Layers, Fingerprint } from 'lucide-react'
import { cn, formatDuration, formatTime, truncate } from '../lib/utils'
import { listContext, listFileChanges, listPendingPermissions, listTerminal, pinContext, resolvePermission, unpinContext } from '../lib/api'

const TABS = ['Trace', 'Files', 'Terminal', 'Context', 'Permissions']

export default function Inspector({
  sessionId,
  toolCalls,
  usage,
  connectionStatus,
  status,
  blocks,
}) {
  const [tab, setTab] = useState('Trace')
  const [fileChanges, setFileChanges] = useState([])
  const [terminalRows, setTerminalRows] = useState([])
  const [contextItems, setContextItems] = useState([])
  const [pendingPerms, setPendingPerms] = useState([])
  const [loading, setLoading] = useState(false)

  const toolCount = toolCalls.length
  const errorCount = toolCalls.filter(t => t.status === 'error').length
  const totalDuration = toolCalls.reduce((acc, t) => acc + (t.duration_ms || 0), 0)

  const traceBlocks = useMemo(() => blocks.slice(-100), [blocks])

  async function refreshTabData(activeTab = tab) {
    if (!sessionId) return
    setLoading(true)
    try {
      if (activeTab === 'Files') setFileChanges(await listFileChanges(sessionId))
      if (activeTab === 'Terminal') setTerminalRows(await listTerminal(sessionId))
      if (activeTab === 'Context') setContextItems(await listContext(sessionId))
      if (activeTab === 'Permissions') setPendingPerms(await listPendingPermissions(sessionId))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Reset per-session inspector data
    setFileChanges([])
    setTerminalRows([])
    setContextItems([])
    setPendingPerms([])
    if (!sessionId) return
    refreshTabData(tab).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  useEffect(() => {
    if (!sessionId) return
    refreshTabData(tab).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  return (
    <div className="flex flex-col h-full bg-bg-secondary border-l border-border overflow-hidden">
      <div className="px-3 py-2 border-b border-border-soft flex items-center justify-between gap-2">
        <h3 className="text-[10px] text-text-muted uppercase tracking-wide">Inspector</h3>
        <button
          onClick={() => refreshTabData().catch(() => {})}
          className={cn(
            'inline-flex items-center gap-1 rounded px-2 py-1 text-[11px]',
            'border border-border-soft text-text-muted hover:text-text-secondary hover:border-border transition-colors',
            loading && 'opacity-60 cursor-wait'
          )}
          title="Refresh"
          disabled={!sessionId || loading}
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      <div className="px-2.5 py-2 border-b border-border-soft">
        <div className="flex items-center gap-1 flex-wrap">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'px-2 py-1 rounded text-[11px] border transition-colors',
                tab === t
                  ? 'bg-bg text-text-primary border-border-soft'
                  : 'bg-bg-secondary text-text-muted border-transparent hover:border-border-soft hover:text-text-secondary'
              )}
              title={t}
            >
              {t === 'Trace' && <Layers size={12} className="inline mr-1 -mt-0.5" />}
              {t === 'Files' && <FileCode size={12} className="inline mr-1 -mt-0.5" />}
              {t === 'Terminal' && <TerminalSquare size={12} className="inline mr-1 -mt-0.5" />}
              {t === 'Context' && <Fingerprint size={12} className="inline mr-1 -mt-0.5" />}
              {t === 'Permissions' && <ShieldAlert size={12} className="inline mr-1 -mt-0.5" />}
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 text-[11px] space-y-3">
        {tab === 'Trace' && (
          <>
            <Section title="Connection">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    'w-1.5 h-1.5 rounded-full',
                    connectionStatus === 'connected'
                      ? 'bg-status-success'
                      : connectionStatus === 'connecting'
                        ? 'bg-status-pending animate-pulse-dot'
                        : connectionStatus === 'error'
                          ? 'bg-status-error'
                          : 'bg-text-muted'
                  )}
                />
                {connectionStatus === 'connected' ? (
                  <Wifi size={12} className="text-text-muted" />
                ) : (
                  <WifiOff size={12} className="text-text-muted" />
                )}
                <span className="text-text-secondary">{connectionStatus}</span>
              </div>
            </Section>

            <Section title="Session">
              <InfoRow label="ID" value={sessionId || '—'} mono />
              <InfoRow label="Status" value={status} />
            </Section>

            {sessionId && (
              <Section title="Export">
                <div className="flex items-center gap-2">
                  <a
                    className="px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-secondary hover:border-border transition-colors"
                    href={`/api/v2/sessions/${encodeURIComponent(sessionId)}/export.json`}
                    target="_blank"
                    rel="noreferrer"
                    title="Download JSON export"
                  >
                    JSON
                  </a>
                  <a
                    className="px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-secondary hover:border-border transition-colors"
                    href={`/api/v2/sessions/${encodeURIComponent(sessionId)}/export.md`}
                    target="_blank"
                    rel="noreferrer"
                    title="Download Markdown export"
                  >
                    Markdown
                  </a>
                </div>
              </Section>
            )}

            {usage && (
              <Section title="Tokens">
                {usage.prompt_tokens != null && <InfoRow label="Prompt" value={usage.prompt_tokens.toLocaleString()} />}
                {usage.completion_tokens != null && <InfoRow label="Completion" value={usage.completion_tokens.toLocaleString()} />}
                {usage.total_tokens != null && <InfoRow label="Total" value={usage.total_tokens.toLocaleString()} />}
              </Section>
            )}

            <Section title={`Tools (${toolCount})`}>
              {toolCount === 0 ? (
                <p className="text-text-muted">No tool calls</p>
              ) : (
                <>
                  <div className="flex items-center gap-3 mb-1.5 text-text-muted">
                    {errorCount > 0 && (
                      <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-status-error" />
                        {errorCount} error{errorCount !== 1 ? 's' : ''}
                      </span>
                    )}
                    {totalDuration > 0 && (
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
                        {formatDuration(totalDuration)}
                      </span>
                    )}
                  </div>
                  <div className="space-y-0.5">
                    {toolCalls.map(tc => (
                      <div
                        key={tc.tool_call_id}
                        className="flex items-center gap-2 py-1 px-2 rounded border border-border-soft bg-bg/40"
                      >
                        <span
                          className={cn(
                            'w-1.5 h-1.5 rounded-full shrink-0',
                            tc.status === 'completed'
                              ? 'bg-status-success'
                              : tc.status === 'error'
                                ? 'bg-status-error'
                                : tc.status === 'permission_required'
                                  ? 'bg-status-pending animate-pulse-dot'
                                  : tc.status === 'running'
                                    ? 'bg-status-running animate-pulse-dot'
                                    : 'bg-status-pending animate-pulse-dot'
                          )}
                        />
                        <span className="font-mono text-text-primary truncate flex-1">{tc.tool_name}</span>
                        {tc.duration_ms > 0 && <span className="text-text-muted">{formatDuration(tc.duration_ms)}</span>}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Section>

            <Section title={`Timeline (${traceBlocks.length})`}>
              <div className="space-y-0.5">
                {traceBlocks.slice(-36).map(b => (
                  <div key={b.id} className="flex items-center gap-2 py-0.5">
                    <BlockDot type={b.type} />
                    <span className="text-text-secondary truncate flex-1">
                      {b.type === 'user'
                        ? 'User'
                        : b.type === 'assistant'
                          ? 'Assistant'
                          : b.type === 'thinking'
                            ? 'Thinking'
                            : b.type === 'tool_call'
                              ? b.tool_name
                              : b.type === 'diff'
                                ? `Diff: ${b.path || ''}`
                                : b.type === 'error'
                                  ? 'Error'
                                  : b.type}
                    </span>
                    {b.ts && <span className="text-text-muted">{formatTime(b.ts)}</span>}
                  </div>
                ))}
              </div>
            </Section>
          </>
        )}

        {tab === 'Files' && (
          <Section title={`File Changes (${fileChanges.length})`}>
            {fileChanges.length === 0 ? (
              <p className="text-text-muted">No file changes</p>
            ) : (
              <div className="space-y-2">
                {fileChanges.map(fc => (
                  <div key={fc.id} className="rounded border border-border-soft overflow-hidden">
                    <div className="flex items-center justify-between gap-2 px-2.5 py-1 bg-bg-secondary text-[11px]">
                      <span className="font-mono text-text-primary truncate">{fc.path}</span>
                      <span className="text-text-muted">{fc.created_at ? new Date(fc.created_at).toLocaleTimeString() : ''}</span>
                    </div>
                    <pre className="bg-bg font-mono text-[11px] leading-5 overflow-x-auto max-h-96 overflow-y-auto p-2">
                      {fc.diff}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === 'Terminal' && (
          <Section title={`Terminal (${terminalRows.length})`}>
            {terminalRows.length === 0 ? (
              <p className="text-text-muted">No terminal output</p>
            ) : (
              <pre className="text-[11px] text-text-secondary bg-bg border border-border-soft rounded p-2 overflow-x-auto max-h-[60vh] overflow-y-auto whitespace-pre-wrap">
                {terminalRows.map(r => r.text).join('')}
              </pre>
            )}
          </Section>
        )}

        {tab === 'Context' && (
          <Section title={`Context (${contextItems.length})`}>
            {contextItems.length === 0 ? (
              <p className="text-text-muted">No context items</p>
            ) : (
              <div className="space-y-1">
                {contextItems.map(ci => (
                  <div key={ci.id} className="flex items-center gap-2 py-1 px-2 rounded border border-border-soft bg-bg/40">
                    <span className="text-text-muted uppercase text-[10px]">{ci.kind}</span>
                    <span className="text-text-secondary truncate flex-1">{truncate(ci.title, 60)}</span>
                    <button
                      className={cn(
                        'px-2 py-0.5 rounded border text-[11px] transition-colors',
                        ci.pinned ? 'border-border-soft bg-bg text-text-primary' : 'border-border-soft bg-bg-secondary text-text-muted hover:text-text-secondary'
                      )}
                      onClick={async () => {
                        if (!sessionId) return
                        if (ci.pinned) await unpinContext(sessionId, ci.id)
                        else await pinContext(sessionId, ci.id)
                        refreshTabData('Context').catch(() => {})
                      }}
                      title={ci.pinned ? 'Unpin' : 'Pin'}
                    >
                      {ci.pinned ? 'Pinned' : 'Pin'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}

        {tab === 'Permissions' && (
          <Section title={`Pending (${pendingPerms.length})`}>
            {pendingPerms.length === 0 ? (
              <p className="text-text-muted">No pending requests</p>
            ) : (
              <div className="space-y-2">
                {pendingPerms.map(pr => (
                  <div key={pr.id} className="rounded border border-border-soft bg-bg/40 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-mono text-text-primary truncate">{pr.tool_name}</div>
                        <div className="text-text-muted text-[10px] truncate">{pr.id}</div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <PermBtn onClick={() => act(pr.id, 'approved', 'once')}>Once</PermBtn>
                        <PermBtn onClick={() => act(pr.id, 'approved', 'session')}>Session</PermBtn>
                        <PermBtn onClick={() => act(pr.id, 'approved', 'always')}>Always</PermBtn>
                        <PermBtn danger onClick={() => act(pr.id, 'denied', 'once')}>Deny</PermBtn>
                      </div>
                    </div>
                    {pr.input && (
                      <pre className="mt-2 text-[11px] text-text-secondary bg-bg-secondary/35 border border-border-soft rounded p-2 overflow-x-auto max-h-48 overflow-y-auto">
                        {JSON.stringify(pr.input, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}
      </div>
    </div>
  )

  async function act(requestId, status2, scope2) {
    await resolvePermission(requestId, status2, scope2)
    refreshTabData('Permissions').catch(() => {})
  }
}

function PermBtn({ children, onClick, danger }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-2 py-1 rounded border text-[11px] transition-colors',
        danger
          ? 'border-border-soft bg-bg-secondary text-status-error hover:border-border'
          : 'border-border-soft bg-bg-secondary text-text-muted hover:text-text-secondary hover:border-border'
      )}
    >
      {children}
    </button>
  )
}

function Section({ title, children }) {
  return (
    <div className="pb-2 border-b border-border-soft last:border-b-0">
      <h4 className="text-[10px] text-text-muted uppercase tracking-wide mb-1.5">{title}</h4>
      {children}
    </div>
  )
}

function InfoRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-text-muted">{label}</span>
      <span className={cn('text-text-secondary', mono && 'font-mono text-[10px]')}>{value}</span>
    </div>
  )
}

function BlockDot({ type }) {
  const colors = {
    user: 'bg-text-muted',
    assistant: 'bg-text-muted',
    thinking: 'bg-text-muted',
    tool_call: 'bg-status-pending',
    diff: 'bg-text-muted',
    error: 'bg-status-error',
  }
  return <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', colors[type] || 'bg-text-muted')} />
}
