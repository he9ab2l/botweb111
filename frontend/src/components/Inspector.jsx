import { Clock, Wifi, WifiOff } from 'lucide-react'
import { cn, formatDuration, formatTime } from '../lib/utils'

export default function Inspector({
  toolCalls,
  usage,
  stopReason,
  runId,
  connectionStatus,
  status,
  blocks,
}) {
  const toolCount = toolCalls.length
  const errorCount = toolCalls.filter(t => t.status === 'error').length
  const totalDuration = toolCalls.reduce((acc, t) => acc + (t.duration_ms || 0), 0)

  return (
    <div className="flex flex-col h-full bg-bg-secondary border-l border-border overflow-hidden">
      <div className="px-3 py-2 border-b border-border-soft">
        <h3 className="text-[10px] text-text-muted uppercase tracking-wide">Inspector</h3>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 text-[11px] space-y-3">
        <Section title="Connection">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full',
                connectionStatus === 'connected'
                  ? 'bg-status-success'
                  : connectionStatus === 'connecting'
                    ? 'bg-status-pending animate-pulse-dot'
                    : 'bg-status-error'
              )}
            />
            {connectionStatus === 'connected' ? (
              <Wifi size={12} className="text-text-muted" />
            ) : (
              <WifiOff size={12} className="text-text-muted" />
            )}
            <span className="text-text-secondary">{connectionStatus}</span>
          </div>
        </Section>

        {runId && (
          <Section title="Run">
            <InfoRow label="ID" value={runId} mono />
            <InfoRow label="Status" value={status} />
            {stopReason && <InfoRow label="Stop" value={stopReason} />}
          </Section>
        )}

        {usage && (
          <Section title="Tokens">
            {usage.prompt_tokens != null && <InfoRow label="Prompt" value={usage.prompt_tokens.toLocaleString()} />}
            {usage.completion_tokens != null && <InfoRow label="Completion" value={usage.completion_tokens.toLocaleString()} />}
            {usage.total_tokens != null && <InfoRow label="Total" value={usage.total_tokens.toLocaleString()} />}
          </Section>
        )}

        <Section title={`Tools (${toolCount})`}>
          {toolCount === 0 ? (
            <p className="text-text-muted">No tool calls</p>
          ) : (
            <>
              <div className="flex items-center gap-3 mb-1.5 text-text-muted">
                {errorCount > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-status-error" />
                    {errorCount} error{errorCount !== 1 ? 's' : ''}
                  </span>
                )}
                {totalDuration > 0 && (
                  <span className="flex items-center gap-1">
                    <Clock size={10} />
                    {formatDuration(totalDuration)}
                  </span>
                )}
              </div>

              <div className="space-y-0.5">
                {toolCalls.map(tc => (
                  <div key={tc.tool_call_id} className="flex items-center gap-2 py-1 px-2 rounded border border-border-soft bg-bg/40">
                    <span
                      className={cn(
                        'w-1.5 h-1.5 rounded-full shrink-0',
                        tc.status === 'completed'
                          ? 'bg-status-success'
                          : tc.status === 'error'
                            ? 'bg-status-error'
                            : tc.status === 'running'
                              ? 'bg-status-running animate-pulse-dot'
                              : 'bg-status-pending animate-pulse-dot'
                      )}
                    />
                    <span className="font-mono text-text-primary truncate flex-1">{tc.tool_name}</span>
                    {tc.duration_ms > 0 && <span className="text-text-muted">{formatDuration(tc.duration_ms)}</span>}
                  </div>
                ))}
              </div>
            </>
          )}
        </Section>

        <Section title={`Timeline (${blocks.length})`}>
          <div className="space-y-0.5">
            {blocks.slice(-24).map(b => (
              <div key={b.id} className="flex items-center gap-2 py-0.5">
                <BlockDot type={b.type} />
                <span className="text-text-secondary truncate flex-1">
                  {b.type === 'user'
                    ? 'User'
                    : b.type === 'assistant'
                      ? 'Assistant'
                      : b.type === 'thinking'
                        ? 'Thinking'
                        : b.type === 'tool_use'
                          ? b.tool_name
                          : b.type === 'patch'
                            ? 'Patch'
                            : b.type === 'error'
                              ? 'Error'
                              : b.type}
                </span>
                {b.ts && <span className="text-text-muted">{formatTime(b.ts)}</span>}
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="pb-2 border-b border-border-soft last:border-b-0">
      <h4 className="text-[10px] text-text-muted uppercase tracking-wide mb-1.5">{title}</h4>
      {children}
    </div>
  )
}

function InfoRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-text-muted">{label}</span>
      <span className={cn('text-text-secondary', mono && 'font-mono text-[10px]')}>{value}</span>
    </div>
  )
}

function BlockDot({ type }) {
  const colors = {
    user: 'bg-text-muted',
    assistant: 'bg-text-muted',
    thinking: 'bg-text-muted',
    tool_use: 'bg-status-pending',
    patch: 'bg-text-muted',
    error: 'bg-status-error',
  }
  return <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', colors[type] || 'bg-text-muted')} />
}
