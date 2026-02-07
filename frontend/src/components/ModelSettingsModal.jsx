import { useEffect, useMemo, useState } from 'react'
import { KeyRound, Settings, X } from 'lucide-react'
import { cn } from '../lib/utils'
import { clearSessionModel, getConfig, getSessionModel, setSessionModel, updateConfig, getPermissionMode, setPermissionMode } from '../lib/api'

export default function ModelSettingsModal({ open, sessionId, onClose, onUpdated }) {
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [config, setConfig] = useState(null)
  const [sessionModel, setSessionModelInfo] = useState(null)

  const [chatModelInput, setChatModelInput] = useState('')

  const [permissionMode, setPermissionModeState] = useState('ask')
  const [permissionBusy, setPermissionBusy] = useState(false)

  const [glmKeyInput, setGlmKeyInput] = useState('')
  const [glmBaseInput, setGlmBaseInput] = useState('')

  const recommended = useMemo(() => {
    return (config?.recommended_models || []).filter(Boolean)
  }, [config])

  async function refresh() {
    setErr('')
    setLoading(true)
    try {
      const cfg = await getConfig()
      setConfig(cfg)
      setGlmBaseInput(cfg?.providers?.zhipu?.api_base || '')

      if (sessionId) {
        const sm = await getSessionModel(sessionId)
        setSessionModelInfo(sm)
        setChatModelInput(sm?.effective_model || cfg?.default_model || '')
      } else {
        setSessionModelInfo(null)
        setChatModelInput(cfg?.default_model || '')
      }

      const pm = await getPermissionMode()
      if (pm?.mode) setPermissionModeState(pm.mode)
    } catch (e) {
      setErr(e?.message || 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sessionId])

  if (!open) return null

  const glmConfigured = !!config?.providers?.zhipu?.configured

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close settings"
      />

      <div className="relative w-[min(760px,95vw)] rounded-xl border border-border-soft bg-bg shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border-soft bg-bg-secondary/60">
          <div className="flex items-center gap-2">
            <Settings size={16} className="text-text-muted" />
            <div>
              <div className="text-sm text-text-primary">Model & API Settings</div>
              <div className="text-[11px] text-text-muted">
                {sessionId ? (
                  <span className="font-mono">{sessionId}</span>
                ) : (
                  <span>Global</span>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded border border-transparent text-text-muted hover:text-text-secondary hover:border-border-soft transition-colors"
            title="Close"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-4 space-y-5">
          {err && (
            <div className="text-[12px] text-status-error border border-border-soft bg-bg-secondary/35 rounded px-3 py-2">
              {err}
            </div>
          )}

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] text-text-muted uppercase tracking-wide">Chat Model</div>
                <div className="text-[12px] text-text-secondary">
                  {sessionId ? (
                    <>
                      Effective: <span className="font-mono">{sessionModel?.effective_model || config?.default_model || '—'}</span>
                      {sessionModel?.override_model ? (
                        <span className="text-text-muted"> (override)</span>
                      ) : (
                        <span className="text-text-muted"> (default)</span>
                      )}
                    </>
                  ) : (
                    <>
                      Default: <span className="font-mono">{config?.default_model || '—'}</span>
                    </>
                  )}
                </div>
              </div>

              <button
                onClick={refresh}
                className={cn(
                  'px-2 py-1 rounded border border-border-soft text-[11px] text-text-muted hover:text-text-secondary hover:border-border transition-colors',
                  loading && 'opacity-60'
                )}
                disabled={loading}
              >
                Refresh
              </button>
            </div>

            <div>
              <input
                className="w-full px-3 py-2 rounded border border-border-soft bg-bg text-[12px] font-mono text-text-secondary focus:outline-none focus:ring-2 focus:ring-btn-primary/40"
                value={chatModelInput}
                onChange={(e) => setChatModelInput(e.target.value)}
                placeholder="e.g. zai/glm-4"
                list="model-list"
              />
              <datalist id="model-list">
                {recommended.map((m) => (
                  <option value={m} key={m} />
                ))}
              </datalist>
              <div className="mt-1 text-[11px] text-text-muted">
                GLM models should use <span className="font-mono">zai/</span> prefix (e.g. <span className="font-mono">zai/glm-4</span>).
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={async () => {
                  if (!sessionId) return
                  setErr('')
                  try {
                    const m = (chatModelInput || '').trim()
                    if (!m) throw new Error('Model is required')
                    await setSessionModel(sessionId, m)
                    await refresh()
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to set model')
                  }
                }}
                disabled={!sessionId || loading}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  sessionId
                    ? 'bg-btn-primary text-white border-transparent hover:bg-btn-primary-hover'
                    : 'bg-bg-secondary text-text-muted border-border-soft opacity-60'
                )}
                title={sessionId ? 'Use this model for the current chat' : 'Create/select a chat first'}
              >
                Use For This Chat
              </button>

              <button
                onClick={async () => {
                  if (!sessionId) return
                  setErr('')
                  try {
                    await clearSessionModel(sessionId)
                    await refresh()
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to clear override')
                  }
                }}
                disabled={!sessionId || loading}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  'bg-bg-secondary text-text-secondary border-border-soft hover:border-border hover:text-text-primary',
                  (!sessionId || loading) && 'opacity-60'
                )}
              >
                Clear Override
              </button>

              <button
                onClick={async () => {
                  setErr('')
                  try {
                    const m = (chatModelInput || '').trim()
                    if (!m) throw new Error('Default model is required')
                    await updateConfig({ default_model: m })
                    await refresh()
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to update default model')
                  }
                }}
                disabled={loading}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  'bg-bg-secondary text-text-secondary border-border-soft hover:border-border hover:text-text-primary',
                  loading && 'opacity-60'
                )}
                title="Set global default model"
              >
                Set As Default
              </button>
            </div>
          </section>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] text-text-muted uppercase tracking-wide">Permissions</div>
                <div className="text-[12px] text-text-secondary">
                  {permissionMode === 'allow' ? 'All tools run without prompts.' : permissionMode === 'custom' ? 'Custom per-tool policy.' : 'Ask before running tools.'}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={async () => {
                  setErr('')
                  setPermissionBusy(true)
                  try {
                    await setPermissionMode('ask')
                    setPermissionModeState('ask')
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to update permissions')
                  } finally {
                    setPermissionBusy(false)
                  }
                }}
                disabled={permissionBusy}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  permissionMode === 'ask'
                    ? 'bg-btn-primary text-white border-transparent hover:bg-btn-primary-hover'
                    : 'bg-bg-secondary text-text-secondary border-border-soft hover:border-border hover:text-text-primary'
                )}
              >
                Require Approval
              </button>

              <button
                onClick={async () => {
                  setErr('')
                  setPermissionBusy(true)
                  try {
                    await setPermissionMode('allow')
                    setPermissionModeState('allow')
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to update permissions')
                  } finally {
                    setPermissionBusy(false)
                  }
                }}
                disabled={permissionBusy}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  permissionMode === 'allow'
                    ? 'bg-btn-primary text-white border-transparent hover:bg-btn-primary-hover'
                    : 'bg-bg-secondary text-text-secondary border-border-soft hover:border-border hover:text-text-primary'
                )}
              >
                Allow All Tools
              </button>
            </div>

            <p className="text-[11px] text-text-muted">
              Require Approval is safer. Allow All skips prompts for read/write/search/fetch tools.
            </p>
          </section>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] text-text-muted uppercase tracking-wide">GLM (Z.ai) API</div>
                <div className="text-[12px] text-text-secondary flex items-center gap-2">
                  <span className={cn('inline-flex items-center gap-1', glmConfigured ? 'text-status-success' : 'text-text-muted')}>
                    <KeyRound size={12} />
                    {glmConfigured ? 'Configured' : 'Not configured'}
                  </span>
                  {config?.config_path && (
                    <span className="text-[11px] text-text-muted font-mono truncate max-w-[360px]">
                      {config.config_path}
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-2">
              <input
                className="w-full px-3 py-2 rounded border border-border-soft bg-bg text-[12px] font-mono text-text-secondary focus:outline-none focus:ring-2 focus:ring-btn-primary/40"
                value={glmKeyInput}
                onChange={(e) => setGlmKeyInput(e.target.value)}
                placeholder="Enter GLM API key (stored in ~/.nanobot/config.json)"
                type="password"
                autoComplete="off"
              />
              <input
                className="w-full px-3 py-2 rounded border border-border-soft bg-bg text-[12px] font-mono text-text-secondary focus:outline-none focus:ring-2 focus:ring-btn-primary/40"
                value={glmBaseInput}
                onChange={(e) => setGlmBaseInput(e.target.value)}
                placeholder="Optional api_base (leave empty for default)"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={async () => {
                  setErr('')
                  try {
                    const upd = {}
                    const key = (glmKeyInput || '').trim()
                    const base = (glmBaseInput || '').trim()
                    if (key) upd.api_key = key
                    // Allow clearing api_base via empty string
                    upd.api_base = base

                    await updateConfig({ providers: { zhipu: upd } })
                    setGlmKeyInput('')
                    await refresh()
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to update GLM settings')
                  }
                }}
                disabled={loading}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  'bg-btn-primary text-white border-transparent hover:bg-btn-primary-hover',
                  loading && 'opacity-60'
                )}
                title="Update GLM API key/base"
              >
                Save GLM Settings
              </button>

              <button
                onClick={async () => {
                  setErr('')
                  try {
                    await updateConfig({ providers: { zhipu: { api_key: '' } } })
                    setGlmKeyInput('')
                    await refresh()
                    onUpdated?.()
                  } catch (e) {
                    setErr(e?.message || 'Failed to clear GLM key')
                  }
                }}
                disabled={loading}
                className={cn(
                  'px-3 py-2 rounded border text-[12px] transition-colors',
                  'bg-bg-secondary text-text-secondary border-border-soft hover:border-border hover:text-text-primary',
                  loading && 'opacity-60'
                )}
              >
                Clear GLM Key
              </button>
            </div>

            <p className="text-[11px] text-text-muted">
              Tip: after setting the key, set model to <span className="font-mono">zai/glm-4</span> (default or per chat).
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
