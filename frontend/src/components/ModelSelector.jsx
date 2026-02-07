import { useState, useEffect, useRef, useCallback } from 'react'
import { ChevronDown, Check, Loader2 } from 'lucide-react'
import { cn } from '../lib/utils'
import { listModels, setModel } from '../lib/api'

/**
 * ModelSelector — compact dropdown for quick model switching.
 *
 * Sits in the InputArea or header bar.
 * Loads models on open, shows current model, allows instant switching.
 */
export default function ModelSelector({ className }) {
  const [open, setOpen] = useState(false)
  const [models, setModels] = useState([])
  const [currentModel, setCurrentModel] = useState(null)
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState(null)
  const dropdownRef = useRef(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  // Load models on open
  const loadModels = useCallback(async () => {
    try {
      setLoading(true)
      const data = await listModels()
      setModels(data.models || [])
      setCurrentModel(data.current_model || data.current || null)
    } catch (err) {
      console.error('Failed to load models:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Load once on mount to show current model
    loadModels()
  }, [loadModels])

  const handleOpen = () => {
    setOpen(o => !o)
    if (!open) loadModels()
  }

  const handleSelect = async (modelId) => {
    if (modelId === currentModel) {
      setOpen(false)
      return
    }
    try {
      setSwitching(modelId)
      await setModel(modelId)
      setCurrentModel(modelId)
      setOpen(false)
    } catch (err) {
      console.error('Failed to set model:', err)
    } finally {
      setSwitching(null)
    }
  }

  // Short display name for button
  const displayName = currentModel
    ? currentModel.split('/').pop().replace(/^(gpt-|claude-|gemini-|deepseek-)/, (m) => m)
    : 'Model'

  return (
    <div ref={dropdownRef} className={cn('relative', className)}>
      {/* Trigger button */}
      <button
        onClick={handleOpen}
        className={cn(
          'flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors',
          'border border-border-soft text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
        )}
        title={currentModel || 'Select model'}
      >
        <span className="truncate max-w-[120px]">{displayName}</span>
        <ChevronDown size={12} className={cn('transition-transform', open && 'rotate-180')} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute bottom-full left-0 mb-1 w-64 max-h-[300px] overflow-y-auto bg-bg rounded-lg border border-border shadow-lg animate-fade-in z-50">
          {loading && models.length === 0 ? (
            <div className="flex items-center justify-center py-4 text-text-muted text-xs">
              <Loader2 size={14} className="animate-spin mr-1.5" />
              Loading...
            </div>
          ) : models.length === 0 ? (
            <div className="px-3 py-4 text-center text-xs text-text-muted">
              No models available. Connect a provider in Settings.
            </div>
          ) : (
            <div className="py-1">
              {models.map(m => {
                const id = m.id || m.model
                const isActive = id === currentModel
                const isSwitching = switching === id

                return (
                  <button
                    key={id}
                    onClick={() => handleSelect(id)}
                    disabled={isSwitching}
                    className={cn(
                      'w-full flex items-center justify-between px-3 py-1.5 text-left text-xs transition-colors',
                      isActive
                        ? 'bg-accent-blue/5 text-accent-blue'
                        : 'text-text-primary hover:bg-bg-secondary'
                    )}
                  >
                    <div className="flex flex-col min-w-0">
                      <span className="truncate font-medium">{m.name || m.label || m.model || id}</span>
                      {m.provider && (
                        <span className="text-[10px] text-text-muted truncate">{m.provider}</span>
                      )}
                    </div>
                    {isSwitching && <Loader2 size={12} className="animate-spin text-text-muted shrink-0" />}
                    {isActive && !isSwitching && <Check size={12} className="text-accent-blue shrink-0" />}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
