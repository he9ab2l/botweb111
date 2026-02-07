import { useState } from 'react'
import { FileText, Copy, Check, Pin } from 'lucide-react'
import { MarkdownContent } from './MessageBlock'
import { cn, copyToClipboard } from '../lib/utils'

export default function DocBlock({ title, path, content, loading, error, truncated, pinned, canPin, pinBusy, pinError, onTogglePin }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (!path) return
    const ok = await copyToClipboard(path)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="mb-4 rounded-lg border border-border-soft bg-bg-secondary/60">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border-soft">
        <div className="flex items-center gap-2 min-w-0">
          <FileText size={14} className="text-text-muted" />
          <div className="min-w-0">
            <div className="text-[12px] text-text-primary truncate">{title || path || 'Document'}</div>
            {path && <div className="text-[10px] text-text-muted font-mono truncate">{path}</div>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canPin && path && (
            <button
              onClick={onTogglePin}
              disabled={pinBusy}
              className={cn(
                'inline-flex items-center justify-center h-7 w-7 rounded border transition-colors',
                pinned
                  ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                  : 'border-border-soft text-text-muted hover:text-text-secondary hover:border-border',
                pinBusy && 'opacity-60 cursor-wait'
              )}
              title={pinned ? 'Unpin from session context' : 'Pin to session context'}
            >
              <Pin size={14} className={cn(pinned && 'rotate-45')} />
            </button>
          )}

          {path && (
            <button
              onClick={handleCopy}
              className={cn(
                'inline-flex items-center justify-center h-7 w-7 rounded border border-border-soft',
                'text-text-muted hover:text-text-secondary hover:border-border transition-colors'
              )}
              title="Copy path"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          )}
        </div>
      </div>

      <div className="px-3 py-3">
        {pinError && (
          <div className="text-[12px] text-status-error mb-2">{pinError}</div>
        )}
        {loading && (
          <div className="text-[12px] text-text-muted">Loading document...</div>
        )}
        {error && (
          <div className="text-[12px] text-status-error">{error}</div>
        )}
        {!loading && !error && (
          <div className="prose text-[13px] leading-[1.55] text-text-primary">
            <MarkdownContent text={content || ''} />
            {truncated && (
              <div className="text-[11px] text-text-muted mt-2">(Truncated)</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
