import { useState } from 'react'
import { FileCode, ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '../lib/utils'

function DiffLine({ line }) {
  let cls = 'text-text-secondary'
  if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add'
  else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-del'
  else if (line.startsWith('@@')) cls = 'diff-hunk'

  return <div className={cn('px-2', cls)}>{line || ' '}</div>
}

/**
 * PatchBlock — v3 neutral styling
 *
 * Collapsible file change list with unified diff.
 * No green accent on header — uses border-border only.
 */
export default function PatchBlock({ block }) {
  const [open, setOpen] = useState(false)

  const files = block.files || []
  if (files.length === 0) return null

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
        <FileCode size={11} className="text-text-muted shrink-0" />
        <span className="text-text-secondary">
          {files.length} file{files.length !== 1 ? 's' : ''} changed
        </span>
        <span className="ml-auto text-text-muted">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
      </button>

      {open && (
        <div className="mt-1 space-y-1">
          {files.map((file, i) => (
            <div key={i} className="rounded border border-border-soft overflow-hidden">
              <div className="flex items-center gap-2 px-2.5 py-1 bg-bg-secondary text-[11px]">
                <FileCode size={11} className="text-text-muted" />
                <span className="text-text-primary font-mono text-[11px]">{file.path || 'unknown'}</span>
              </div>
              <div className="bg-bg font-mono text-[11px] leading-5 overflow-x-auto max-h-96 overflow-y-auto">
                {(file.diff || '').split('\n').map((line, j) => (
                  <DiffLine key={j} line={line} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
