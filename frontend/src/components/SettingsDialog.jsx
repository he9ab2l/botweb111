import { useState, useEffect, useCallback } from 'react'
import { X, Settings, Plug, Cpu, Eye, EyeOff, Check, Loader2, AlertCircle, Trash2 } from 'lucide-react'
import { cn } from '../lib/utils'
import { listProviders, updateProvider, disconnectProvider, listModels, setModel } from '../lib/api'

/**
 * SettingsDialog — Provider & model configuration UI.
 *
 * Tabs: Providers | Models
 * Providers tab: list all known providers, connect/disconnect, edit API key.
 * Models tab: list available models, select active model.
 * Inspired by OpenCode's settings dialog.
 */

const TABS = [
  { id: 'providers', label: 'Providers', icon: Plug },
  { id: 'models', label: 'Models', icon: Cpu },
]

export default function SettingsDialog({ open, onClose }) {
  const [tab, setTab] = useState('providers')

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-[60] bg-black/20" onClick={onClose} />

      {/* Dialog */}
      <div className="fixed inset-0 z-[61] flex items-center justify-center p-4">
        <div
          className="bg-bg rounded-lg border border-border shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col animate-fade-in"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border-soft">
            <div className="flex items-center gap-2">
              <Settings size={16} className="text-text-muted" />
              <span className="text-sm font-medium text-text-primary">Settings</span>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-secondary transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-border-soft px-4">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors',
                  tab === t.id
                    ? 'border-accent-blue text-text-primary'
                    : 'border-transparent text-text-muted hover:text-text-secondary'
                )}
              >
                <t.icon size={13} />
                {t.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {tab === 'providers' && <ProvidersTab />}
            {tab === 'models' && <ModelsTab />}
          </div>
        </div>
      </div>
    </>
  )
}

/* ────────────────── Providers Tab ────────────────── */

