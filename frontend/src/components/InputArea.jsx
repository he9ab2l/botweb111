import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Square } from 'lucide-react'
import { cn } from '../lib/utils'

/**
 * InputArea — v3
 *
 * Auto-resize textarea, Enter to send, Shift+Enter for newline.
 * Focus ring uses accent-blue. Stop button uses status-error.
 */
export default function InputArea({
  onSend,
  onCancel,
  isRunning,
  disabled,
  modelValue,
  modelOptions,
  onModelChange,
  onApplyModel,
  onClearModel,
  hasOverride,
  onOpenSettings,
}) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  // Auto-resize
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [text])

  // Focus on mount
  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  const handleSend = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
  }, [text, disabled, onSend])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="border-t border-border-soft bg-bg p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
      <div className="max-w-chat mx-auto">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isRunning ? 'Working...' : 'Send a message...'}
            disabled={disabled || isRunning}
            rows={1}
            className={cn(
              'flex-1 resize-none rounded border border-border-soft bg-bg-secondary px-3 py-2',
              'text-[13px] text-text-primary placeholder:text-text-muted',
              'focus:outline-none focus:border-accent-blue',
              'transition-colors min-h-[38px] max-h-[200px]',
              (disabled || isRunning) && 'opacity-50 cursor-not-allowed'
            )}
          />

          {isRunning ? (
            <button
              onClick={onCancel}
              className="shrink-0 flex items-center justify-center w-9 h-9 rounded border border-border-soft text-status-error hover:bg-bg-secondary transition-colors"
              title="Stop"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!text.trim() || disabled}
              className={cn(
                'shrink-0 flex items-center justify-center w-9 h-9 rounded transition-colors',
                text.trim() && !disabled
                  ? 'bg-btn-primary text-white hover:bg-btn-primary-hover'
                  : 'bg-bg-tertiary text-text-muted cursor-not-allowed'
              )}
              title="Send"
            >
              <Send size={14} />
            </button>
          )}
        </div>

        {onModelChange && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
            <span className="text-text-muted">Model</span>
            <input
              value={modelValue || ''}
              onChange={(e) => onModelChange(e.target.value)}
              placeholder="zai/glm-4.7"
              list="model-list"
              className="min-w-[180px] flex-1 px-2 py-1 rounded border border-border-soft bg-bg-secondary text-text-secondary font-mono"
            />
            <datalist id="model-list">
              {(modelOptions || []).map((m) => (
                <option value={m} key={m} />
              ))}
            </datalist>
            <button
              type="button"
              onClick={() => onApplyModel && onApplyModel()}
              className="px-2.5 py-1 rounded border border-border-soft bg-bg-secondary text-text-secondary hover:text-text-primary hover:border-border transition-colors"
              disabled={disabled || isRunning}
            >
              Use
            </button>
            {hasOverride && (
              <button
                type="button"
                onClick={() => onClearModel && onClearModel()}
                className="px-2.5 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-primary hover:border-border transition-colors"
                disabled={disabled || isRunning}
              >
                Clear
              </button>
            )}
            <button
              type="button"
              onClick={() => onOpenSettings && onOpenSettings()}
              className="px-2.5 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted hover:text-text-primary hover:border-border transition-colors"
            >
              Settings
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
