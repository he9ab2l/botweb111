import { ShieldAlert, X } from 'lucide-react'
import { cn } from '../lib/utils'

export default function PermissionModal({ request, onApprove, onDeny, onClose }) {
  if (!request) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close permission modal"
      />

      <div className="relative w-[min(720px,95vw)] rounded-xl border border-border-soft bg-bg shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border-soft bg-bg-secondary/60">
          <div className="flex items-center gap-2">
            <ShieldAlert size={16} className="text-text-muted" />
            <div>
              <div className="text-sm text-text-primary">Tool Permission</div>
              <div className="text-[11px] text-text-muted font-mono">{request.tool_name}</div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded border border-transparent text-text-muted hover:text-text-secondary hover:border-border-soft transition-colors"
            title="Close"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <p className="text-[13px] text-text-secondary">
            fanfan wants to run a tool. Approve to continue.
          </p>

          {request.input && (
            <div>
              <div className="text-[10px] text-text-muted uppercase tracking-wide mb-1">Input</div>
              <pre className="text-[11px] text-text-secondary bg-bg-secondary/35 border border-border-soft rounded p-2 overflow-x-auto max-h-64 overflow-y-auto">
                {JSON.stringify(request.input, null, 2)}
              </pre>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <ActionBtn onClick={() => onApprove('once')} primary>
              Allow Once
            </ActionBtn>
            <ActionBtn onClick={() => onApprove('session')}>
              Allow Session
            </ActionBtn>
            <ActionBtn onClick={() => onApprove('always')}>
              Always Allow
            </ActionBtn>
            <ActionBtn onClick={onDeny} danger>
              Deny
            </ActionBtn>
          </div>

          <p className="text-[11px] text-text-muted">
            Tip: "Allow Once" is safest. "Always Allow" updates global tool policy.
          </p>
        </div>
      </div>
    </div>
  )
}

function ActionBtn({ children, onClick, primary, danger }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-3 py-2 rounded border text-[12px] transition-colors',
        primary && 'bg-btn-primary text-white border-transparent hover:bg-btn-primary-hover',
        danger && 'bg-bg-secondary text-status-error border-border-soft hover:border-border',
        !primary && !danger && 'bg-bg-secondary text-text-secondary border-border-soft hover:border-border hover:text-text-primary'
      )}
    >
      {children}
    </button>
  )
}