function ProvidersTab() {
  const [providers, setProviders] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [editingId, setEditingId] = useState(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await listProviders()
      setProviders(data.providers || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !providers) {
    return (
      <div className="flex items-center justify-center py-8 text-text-muted">
        <Loader2 size={16} className="animate-spin mr-2" />
        Loading providers...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 py-4 text-status-error text-sm">
        <AlertCircle size={14} />
        {error}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-muted mb-3">
        Connect AI providers by adding your API key. Models from connected providers will appear in the Models tab.
      </p>

      {(providers || []).map(p => (
        <ProviderRow
          key={p.id}
          provider={p}
          isEditing={editingId === p.id}
          onEdit={() => setEditingId(editingId === p.id ? null : p.id)}
          onRefresh={load}
        />
      ))}
    </div>
  )
}

function ProviderRow({ provider, isEditing, onEdit, onRefresh }) {
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [error, setError] = useState(null)

  const handleSave = async () => {
    if (!apiKey.trim()) return
    try {
      setSaving(true)
      setError(null)
      await updateProvider(provider.id, {
        api_key: apiKey.trim(),
        api_base: apiBase.trim() || null,
      })
      setApiKey('')
      setApiBase('')
      onEdit() // close
      await onRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDisconnect = async () => {
    try {
      setRemoving(true)
      setError(null)
      await disconnectProvider(provider.id)
      await onRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setRemoving(false)
    }
  }

  return (
    <div className="border border-border-soft rounded-lg overflow-hidden">
      {/* Summary row */}
      <div
        className="flex items-center justify-between px-3 py-2.5 bg-bg hover:bg-bg-secondary/40 transition-colors cursor-pointer"
        onClick={onEdit}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              'w-2 h-2 rounded-full shrink-0',
              provider.connected ? 'bg-status-success' : 'bg-bg-tertiary'
            )}
          />
          <span className="text-sm font-medium text-text-primary truncate">
            {provider.name || provider.id}
          </span>
        </div>
        <span className={cn(
          'text-xs shrink-0',
          provider.connected ? 'text-status-success' : 'text-text-muted'
        )}>
          {provider.connected ? 'Connected' : 'Not connected'}
        </span>
      </div>

      {/* Expanded edit form */}
      {isEditing && (
        <div className="px-3 py-3 border-t border-border-soft bg-bg-secondary/30 space-y-2.5">
          {provider.connected && (
            <div className="flex items-center justify-between text-xs text-text-secondary">
              <span>API Key: ****{provider.key_hint || ''}</span>
              <button
                onClick={handleDisconnect}
                disabled={removing}
                className="flex items-center gap-1 text-status-error hover:underline disabled:opacity-50"
              >
                {removing ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                Disconnect
              </button>
            </div>
          )}

          <div>
            <label className="block text-xs text-text-muted mb-1">
              {provider.connected ? 'Update API Key' : 'API Key'}
            </label>
            <div className="flex items-center gap-1">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder={provider.connected ? 'Enter new key to update' : 'sk-...'}
                className="flex-1 px-2.5 py-1.5 rounded border border-border-soft bg-bg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
              />
              <button
                onClick={() => setShowKey(v => !v)}
                className="p-1.5 rounded text-text-muted hover:text-text-primary hover:bg-bg-secondary transition-colors"
                title={showKey ? 'Hide' : 'Show'}
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs text-text-muted mb-1">
              Base URL <span className="text-text-muted">(optional)</span>
            </label>
            <input
              type="text"
              value={apiBase}
              onChange={e => setApiBase(e.target.value)}
              placeholder={provider.default_base_url || 'https://api.example.com/v1'}
              className="w-full px-2.5 py-1.5 rounded border border-border-soft bg-bg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
            />
          </div>

          {error && (
            <div className="flex items-center gap-1.5 text-xs text-status-error">
              <AlertCircle size={12} />
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onEdit}
              className="px-3 py-1.5 rounded text-xs text-text-secondary hover:text-text-primary hover:bg-bg-secondary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!apiKey.trim() || saving}
              className={cn(
                'flex items-center gap-1 px-3 py-1.5 rounded text-xs transition-colors',
                apiKey.trim() && !saving
                  ? 'bg-btn-primary text-white hover:bg-btn-primary-hover'
                  : 'bg-bg-tertiary text-text-muted cursor-not-allowed'
              )}
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              {provider.connected ? 'Update' : 'Connect'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ────────────────── Models Tab ────────────────── */

function ModelsTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [setting, setSetting] = useState(null) // model id currently being set

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const d = await listModels()
      setData(d)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSelect = async (modelId) => {
    try {
      setSetting(modelId)
      await setModel(modelId)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setSetting(null)
    }
  }

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-8 text-text-muted">
        <Loader2 size={16} className="animate-spin mr-2" />
        Loading models...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 py-4 text-status-error text-sm">
        <AlertCircle size={14} />
        {error}
      </div>
    )
  }

  const currentModel = data?.current
  const models = data?.models || []

  // Group by provider
  const byProvider = {}
  for (const m of models) {
    const key = m.provider || 'unknown'
    if (!byProvider[key]) byProvider[key] = []
    byProvider[key].push(m)
  }

  const providerNames = Object.keys(byProvider).sort()

  if (providerNames.length === 0) {
    return (
      <div className="text-center py-8">
        <Cpu size={24} className="mx-auto text-text-muted mb-2" />
        <p className="text-sm text-text-secondary">No models available</p>
        <p className="text-xs text-text-muted mt-1">Connect a provider first to see available models.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {currentModel && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-secondary/60 border border-border-soft">
          <Cpu size={13} className="text-accent-blue shrink-0" />
          <span className="text-xs text-text-secondary">Active:</span>
          <span className="text-xs font-medium text-text-primary truncate">{currentModel}</span>
        </div>
      )}

      {providerNames.map(prov => (
        <div key={prov}>
          <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-1.5 px-1">
            {prov}
          </h3>
          <div className="space-y-0.5">
            {byProvider[prov].map(m => {
              const isActive = m.id === currentModel || m.model === currentModel
              const isSettingThis = setting === (m.id || m.model)

              return (
                <button
                  key={m.id || m.model}
                  onClick={() => !isActive && handleSelect(m.id || m.model)}
                  disabled={isActive || isSettingThis}
                  className={cn(
                    'w-full flex items-center justify-between px-3 py-2 rounded text-left transition-colors',
                    isActive
                      ? 'bg-accent-blue/5 border border-accent-blue/20'
                      : 'hover:bg-bg-secondary/60 border border-transparent'
                  )}
                >
                  <span className={cn(
                    'text-sm truncate',
                    isActive ? 'text-accent-blue font-medium' : 'text-text-primary'
                  )}>
                    {m.name || m.label || m.model || m.id}
                  </span>
                  {isSettingThis && <Loader2 size={13} className="animate-spin text-text-muted shrink-0" />}
                  {isActive && !isSettingThis && <Check size={13} className="text-accent-blue shrink-0" />}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
