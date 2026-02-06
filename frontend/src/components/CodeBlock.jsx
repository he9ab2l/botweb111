import { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check, ChevronDown, ChevronRight } from 'lucide-react'
import { copyToClipboard, cn } from '../lib/utils'

const MAX_LINES = 40

/**
 * CodeBlock — v3
 *
 * Syntax-highlighted code with:
 * - Language label
 * - Copy button
 * - Long code collapse (>40 lines)
 * Background matches bg-secondary (#0f172a)
 */
export default function CodeBlock({ children, language, className }) {
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const lang = language || (className ? className.replace(/language-/, '') : 'text')
  const code = typeof children === 'string' ? children.replace(/\n$/, '') : String(children || '')

  const lines = code.split('\n')
  const isLong = lines.length > MAX_LINES
  const displayCode = isLong && !expanded ? lines.slice(0, MAX_LINES).join('\n') : code

  const handleCopy = async () => {
    const ok = await copyToClipboard(code)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="relative group rounded overflow-hidden border border-border-soft my-1.5">
      <div className="flex items-center justify-between bg-bg-secondary px-2.5 py-1 text-[10px] text-text-muted border-b border-border-soft">
        <span className="font-mono">{lang}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-text-secondary transition-colors"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      <SyntaxHighlighter
        language={lang}
        style={oneDark}
        customStyle={{
          margin: 0,
          padding: '0.6rem 0.85rem',
          fontSize: '0.78rem',
          lineHeight: '1.45',
          background: '#0f172a',
          borderRadius: 0,
        }}
        wrapLongLines
      >
        {displayCode}
      </SyntaxHighlighter>

      {isLong && (
        <button
          onClick={() => setExpanded(e => !e)}
          className={cn(
            'w-full flex items-center justify-center gap-1 py-1 text-[10px]',
            'bg-bg-secondary text-text-muted hover:text-text-secondary transition-colors',
            'border-t border-border-soft'
          )}
        >
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          {expanded ? 'Collapse' : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  )
}
