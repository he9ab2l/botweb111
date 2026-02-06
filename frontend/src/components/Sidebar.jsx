import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { Plus, MessageSquare, Trash2, Search, X } from 'lucide-react'
import { cn, truncate } from '../lib/utils'

/**
 * Sidebar — v3 Lody style
 *
 * Session list with search, rename (double-click), delete.
 * Uses accent-blue for active/focus states.
 * Accepts searchFocusTrigger to externally focus the search input (Ctrl+K).
 */
export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onRenameSession,
  searchFocusTrigger,
}) {
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const searchRef = useRef(null)

  // Focus search input when Ctrl+K is pressed (trigger from App)
  useEffect(() => {
    if (searchFocusTrigger > 0 && searchRef.current) {
      searchRef.current.focus()
    }
  }, [searchFocusTrigger])

  const filtered = useMemo(() => {
    if (!search.trim()) return sessions
    const q = search.toLowerCase()
    return sessions.filter(s =>
      (s.title || '').toLowerCase().includes(q) ||
      (s.id || '').toLowerCase().includes(q)
    )
  }, [sessions, search])

  const handleDoubleClick = useCallback((session) => {
    setEditingId(session.id)
    setEditTitle(session.title || '')
  }, [])

  const handleRenameSubmit = useCallback((id) => {
    const trimmed = editTitle.trim()
    if (trimmed && onRenameSession) {
      onRenameSession(id, trimmed)
    }
    setEditingId(null)
    setEditTitle('')
  }, [editTitle, onRenameSession])

  const handleRenameKeyDown = useCallback((e, id) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleRenameSubmit(id)
    } else if (e.key === 'Escape') {
      setEditingId(null)
      setEditTitle('')
    }
  }, [handleRenameSubmit])

  return (
    <div className="flex flex-col h-full bg-bg-secondary border-r border-border-soft">
      <div className="p-2.5 border-b border-border-soft">
        <button
          onClick={onNewSession}
          className={cn(
            'w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded',
            'bg-btn-primary text-white text-xs',
            'hover:bg-btn-primary-hover transition-colors'
          )}
        >
          <Plus size={13} />
          New Chat
        </button>
      </div>

      <div className="px-2.5 pt-2 pb-1">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search..."
            className={cn(
              'w-full pl-8 pr-8 py-1.5 rounded text-xs',
              'bg-bg-secondary border border-border-soft text-text-primary',
              'placeholder:text-text-muted',
              'focus:outline-none focus:border-accent-blue'
            )}
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-1">
        {filtered.length === 0 && (
          <p className="text-xs text-text-muted text-center py-4">
            {sessions.length === 0 ? 'No chats yet' : 'No matches'}
          </p>
        )}

        {filtered.map(session => (
          <div
            key={session.id}
            onClick={() => onSelectSession(session.id)}
            onDoubleClick={() => handleDoubleClick(session)}
            className={cn(
              'group flex items-center gap-2 px-2.5 py-1.5 rounded mb-0.5 cursor-pointer border border-transparent',
              'text-sm transition-colors',
              session.id === activeSessionId
                ? 'bg-bg-tertiary/60 text-text-primary border-border-soft'
                : 'text-text-secondary hover:bg-bg-tertiary/40 hover:text-text-primary'
            )}
          >
            <MessageSquare size={12} className="shrink-0 text-text-muted" />
            <div className="min-w-0 flex-1">
              {editingId === session.id ? (
                <input
                  type="text"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  onBlur={() => handleRenameSubmit(session.id)}
                  onKeyDown={e => handleRenameKeyDown(e, session.id)}
                  autoFocus
                  className="w-full bg-bg border border-accent-blue rounded px-1 py-0.5 text-xs text-text-primary focus:outline-none"
                  onClick={e => e.stopPropagation()}
                />
              ) : (
                <>
                  <div className="truncate text-xs">
                    {truncate(session.title || 'Untitled', 30)}
                  </div>
                  <div className="text-[10px] text-text-muted mt-0.5">
                    {session.updated_at
                      ? new Date(session.updated_at).toLocaleDateString()
                      : ''
                    }
                  </div>
                </>
              )}
            </div>

            {/* Running indicator */}
            {session.status === 'running' && (
              <span className="w-1.5 h-1.5 rounded-full bg-status-running animate-pulse-dot shrink-0" />
            )}

            {/* Delete */}
            <button
              onClick={e => {
                e.stopPropagation()
                onDeleteSession(session.id)
              }}
              className="opacity-0 group-hover:opacity-100 shrink-0 text-text-muted hover:text-text-secondary transition-opacity"
              title="Delete"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
