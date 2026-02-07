import { useEffect, useRef, useCallback, useReducer } from 'react'
import { connectSSE } from '../lib/api'

/**
 * fanfan v2 event protocol.
 * SSE envelope: { id, seq, ts, type, session_id, turn_id, step_id, payload }
 */

const initialState = {
  blocks: [],
  streamingText: '',
  streamingMessageId: null,
  streamingRole: null,

  thinkingText: '',
  thinkingStartTs: null,

  status: 'idle', // idle | running | error
  lastEventId: null,
  connectionStatus: 'disconnected',

  usage: null,
  toolCalls: [], // [{tool_call_id, tool_name, status, duration_ms, input, output, error, terminal}]

  pendingPermission: null, // { requestId, tool_call_id, tool_name, input }
}

function flushStreamingAssistant(state, ts) {
  if (!state.streamingMessageId || !state.streamingText || state.streamingRole !== 'assistant') return state

  return {
    ...state,
    blocks: [
      ...state.blocks,
      {
        id: state.streamingMessageId,
        type: 'assistant',
        text: state.streamingText,
        ts,
      },
    ],
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

          // assistant streaming
          let next = state
          if (next.streamingMessageId && next.streamingMessageId !== messageId) {
            next = flushStreamingAssistant(next, ts)
          }
          if (!next.streamingMessageId) {
            next = { ...next, streamingMessageId: messageId, streamingText: '', streamingRole: 'assistant' }
          }
          return {
            ...next,
            status: 'running',
            streamingText: next.streamingText + delta,
          }
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
            const next = flushStreamingAssistant(state, ts)
            const durationMs = payload.duration_ms || null
            return {
              ...next,
              status: 'running',
              blocks: [
                ...next.blocks,
                {
                  id: `thinking_${Date.now()}`,
                  type: 'thinking',
                  text: state.thinkingText,
                  duration_ms: durationMs,
                  ts: state.thinkingStartTs || ts,
                },
              ],
              thinkingText: '',
              thinkingStartTs: null,
            }
          }
          return state
        }

        case 'tool_call': {
          let next = flushStreamingAssistant(state, ts)

          const tool_call_id = payload.tool_call_id
          const tool_name = payload.tool_name
          const toolStatus = payload.status || 'running'
          const input = payload.input || {}

          // Upsert tool call record
          const existingIdx = next.toolCalls.findIndex(tc => tc.tool_call_id === tool_call_id)
          const tc = {
            tool_call_id,
            tool_name,
            status: toolStatus,
            input,
            output: existingIdx >= 0 ? next.toolCalls[existingIdx].output : null,
            error: existingIdx >= 0 ? next.toolCalls[existingIdx].error : null,
            duration_ms: existingIdx >= 0 ? next.toolCalls[existingIdx].duration_ms : 0,
            terminal: existingIdx >= 0 ? next.toolCalls[existingIdx].terminal : '',
            ts,
          }
          const toolCalls = [...next.toolCalls]
          if (existingIdx >= 0) toolCalls[existingIdx] = tc
          else toolCalls.push(tc)

          // Upsert block
          const blocks = existingIdx >= 0
            ? next.blocks.map(b => (b.id === tool_call_id ? { ...b, ...tc, type: 'tool_call' } : b))
            : [...next.blocks, { id: tool_call_id, type: 'tool_call', ...tc }]

          let pendingPermission = next.pendingPermission
          if (toolStatus === 'permission_required' && payload.permission_request_id) {
            pendingPermission = {
              requestId: payload.permission_request_id,
              tool_call_id,
              tool_name,
              input,
            }
          }

          return {
            ...next,
            status: 'running',
            toolCalls,
            blocks,
            pendingPermission,
          }
        }

        case 'terminal_chunk': {
          const tool_call_id = payload.tool_call_id
          const text = payload.text || ''
          const stream = payload.stream || 'stdout'
          const prefix = stream === 'stderr' ? '' : ''
          const chunk = prefix + text

          const toolCalls = nextToolCallsWith(nextToolCallsWithTerminal(state.toolCalls, tool_call_id, chunk))
          const blocks = state.blocks.map(b =>
            b.id === tool_call_id && b.type === 'tool_call'
              ? { ...b, terminal: (b.terminal || '') + chunk }
              : b
          )
          return { ...state, status: 'running', toolCalls, blocks }
        }

        case 'tool_result': {
          let next = flushStreamingAssistant(state, ts)
          const tool_call_id = payload.tool_call_id
          const ok = !!payload.ok
          const output = payload.output || ''
          const error = payload.error || ''
          const duration_ms = payload.duration_ms || 0

          const toolCalls = next.toolCalls.map(tc =>
            tc.tool_call_id === tool_call_id
              ? { ...tc, status: ok ? 'completed' : 'error', output: ok ? output : tc.output, error: ok ? tc.error : (error || tc.error), duration_ms }
              : tc
          )

          const blocks = next.blocks.map(b =>
            b.id === tool_call_id && b.type === 'tool_call'
              ? { ...b, status: ok ? 'completed' : 'error', output: ok ? output : b.output, error: ok ? b.error : error, duration_ms }
              : b
          )

          return { ...next, status: 'running', toolCalls, blocks }
        }

        case 'diff': {
          const next = flushStreamingAssistant(state, ts)
          return {
            ...next,
            status: 'running',
            blocks: [
              ...next.blocks,
              {
                id: `diff_${payload.tool_call_id || 'x'}_${Date.now()}`,
                type: 'diff',
                tool_call_id: payload.tool_call_id,
                path: payload.path,
                diff: payload.diff,
                ts,
              },
            ],
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
          let next = flushStreamingAssistant(state, ts)
          const text = payload.text || ''
          if (text && !next.blocks.some(b => b.type === 'assistant' && b.id === payload.message_id)) {
            next = {
              ...next,
              blocks: [...next.blocks, { id: payload.message_id || `assistant_${Date.now()}`, type: 'assistant', text, ts }],
            }
          }
          return {
            ...next,
            status: 'idle',
            usage: payload.usage || next.usage,
          }
        }

        case 'error': {
          const next = flushStreamingAssistant(state, ts)
          return {
            ...next,
            status: 'error',
            blocks: [
              ...next.blocks,
              {
                id: `error_${Date.now()}`,
                type: 'error',
                text: payload.message || 'Unknown error',
                code: payload.code,
                ts,
              },
            ],
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

function nextToolCallsWithTerminal(toolCalls, tool_call_id, chunk) {
  return toolCalls.map(tc =>
    tc.tool_call_id === tool_call_id ? { ...tc, terminal: (tc.terminal || '') + chunk } : tc
  )
}

function nextToolCallsWith(toolCalls) {
  return toolCalls
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

