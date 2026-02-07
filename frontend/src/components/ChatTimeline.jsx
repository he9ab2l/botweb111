import { useMemo } from 'react'
import MessageBlock from './MessageBlock'
import ThinkingBlock from './ThinkingBlock'
import ToolUseBlock from './ToolUseBlock'
import PatchBlock from './PatchBlock'
import ErrorBlock from './ErrorBlock'
import DocBlock from './DocBlock'
import ScrollToBottom from './ScrollToBottom'
import { cn } from '../lib/utils'

export default function ChatTimeline({ blocks, streamingText, streamingBlockId, viewMode, status, doc }) {
  const isChat = viewMode === 'chat'
  const isDocs = viewMode === 'docs'
  const showMessages = viewMode !== 'docs'

  // Separate blocks into trace (thinking/tool/diff) and conversation (user/assistant/error)
  const { traceBlocks, messageBlocks } = useMemo(() => {
    if (!showMessages) {
      return { traceBlocks: [], messageBlocks: [] }
    }
    if (!isChat) {
      // Agent mode: everything is visible inline, no separation
      return { traceBlocks: [], messageBlocks: blocks }
    }

    const trace = []
    const msgs = []

    for (const b of blocks) {
      if (b.type === 'user' || b.type === 'assistant' || b.type === 'error') {
        msgs.push(b)
      } else {
        trace.push(b)
      }
    }

    return { traceBlocks: trace, messageBlocks: msgs }
  }, [blocks, isChat, showMessages])

  const isStreaming = showMessages && !!streamingBlockId && !!streamingText

  function renderBlock(block) {
    switch (block.type) {
      case 'user':
        return <MessageBlock key={block.id} block={block} viewMode={viewMode} />
      case 'assistant':
        return <MessageBlock key={block.id} block={block} viewMode={viewMode} />
      case 'thinking':
        return <ThinkingBlock key={block.id} block={block} />
      case 'tool_call':
        return <ToolUseBlock key={block.id} block={block} />
      case 'diff':
        return <PatchBlock key={block.id} block={block} />
      case 'error':
        return <ErrorBlock key={block.id} block={block} />
      default:
        return null
    }
  }

  return (
    <ScrollToBottom deps={[blocks.length, streamingText]}>
      <div className={cn(
        'mx-auto px-3 py-4',
        isChat ? 'max-w-chat' : 'max-w-3xl'
      )}>
        {/* Docs: only show in docs mode */}
        {isDocs && doc && (
          <DocBlock
            title={doc.title}
            path={doc.path}
            content={doc.content}
            loading={doc.loading}
            error={doc.error}
            truncated={doc.truncated}
            pinned={doc.pinned}
            canPin={doc.canPin}
            pinBusy={doc.pinBusy}
            pinError={doc.pinError}
            onTogglePin={doc.onTogglePin}
          />
        )}

        {isDocs && !doc && (
          <div className="flex flex-col items-center justify-center h-full py-24 text-center">
            <h2 className="text-sm text-text-secondary mb-1">Docs</h2>
            <p className="text-xs text-text-muted">Select a document from the left sidebar</p>
          </div>
        )}

        {/* Chat/Agent mode: trace blocks (thinking + tool calls) at the top */}
        {isChat && traceBlocks.length > 0 && (
          <div className="mb-4 space-y-1 border-b border-border-soft pb-3">
            <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5">Execution</div>
            {traceBlocks.map(renderBlock)}
          </div>
        )}

        {/* Empty state */}
        {showMessages && messageBlocks.length === 0 && !isStreaming && traceBlocks.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full py-24 text-center">
            <h2 className="text-sm text-text-secondary mb-1">fanfan</h2>
            <p className="text-xs text-text-muted">Send a message to get started</p>
          </div>
        )}

        {/* Conversation messages */}
        {messageBlocks.map(renderBlock)}

        {/* Streaming message */}
        {isStreaming && (
          <MessageBlock
            key="streaming"
            block={{ id: 'streaming', type: 'assistant', ts: null }}
            isStreaming
            streamingText={streamingText}
            viewMode={viewMode}
          />
        )}

        {/* Working indicator */}
        {status === 'running' && !isStreaming && (
          <div className="flex items-center gap-2 py-2 text-xs text-text-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-status-running animate-pulse-dot" />
            Working...
          </div>
        )}
      </div>
    </ScrollToBottom>
  )
}
