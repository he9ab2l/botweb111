import { useEffect, useRef, useCallback, useReducer } from 'react'
import { connectSSE } from '../lib/api'

const initialState = {
  blocks: [],
  streamingText: '',
  streamingMessageId: null,
  streamingRole: null,
  thinkingText: '',
  thinkingStartTs: null,
  status: 'idle',
  lastEventId: null,
  connectionStatus: 'disconnected',
  usage: null,
  toolCalls: [],
  pendingPermission: null,
}

function flushStreaming(state, ts) {
  if (!state.streamingMessageId || !state.streamingText || state.streamingRole !== 'assistant') return state
  return {
    ...state,
    blocks: [...state.blocks, {
      id: state.streamingMessageId,
      type: 'assistant',
      text: state.streamingText,
      ts,
    }],
    streamingText: '',
    streamingMessageId: null,
    streamingRole: null,
  }
}

function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { ...initialState, connectionStatus: state.connectionStatus }
    case 'SET_CONNECTION':
      return { ...state, connectionStatus: action.status }
    case 'SET_LAST_EVENT_ID':
      return { ...state, lastEventId: action.id }
    case 'CLEAR_PENDING_PERMISSION':
      return { ...state, pendingPermission: null }

    case 'APPLY_EVENT': {
      const evt = action.event
      const payload = evt.payload || {}
      const ts = evt.ts || Date.now() / 1000

      switch (evt.type) {
        case 'message_delta': {
          const role = payload.role
          const messageId = payload.message_id || `msg_${Date.now()}`
          const delta = payload.delta || ''

          if (role === 'user') {
            return {
              ...state,
              status: 'running',
              blocks: [...state.blocks, { id: messageId, type: 'user', text: delta, ts }],
            }
          }

          let next = state
          if (next.streamingMessageId && next.streamingMessageId !== messageId) {
            next = flushStreaming(next, ts)
          }
          if (!next.streamingMessageId) {
            next = { ...next, streamingMessageId: messageId, streamingText: '', streamingRole: 'assistant' }
          }
          return { ...next, status: 'running', streamingText: next.streamingText + delta }
        }

        case 'thinking': {
          const status = payload.status
          if (status === 'start') {
            return { ...state, status: 'running', thinkingText: '', thinkingStartTs: ts }
          }
          if (status === 'delta') {
            return { ...state, status: 'running', thinkingText: state.thinkingText + (payload.text || '') }
          }
          if (status === 'end') {
            const next = flushStreaming(state, ts)
            return {
              ...next,
              status: 'running',
              blocks: [...next.blocks, {
                id: `thinking_${Date.now()}`,
                type: 'thinking',
                text: state.thinkingText,
                duration_ms: payload.duration_ms || null,
                ts: state.thinkingStartTs || ts,
              }],
              thinkingText: '',
              thinkingStartTs: null,
            }
          }
          return state
        }

        case 'tool_call': {
          let next = flushStreaming(state, ts)
          const { tool_call_id, tool_name, input = {}, status: toolStatus = 'running' } = payload

          const existingIdx = next.toolCalls.findIndex(tc => tc.tool_call_id === tool_call_id)
          const existing = existingIdx >= 0 ? next.toolCalls[existingIdx] : {}
          const tc = {
            tool_call_id,
            tool_name,
            status: toolStatus,
            input,
            output: existing.output || null,
            error: existing.error || null,
            duration_ms: existing.duration_ms || 0,
            terminal: existing.terminal || '',
            ts,
          }

          const toolCalls = [...next.toolCalls]
          if (existingIdx >= 0) toolCalls[existingIdx] = tc
          else toolCalls.push(tc)

          const blocks = existingIdx >= 0
            ? next.blocks.map(b => b.id === tool_call_id ? { ...b, ...tc, type: 'tool_call' } : b)
            : [...next.blocks, { id: tool_call_id, type: 'tool_call', ...tc }]

          let pendingPermission = next.pendingPermission
          if (toolStatus === 'permission_required' && payload.permission_request_id) {
            pendingPermission = { requestId: payload.permission_request_id, tool_call_id, tool_name, input }
          }

          return { ...next, status: 'running', toolCalls, blocks, pendingPermission }
        }

        case 'terminal_chunk': {
          const { tool_call_id, text = '' } = payload
          const chunk = text
          const toolCalls = state.toolCalls.map(tc =>
            tc.tool_call_id === tool_call_id ? { ...tc, terminal: (tc.terminal || '') + chunk } : tc
          )
          const blocks = state.blocks.map(b =>
            b.id === tool_call_id && b.type === 'tool_call'
              ? { ...b, terminal: (b.terminal || '') + chunk }
              : b
          )
          return { ...state, status: 'running', toolCalls, blocks }
        }

        case 'tool_result': {
          let next = flushStreaming(state, ts)
          const { tool_call_id, ok, output = '', error = '', duration_ms = 0 } = payload
          const newStatus = ok ? 'completed' : 'error'

          const toolCalls = next.toolCalls.map(tc =>
            tc.tool_call_id === tool_call_id
              ? { ...tc, status: newStatus, output: ok ? output : tc.output, error: ok ? tc.error : (error || tc.error), duration_ms }
              : tc
          )
          const blocks = next.blocks.map(b =>
            b.id === tool_call_id && b.type === 'tool_call'
              ? { ...b, status: newStatus, output: ok ? output : b.output, error: ok ? b.error : error, duration_ms }
              : b
          )
          return { ...next, status: 'running', toolCalls, blocks }
        }

        case 'diff': {
          const next = flushStreaming(state, ts)
          return {
            ...next,
            status: 'running',
            blocks: [...next.blocks, {
              id: `diff_${payload.tool_call_id || 'x'}_${Date.now()}`,
              type: 'diff',
              tool_call_id: payload.tool_call_id,
              path: payload.path,
              diff: payload.diff,
              ts,
            }],
          }
        }



        case 'subagent': {
          const next = flushStreamingAssistant(state, ts)
          const parentId = payload.parent_tool_call_id
          if (!parentId) return next

          const blocks = next.blocks.map(b => {
            if (b.id !== parentId || b.type !== 'tool_call') return b
            const prev = b.subagent || {}
            return {
              ...b,
              subagent: {
                ...prev,
                subagent_id: payload.subagent_id || prev.subagent_id || null,
                status: payload.status || prev.status || 'running',
                label: payload.label || prev.label || '',
                task: payload.task || prev.task || '',
                result: payload.result || prev.result || '',
                error: payload.error || prev.error || '',
                blocks: Array.isArray(prev.blocks) ? prev.blocks : [],
              },
            }
          })

          return { ...next, status: 'running', blocks }
        }

        case 'subagent_block': {
          const next = flushStreamingAssistant(state, ts)
          const parentId = payload.parent_tool_call_id
          const blk = payload.block
          if (!parentId || !blk) return next

          const blk2 = { ...blk, ts: blk.ts || ts }

          const blocks = next.blocks.map(b => {
            if (b.id !== parentId || b.type !== 'tool_call') return b
            const prev = b.subagent || {}
            const arr = Array.isArray(prev.blocks) ? prev.blocks : []
            const existingIdx = arr.findIndex(x => x.id === blk2.id)
            const nextArr = existingIdx >= 0
              ? arr.map(x => (x.id === blk2.id ? { ...x, ...blk2 } : x))
              : [...arr, blk2]

            return { ...b, subagent: { ...prev, blocks: nextArr } }
          })

          return { ...next, status: 'running', blocks }
        }
        case 'final': {
          let next = flushStreaming(state, ts)
          const text = payload.text || ''
          if (text && !next.blocks.some(b => b.type === 'assistant' && b.id === payload.message_id)) {
            next = {
              ...next,
              blocks: [...next.blocks, { id: payload.message_id || `assistant_${Date.now()}`, type: 'assistant', text, ts }],
            }
          }
          return { ...next, status: 'idle', usage: payload.usage || next.usage }
        }

        case 'error': {
          const next = flushStreaming(state, ts)
          return {
            ...next,
            status: 'error',
            blocks: [...next.blocks, {
              id: `error_${Date.now()}`,
              type: 'error',
              text: payload.message || 'Unknown error',
              code: payload.code,
              ts,
            }],
          }
        }

        default:
          return state
      }
    }

    default:
      return state
  }
}

