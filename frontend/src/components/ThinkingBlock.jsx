import { useState } from 'react'
import { Brain, ChevronDown, ChevronRight } from 'lucide-react'
import { MarkdownContent } from './MessageBlock'
import { cn, formatDuration } from '../lib/utils'

export default function ThinkingBlock({ block }) {
  const [open, setOpen] = useState(false)
  const hasContent = block.text && block.text.trim().length > 0

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-2 w-full text-left px-2.5 py-1 rounded',
          'border border-border-soft bg-bg-secondary/25',
          'hover:border-border transition-colors text-[11px]'
        )}
      >
        <Brain size={12} className="text-text-muted shrink-0" />
        <span className="text-text-secondary">Thinking</span>
        {block.duration_ms > 0 && (
          <span className="text-text-muted text-[11px]">
            {formatDuration(block.duration_ms)}
          </span>
        )}
        <span className="ml-auto text-text-muted">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
      </button>

      {open && (
        <div className="mt-1 ml-4 px-2 py-1.5 text-xs text-text-secondary leading-relaxed border-l border-border-soft">
          {hasContent ? (
            <div className="prose text-[12px] text-text-secondary">
              <MarkdownContent text={block.text} />
            </div>
          ) : (
            <span className="text-text-muted italic text-[11px]">(empty)</span>
          )}
        </div>
      )}
    </div>
  )
}
