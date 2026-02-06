import { useState } from 'react'
import { Wrench, ChevronDown, ChevronRight, Clock } from 'lucide-react'
import { cn, formatDuration, truncate } from '../lib/utils'

/**
 * Status dot colors — v3 uses status-* tokens
 * Small dots only, never large areas
 */
const STATUS_DOT = {
  pending:   'bg-status-pending animate-pulse-dot',
  running:   'bg-status-running animate-pulse-dot',
  completed: 'bg-status-success',
  error:     'bg-status-error',
}

export default function ToolUseBlock({ block }) {
  const [open, setOpen] = useState(false)

  const statusDot = STATUS_DOT[block.status] || STATUS_DOT.pending
  const isComplete = block.status === 'completed' || block.status === 'error'
  const hasOutput = block.output || block.error

  // Build summary from first input param
  const inputSummary = (() => {
    if (!block.input) return ''
    const keys = Object.keys(block.input)
    if (keys.length === 0) return ''
    const first = block.input[keys[0]]
    if (typeof first === 'string') return truncate(first, 60)
    return truncate(JSON.stringify(first), 60)
  })()

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
        <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', statusDot)} />

        <Wrench size={11} className="text-text-muted shrink-0" />

        <span className="text-text-primary font-mono text-[11px]">
          {block.tool_name}
        </span>

        {inputSummary && (
          <span className="text-text-muted text-[11px] truncate hidden sm:inline">
            {inputSummary}
          </span>
        )}

        <span className="ml-auto flex items-center gap-2">
          {block.duration_ms > 0 && (
            <span className="flex items-center gap-1 text-text-muted text-[11px]">
              <Clock size={10} />
              {formatDuration(block.duration_ms)}
            </span>
          )}
          <span className="text-text-muted">
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        </span>
      </button>

      {open && (
        <div className="mt-1 ml-3 border-l border-border-soft pl-2.5 space-y-1.5">
          {block.input && Object.keys(block.input).length > 0 && (
            <div>
              <span className="text-[10px] text-text-muted block mb-0.5">Input</span>
              <pre className="text-[11px] text-text-secondary bg-bg-secondary/35 border border-border-soft rounded p-2 overflow-x-auto max-h-48 overflow-y-auto">
                {JSON.stringify(block.input, null, 2)}
              </pre>
            </div>
          )}

          {block.output && (
            <div>
              <span className="text-[10px] text-text-muted block mb-0.5">Output</span>
              <pre className="text-[11px] text-text-secondary bg-bg-secondary/35 border border-border-soft rounded p-2 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">
                {typeof block.output === 'string' ? block.output : JSON.stringify(block.output, null, 2)}
              </pre>
            </div>
          )}

          {block.error && (
            <div>
              <span className="text-[10px] text-text-muted flex items-center gap-1 mb-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-status-error" />
                Error
              </span>
              <pre className="text-[11px] text-text-secondary bg-bg-secondary/35 border border-border-soft rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {block.error}
              </pre>
            </div>
          )}

          {!isComplete && !hasOutput && (
            <div className="flex items-center gap-2 py-0.5 text-[11px] text-text-muted">
              <span className={cn('w-1.5 h-1.5 rounded-full', statusDot)} />
              Running...
            </div>
          )}
        </div>
      )}
    </div>
  )
}
