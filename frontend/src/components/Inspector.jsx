import { useEffect, useMemo, useState } from 'react'
import { Clock, RefreshCw, Wifi, WifiOff, ShieldAlert, FileCode, Layers, Fingerprint } from 'lucide-react'
import { cn, formatDuration, formatTime, truncate } from '../lib/utils'
import {
  fsTree,
  fsRead,
  fsVersions,
  fsGetVersion,
  fsRollback,
  listContext,
  listFileChanges,
  listPendingPermissions,
  pinContext,
  resolvePermission,
  unpinContext,
} from '../lib/api'

const TABS = ['Trace', 'Files', 'Context', 'Permissions']

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
  const [contextItems, setContextItems] = useState([])
  const [pendingPerms, setPendingPerms] = useState([])
  const [loading, setLoading] = useState(false)

  // FS browser (tree + versions + rollback)
  const [fsIndex, setFsIndex] = useState(null) // { root, items, truncated }
  const [fsFilter, setFsFilter] = useState('')
  const [fsSelectedPath, setFsSelectedPath] = useState('')
  const [fsFile, setFsFile] = useState(null) // { path, size, mtime, truncated, content }
  const [fsFileVersions, setFsFileVersions] = useState([])
  const [fsPreview, setFsPreview] = useState(null) // { id, idx, note, created_at, truncated, content }
  const [fsBusy, setFsBusy] = useState(false)
  const [fsError, setFsError] = useState('')

  const toolCount = toolCalls.length
  const errorCount = toolCalls.filter(t => t.status === 'error').length
  const totalDuration = toolCalls.reduce((acc, t) => acc + (t.duration_ms || 0), 0)

  const traceBlocks = useMemo(() => blocks.slice(-100), [blocks])

  const filteredFiles = useMemo(() => {
    const items = fsIndex?.items || []
    const q = (fsFilter || '').trim().toLowerCase()
    if (!q) return items
    return items.filter(i => String(i.path || '').toLowerCase().includes(q))
  }, [fsIndex, fsFilter])

  async function refreshTabData(activeTab = tab) {
    if (!sessionId) return
    setLoading(true)
    try {
      if (activeTab === 'Files') {
        setFsError('')
        try {
          const [tree, changes] = await Promise.all([
            fsTree(sessionId),
            listFileChanges(sessionId),
          ])
          setFsIndex(tree)
          setFileChanges(changes)
        } catch (e) {
          setFsError(e?.message || String(e))
        }
      }
      if (activeTab === 'Context') setContextItems(await listContext(sessionId))
      if (activeTab === 'Permissions') setPendingPerms(await listPendingPermissions(sessionId))
    } finally {
      setLoading(false)
    }
  }

  async function refreshSelectedFile(path = fsSelectedPath) {
    if (!sessionId || !path) return
    setFsBusy(true)
    setFsError('')
    try {
      const [file, versions] = await Promise.all([
        fsRead(sessionId, path),
        fsVersions(sessionId, path),
      ])
      setFsFile(file)
      setFsFileVersions(versions)
    } catch (e) {
      setFsError(e?.message || String(e))
    } finally {
      setFsBusy(false)
    }
  }

  useEffect(() => {
    // Reset per-session inspector data
    setFileChanges([])
    setContextItems([])
    setPendingPerms([])

    setFsIndex(null)
    setFsFilter('')
    setFsSelectedPath('')
    setFsFile(null)
    setFsFileVersions([])
    setFsPreview(null)
    setFsBusy(false)
    setFsError('')

    if (!sessionId) return
    refreshTabData(tab).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  useEffect(() => {
    if (!sessionId) return
    refreshTabData(tab).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  useEffect(() => {
    if (!sessionId) return
    if (tab !== 'Files') return
    if (!fsSelectedPath) return
    refreshSelectedFile(fsSelectedPath).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, tab, fsSelectedPath])

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
          <>
            <Section title="Workspace">
              <div className="flex items-center gap-2">
                <input
                  value={fsFilter}
                  onChange={e => setFsFilter(e.target.value)}
                  placeholder="Filter files"
                  className={cn(
                    'flex-1 px-2 py-1 rounded border border-border-soft bg-bg text-text-secondary',
                    'placeholder:text-text-muted outline-none focus:border-border'
                  )}
                />
                <button
                  onClick={() => {
                    setFsPreview(null)
                    refreshTabData('Files').catch(() => {})
                  }}
                  className={cn(
                    'px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted',
                    'hover:text-text-secondary hover:border-border transition-colors'
                  )}
                  title="Reload file tree"
                  disabled={!sessionId}
                >
                  Reload
                </button>
              </div>

              {fsError && (
                <div className="mt-2 text-status-error">{fsError}</div>
              )}

              <div className="mt-2 rounded border border-border-soft overflow-hidden">
                <div className="max-h-56 overflow-y-auto">
                  {filteredFiles.length === 0 ? (
                    <div className="px-2.5 py-2 text-text-muted">No files</div>
                  ) : (
                    filteredFiles.slice(0, 400).map(i => (
                      <button
                        key={i.path}
                        onClick={() => {
                          setFsSelectedPath(i.path)
                          setFsPreview(null)
                        }}
                        className={cn(
                          'w-full text-left px-2.5 py-1 border-b border-border-soft last:border-b-0',
                          'hover:bg-bg/40 transition-colors',
                          fsSelectedPath === i.path ? 'bg-bg/60' : 'bg-bg-secondary/20'
                        )}
                        title={i.path}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-text-primary truncate">{i.path}</span>
                          <span className="text-text-muted shrink-0">{formatBytes(i.size || 0)}</span>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>

              {fsIndex?.truncated && (
                <div className="mt-2 text-text-muted">File list truncated.</div>
              )}
              {filteredFiles.length > 400 && (
                <div className="mt-2 text-text-muted">Showing first 400 matches. Narrow your filter.</div>
              )}
            </Section>

            <Section title="File">
              {!fsSelectedPath ? (
                <p className="text-text-muted">Select a file to preview and manage versions.</p>
              ) : (
                <>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-text-primary truncate">{fsSelectedPath}</span>
                    <button
                      onClick={() => refreshSelectedFile().catch(() => {})}
                      className={cn(
                        'px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted',
                        'hover:text-text-secondary hover:border-border transition-colors',
                        fsBusy && 'opacity-60 cursor-wait'
                      )}
                      title="Reload file"
                      disabled={fsBusy}
                    >
                      Reload
                    </button>
                  </div>

                  {fsFile && (
                    <>
                      <div className="mt-1 text-text-muted text-[10px] flex items-center justify-between">
                        <span>{formatBytes(fsFile.size || 0)}</span>
                        <span>{fsFile.truncated ? 'truncated' : ''}</span>
                      </div>
                      <pre className="mt-2 bg-bg font-mono text-[11px] leading-5 overflow-x-auto max-h-80 overflow-y-auto p-2 border border-border-soft rounded">
                        {fsFile.content || ''}
                      </pre>
                    </>
                  )}
                </>
              )}
            </Section>

            <Section title={`Versions (${fsFileVersions.length})`}>
              {!fsSelectedPath ? (
                <p className="text-text-muted">Select a file first.</p>
              ) : fsBusy && fsFileVersions.length === 0 ? (
                <p className="text-text-muted">Loading...</p>
              ) : fsFileVersions.length === 0 ? (
                <p className="text-text-muted">No versions yet. Versions are captured when tools modify a file.</p>
              ) : (
                <div className="space-y-1">
                  {fsFileVersions.map(v => (
                    <div key={v.id} className="rounded border border-border-soft bg-bg/40 px-2 py-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-text-primary shrink-0">v{v.idx}</span>
                        <span className="text-text-muted truncate flex-1">{v.note || ''}</span>
                        <button
                          className="px-2 py-0.5 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-secondary hover:border-border transition-colors"
                          onClick={async () => {
                            if (!sessionId) return
                            try {
                              const data = await fsGetVersion(sessionId, v.id)
                              setFsPreview(data)
                            } catch (e) {
                              setFsError(e?.message || String(e))
                            }
                          }}
                          title="Preview version"
                        >
                          View
                        </button>
                        <button
                          className="px-2 py-0.5 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-secondary hover:border-border transition-colors"
                          onClick={async () => {
                            if (!sessionId) return
                            if (!fsSelectedPath) return
                            const ok = window.confirm(`Rollback ${fsSelectedPath} to v${v.idx}?`)
                            if (!ok) return
                            setFsBusy(true)
                            setFsError('')
                            try {
                              await fsRollback(sessionId, fsSelectedPath, v.id)
                              setFsPreview(null)
                              await refreshSelectedFile(fsSelectedPath)
                              setFileChanges(await listFileChanges(sessionId))
                            } catch (e) {
                              setFsError(e?.message || String(e))
                            } finally {
                              setFsBusy(false)
                            }
                          }}
                          title="Rollback to this version"
                        >
                          Rollback
                        </button>
                      </div>
                      <div className="text-[10px] text-text-muted mt-0.5">
                        {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {fsPreview && (
              <Section title={`Preview v${fsPreview.idx} (${truncate(fsPreview.note || '', 20) || 'snapshot'})`}>
                <div className="text-[10px] text-text-muted flex items-center justify-between">
                  <span className="font-mono truncate">{fsPreview.path}</span>
                  <span>{fsPreview.truncated ? 'truncated' : ''}</span>
                </div>
                <pre className="mt-2 bg-bg font-mono text-[11px] leading-5 overflow-x-auto max-h-80 overflow-y-auto p-2 border border-border-soft rounded">
                  {fsPreview.content || ''}
                </pre>
              </Section>
            )}

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
          </>
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

function formatBytes(n) {
  const num = Number(n || 0)
  if (!Number.isFinite(num) || num <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = num
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  const fixed = i === 0 ? 0 : i === 1 ? 1 : 2
  return `${v.toFixed(fixed)} ${units[i]}`
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
