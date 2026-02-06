import { useEffect, useRef, useState, useCallback } from 'react'
import { ArrowDown } from 'lucide-react'

/**
 * Wrapper that auto-scrolls to bottom when new content arrives,
 * unless the user has scrolled up. Shows a "scroll to bottom" button.
 */
export default function ScrollToBottom({ children, deps = [] }) {
  const containerRef = useRef(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [showButton, setShowButton] = useState(false)

  const checkScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const threshold = 80
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
    setIsAtBottom(atBottom)
    setShowButton(!atBottom)
  }, [])

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [])

  // Auto-scroll when deps change (new blocks/streaming text)
  useEffect(() => {
    if (isAtBottom) {
      const el = containerRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto"
        onScroll={checkScroll}
      >
        {children}
      </div>

      {showButton && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 px-2.5 py-1 rounded border border-border-soft bg-bg-secondary text-text-muted text-[11px] hover:text-text-secondary hover:border-border transition-colors"
        >
          <ArrowDown size={12} />
          Scroll to bottom
        </button>
      )}
    </div>
  )
}
