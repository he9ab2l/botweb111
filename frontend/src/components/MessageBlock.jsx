import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Copy, Check } from 'lucide-react'
import CodeBlock from './CodeBlock'
import { cn, formatTime, formatDuration, copyToClipboard } from '../lib/utils'

/**
 * MarkdownContent — renders markdown text with GFM + code blocks
 * Exported for reuse in ThinkingBlock
 */
function MarkdownContent({ text }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ node, inline, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || '')
          if (!inline && (match || (typeof children === 'string' && children.includes('\n')))) {
            return (
              <CodeBlock language={match?.[1]} className={className}>
                {String(children)}
              </CodeBlock>
            )
          }
          return (
            <code className={className} {...props}>
              {children}
            </code>
          )
        },
      }}
    >
      {text || ''}
    </ReactMarkdown>
  )
}

export default function MessageBlock({ block, isStreaming, streamingText, viewMode }) {
  const [copied, setCopied] = useState(false)
  const isUser = block.type === 'user'
  const text = isStreaming ? (streamingText || '') : (block.text || '')
  const isChat = viewMode === 'chat'

  const handleCopy = async () => {
    const ok = await copyToClipboard(text)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const MessageCard = ({ className, children }) => {
    return (
      <div className={cn('border border-border-soft', className)}>
        {children}
      </div>
    )
  }

  const MessageContent = ({ className, children }) => {
    return <div className={className}>{children}</div>
  }

  const MessageFooter = () => {
    // Keep footer height stable to avoid layout jitter during streaming.
    // Copy button stays present (disabled when no text).
    return (
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="min-w-0 flex items-center gap-2">
          <span className="text-[10px] text-text-muted tabular-nums leading-none">
            {block.ts ? formatTime(block.ts) : ''}
          </span>

          {block.type === 'assistant' && block.thinking_ms != null && block.thinking_ms > 0 && (
            <span className="text-[10px] text-text-muted leading-none">
              Think {formatDuration(block.thinking_ms)}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1" aria-hidden="true" />

          <button
            type="button"
            onClick={handleCopy}
            disabled={!text}
            aria-label="Copy message"
            title="Copy"
            className={cn(
              'h-10 w-10 inline-flex items-center justify-center rounded-md',
              'border border-border-soft bg-bg-secondary/40',
              'text-text-muted hover:text-text-secondary hover:border-border',
              'transition-colors',
              'disabled:opacity-40 disabled:cursor-not-allowed'
            )}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
          </button>
        </div>
      </div>
    )
  }

  if (isChat) {
    return (
      <div className={cn(
        'flex py-1.5',
        isUser ? 'justify-end' : 'justify-start'
      )}>
        <MessageCard
          className={cn(
            'max-w-[92%] sm:max-w-[85%] rounded-bubble px-3 py-2',
            isUser ? 'bg-bubble-user' : 'bg-bubble-assistant'
          )}
        >
          <MessageContent className="prose text-[14px] sm:text-[13px] leading-[1.5] text-text-primary">
            <MarkdownContent text={text} />
            {isStreaming && (
              <span className="inline-block w-1 h-3 ml-0.5 bg-text-muted animate-blink rounded-sm" />
            )}
          </MessageContent>

          <MessageFooter />
        </MessageCard>
      </div>
    )
  }

  return (
    <div className="py-1.5">
      <div className="min-w-0">
        <MessageCard className="rounded-md px-3 py-2 bg-bg-secondary/35">
          <MessageContent className="prose text-[14px] sm:text-[13px] text-text-primary leading-[1.5]">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[10px] tracking-wide uppercase text-text-muted">
                {isUser ? 'You' : 'fanfan'}
              </span>
            </div>

          <MarkdownContent text={text} />
          {isStreaming && (
            <span className="inline-block w-1 h-3 ml-0.5 bg-text-muted animate-blink rounded-sm" />
          )}
          </MessageContent>

          <MessageFooter />
        </MessageCard>
      </div>
    </div>
  )
}

export { MarkdownContent }
