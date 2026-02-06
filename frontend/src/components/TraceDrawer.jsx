import { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import ThinkingBlock from './ThinkingBlock'
import ToolUseBlock from './ToolUseBlock'
import PatchBlock from './PatchBlock'
import { cn, formatDuration } from '../lib/utils'

export default function TraceDrawer({ details }) {
  const [open, setOpen] = useState(false)

  const stats = useMemo(() => {
    let thinkingCount = 0
    let thinkingMs = 0
    let toolCount = 0
    let toolMs = 0
    let errorCount = 0
    let patchCount = 0

    for (const d of details) {
      if (d.type === 'thinking') {
        thinkingCount++
        thinkingMs += d.duration_ms || 0
      } else if (d.type === 'tool_use') {
        toolCount++
        toolMs += d.duration_ms || 0
        if (d.status === 'error') errorCount++
      } else if (d.type === 'patch') {
        patchCount++
      }
    }

    return { thinkingCount, thinkingMs, toolCount, toolMs, errorCount, patchCount }
  }, [details])

  if (details.length === 0) return null

  const totalMs = stats.thinkingMs + stats.toolMs
  const parts = []
  if (stats.toolCount > 0) parts.push(`${stats.toolCount} tool${stats.toolCount !== 1 ? 's' : ''}`)
  if (stats.thinkingCount > 0) parts.push(`${stats.thinkingCount} thinking`)
  if (totalMs > 0) parts.push(formatDuration(totalMs))
  if (stats.errorCount > 0) parts.push(`${stats.errorCount} error${stats.errorCount !== 1 ? 's' : ''}`)
  if (parts.length === 0) parts.push('execution details')

  return (
    <div className="mt-1 mb-2">
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-2 text-[11px] text-text-muted',
          'px-2 py-1 rounded border border-border-soft',
          'hover:border-border hover:text-text-secondary transition-colors'
        )}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>{parts.join(' • ')}</span>
      </button>

      {open && (
        <div className="mt-1 space-y-1 pl-2 border-l border-border-soft ml-2">
          {details.map(d => {
            if (d.type === 'thinking') return <ThinkingBlock key={d.id} block={d} />
            if (d.type === 'tool_use') return <ToolUseBlock key={d.id} block={d} />
            if (d.type === 'patch') return <PatchBlock key={d.id} block={d} />
            return null
          })}
        </div>
      )}
    </div>
  )
}