export function useEventStream(sessionId) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const esRef = useRef(null)
  const lastIdRef = useRef(null)
  const reconnectRef = useRef(0)

  const handleEvent = useCallback((event, eventId) => {
    if (eventId) {
      lastIdRef.current = eventId
      dispatch({ type: 'SET_LAST_EVENT_ID', id: eventId })
    }
    dispatch({ type: 'APPLY_EVENT', event })
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return
    dispatch({ type: 'SET_CONNECTION', status: 'connecting' })

    const es = connectSSE(
      sessionId,
      lastIdRef.current,
      (data, eventId) => {
        dispatch({ type: 'SET_CONNECTION', status: 'connected' })
        reconnectRef.current = 0
        handleEvent(data, eventId)
      },
      () => {
        dispatch({ type: 'SET_CONNECTION', status: 'error' })
        if (reconnectRef.current < 5) {
          reconnectRef.current++
          const delay = Math.min(1000 * Math.pow(2, reconnectRef.current), 30000)
          setTimeout(connect, delay)
        }
      }
    )
    esRef.current = es
  }, [sessionId, handleEvent])

  useEffect(() => {
    dispatch({ type: 'RESET' })
    lastIdRef.current = null
    reconnectRef.current = 0

    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }

    if (sessionId) connect()

    return () => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
  }, [sessionId, connect])

  const clearPendingPermission = useCallback(() => {
    dispatch({ type: 'CLEAR_PENDING_PERMISSION' })
  }, [])

  return { ...state, clearPendingPermission }
}
