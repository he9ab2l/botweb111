import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Square } from 'lucide-react'
import { cn } from '../lib/utils'
import ModelSelector from './ModelSelector'

/**
 * InputArea — v3
 *
 * Auto-resize textarea, Enter to send, Shift+Enter for newline.
 * Focus ring uses accent-blue. Stop button uses status-error.
 * Includes ModelSelector for quick model switching.
 */
export default function InputArea({ onSend, onCancel, isRunning, disabled }) {
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
      <div className="max-w-chat mx-auto space-y-1.5">
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

        {/* Model selector row */}
        <div className="flex items-center">
          <ModelSelector />
        </div>
      </div>
    </div>
  )
}
