import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Copy, Check } from 'lucide-react'
import CodeBlock from './CodeBlock'
import { cn, formatTime, copyToClipboard } from '../lib/utils'

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

  if (isChat) {
    return (
      <div className={cn(
        'flex py-1.5',
        isUser ? 'justify-end' : 'justify-start'
      )}>
        <div className={cn(
          'group relative max-w-[85%] rounded-bubble px-3 py-2',
          isUser
            ? 'bg-bubble-user border border-border-soft'
            : 'bg-bubble-assistant border border-border-soft'
        )}>
          <div className="prose text-[13px] leading-[1.5] text-text-primary">
            <MarkdownContent text={text} />
            {isStreaming && (
              <span className="inline-block w-1 h-3 ml-0.5 bg-text-muted animate-blink rounded-sm" />
            )}
          </div>

          {text && !isStreaming && (
            <button
              onClick={handleCopy}
              className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 flex items-center gap-1 px-1.5 py-0.5 rounded border border-border-soft bg-bg text-text-muted hover:text-text-secondary text-[10px] transition-opacity"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          )}

          {block.ts && (
            <div className={cn(
              'text-[10px] text-text-muted mt-1',
              isUser ? 'text-right' : 'text-left'
            )}>
              {formatTime(block.ts)}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="group py-1.5">
      <div className="min-w-0 relative">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="text-[10px] tracking-wide uppercase text-text-muted">
            {isUser ? 'You' : 'nanobot'}
          </span>
          {block.ts && (
            <span className="text-[10px] text-text-muted">{formatTime(block.ts)}</span>
          )}
        </div>

        <div className="prose text-[13px] text-text-primary leading-[1.5] border border-border-soft rounded-md px-3 py-2 bg-bg-secondary/35">
          <MarkdownContent text={text} />
          {isStreaming && (
            <span className="inline-block w-1 h-3 ml-0.5 bg-text-muted animate-blink rounded-sm" />
          )}
        </div>

        {text && !isStreaming && (
          <button
            onClick={handleCopy}
            className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 flex items-center gap-1 px-1.5 py-0.5 rounded border border-border-soft bg-bg text-text-muted hover:text-text-secondary text-[10px] transition-opacity"
          >
            {copied ? <Check size={10} /> : <Copy size={10} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        )}
      </div>
    </div>
  )
}

export { MarkdownContent }
