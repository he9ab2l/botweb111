import { clsx } from 'clsx'

export function cn(...args) {
  return clsx(...args)
}

export function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function formatDuration(ms) {
  if (!ms || ms < 0) return '0s'
  if (ms < 1000) return `${ms}ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const remainder = s % 60
  return remainder > 0 ? `${m}m ${remainder}s` : `${m}m`
}

export function truncate(str, maxLen = 80) {
  if (!str) return ''
  return str.length > maxLen ? str.slice(0, maxLen) + '...' : str
}

export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
