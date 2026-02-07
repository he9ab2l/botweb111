import { useMemo } from 'react'
import MessageBlock from './MessageBlock'
import ThinkingBlock from './ThinkingBlock'
import ToolUseBlock from './ToolUseBlock'
import PatchBlock from './PatchBlock'
import ErrorBlock from './ErrorBlock'
import TraceDrawer from './TraceDrawer'
import DocBlock from './DocBlock'
import ScrollToBottom from './ScrollToBottom'
import { cn } from '../lib/utils'

export default function ChatTimeline({ blocks, streamingText, streamingBlockId, viewMode, status, doc }) {
  const isChat = viewMode === 'chat'

  // In chat mode, separate visible messages from execution trace
  const { visibleBlocks, traceBlocks } = useMemo(() => {
    if (!isChat) {
      return { visibleBlocks: blocks, traceBlocks: [] }
    }

    const visible = []
    const trace = []

    for (const b of blocks) {
      if (b.type === 'user' || b.type === 'assistant' || b.type === 'error') {
        visible.push(b)
      } else {
        trace.push(b)
      }
    }

    return { visibleBlocks: visible, traceBlocks: trace }
  }, [blocks, isChat])

  const isStreaming = !!streamingBlockId && !!streamingText

  return (
    <ScrollToBottom deps={[blocks.length, streamingText]}>
      <div className={cn(
        'mx-auto px-3 py-4',
        isChat ? 'max-w-chat' : 'max-w-3xl'
      )}>
        {doc && (
          <DocBlock
            title={doc.title}
            path={doc.path}
            content={doc.content}
            loading={doc.loading}
            error={doc.error}
            truncated={doc.truncated}
          />
        )}

        {visibleBlocks.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center h-full py-24 text-center">
            <h2 className="text-sm text-text-secondary mb-1">fanfan</h2>
            <p className="text-xs text-text-muted">Send a message to get started</p>
          </div>
        )}

        {visibleBlocks.map((block, idx) => {
          switch (block.type) {
            case 'user':
              return <MessageBlock key={block.id} block={block} viewMode={viewMode} />
            case 'assistant': {
              const isLastAssistant = isChat && idx === visibleBlocks.length - 1
              return (
                <div key={block.id}>
                  <MessageBlock block={block} viewMode={viewMode} />
                  {isLastAssistant && traceBlocks.length > 0 && (
                    <TraceDrawer details={traceBlocks} />
                  )}
                </div>
              )
            }
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
        })}

        {isStreaming && (
          <MessageBlock
            key="streaming"
            block={{ id: 'streaming', type: 'assistant', ts: null }}
            isStreaming
            streamingText={streamingText}
            viewMode={viewMode}
          />
        )}

        {isChat && isStreaming && traceBlocks.length > 0 && (
          <TraceDrawer details={traceBlocks} />
        )}

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
