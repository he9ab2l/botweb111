import clsx from 'clsx'

/** Merge class names, filtering falsy values */
export function cn(...args) {
  return clsx(...args)
}

/** Format milliseconds as human-readable duration */
export function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

/** Format timestamp */
export function formatTime(ts) {
  if (!ts) return ''
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Truncate string */
export function truncate(s, max = 80) {
  if (!s || s.length <= max) return s
  return s.slice(0, max) + '...'
}

/** Copy text to clipboard */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
