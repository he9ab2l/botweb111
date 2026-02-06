import { AlertTriangle } from 'lucide-react'
import { formatTime } from '../lib/utils'

export default function ErrorBlock({ block }) {
  return (
    <div className="flex gap-2.5 px-2.5 py-2 rounded border border-border-soft bg-bg-secondary/20 my-1">
      <AlertTriangle size={14} className="text-status-error shrink-0 mt-0.5" />
      <div className="min-w-0">
        {block.code && (
          <span className="text-[10px] font-mono text-text-muted block mb-1">{block.code}</span>
        )}
        <p className="text-xs text-text-secondary">{block.text}</p>
        {block.ts && (
          <span className="text-[10px] text-text-muted mt-1 block">{formatTime(block.ts)}</span>
        )}
      </div>
    </div>
  )
}
