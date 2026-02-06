import { useEffect, useRef, useCallback, useReducer } from 'react'
import { connectSSE } from '../lib/api'

/**
 * Event types from the backend protocol.
 * Each event: { type, run_id, ts, step, payload, session_id }
 */

const initialState = {
  blocks: [],         // timeline blocks
  streamingText: '',  // current streaming text accumulator
  streamingBlockId: null,
  lastAssistantBlockId: null,
  thinkingText: '',
  thinkingBlockId: null,
  thinkingStart: null,
  pendingThinkingDurationMs: null,
  runId: null,
  status: 'idle',     // idle | running | error
  lastEventId: null,
  connectionStatus: 'disconnected',
  usage: null,
  stopReason: null,
  toolCalls: [],      // [{tool_call_id, tool_name, status, duration_ms, input, output, error}]
}

function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { ...initialState, blocks: [], connectionStatus: state.connectionStatus }

    case 'SET_CONNECTION':
      return { ...state, connectionStatus: action.status }

    case 'SET_LAST_EVENT_ID':
      return { ...state, lastEventId: action.id }

    // Legacy user event (from old protocol)
    case 'USER_MESSAGE':
      return {
        ...state,
        blocks: [...state.blocks, {
          id: `user_${Date.now()}`,
          type: 'user',
          text: action.text,
          ts: action.ts,
        }],
      }

    case 'STATUS': {
      const s = action.payload.status
      return {
        ...state,
        status: s === 'started' ? 'running' : state.status,
        runId: action.run_id || state.runId,
      }
    }

    case 'CONTENT_BLOCK_START': {
      const { block_id, block_type } = action.payload
      if (block_type === 'text') {
        return { ...state, streamingBlockId: block_id, streamingText: '' }
      }
      return state
    }

    case 'CONTENT_BLOCK_DELTA': {
      const { block_id, delta } = action.payload
      if (block_id === state.streamingBlockId) {
        return { ...state, streamingText: state.streamingText + delta }
      }
      return state
    }

    case 'CONTENT_BLOCK_STOP': {
      const { block_id } = action.payload
      if (block_id === state.streamingBlockId && state.streamingText) {
        return {
          ...state,
          blocks: [...state.blocks, {
            id: block_id,
            type: 'assistant',
            text: state.streamingText,
            ts: action.ts,
            thinking_ms: state.pendingThinkingDurationMs || null,
          }],
          streamingText: '',
          streamingBlockId: null,
          lastAssistantBlockId: block_id,
          pendingThinkingDurationMs: null,
        }
      }
      return { ...state, streamingBlockId: null }
    }

    case 'THINKING': {
      const { status, text, duration_ms } = action.payload
      if (status === 'start') {
        return {
          ...state,
          thinkingBlockId: `thinking_${Date.now()}`,
          thinkingText: text || '',
          thinkingStart: action.ts,
        }
      }
      if (status === 'end' && state.thinkingBlockId) {
        // Attach thinking duration to the most recent assistant message if present.
        // If the assistant message hasn't been created yet, stash it for later.
        const thinkingMs = duration_ms || 0
        let blocks = state.blocks
        if (state.lastAssistantBlockId) {
          blocks = blocks.map(b =>
            b.id === state.lastAssistantBlockId && b.type === 'assistant'
              ? { ...b, thinking_ms: thinkingMs }
              : b
          )
        }
        return {
          ...state,
          blocks: [...blocks, {
            id: state.thinkingBlockId,
            type: 'thinking',
            text: state.thinkingText,
            duration_ms: thinkingMs,
            ts: state.thinkingStart || action.ts,
          }],
          thinkingBlockId: null,
          thinkingText: '',
          thinkingStart: null,
          pendingThinkingDurationMs: state.lastAssistantBlockId ? null : thinkingMs,
        }
      }
      return state
    }

    case 'TOOL_USE': {
      const { tool_call_id, tool_name, input, status: toolStatus } = action.payload
      const tc = {
        tool_call_id,
        tool_name,
        status: toolStatus,
        input: input || {},
        output: null,
        error: null,
        duration_ms: 0,
        ts: action.ts,
      }
      // Also add as a timeline block
      return {
        ...state,
        toolCalls: [...state.toolCalls, tc],
        blocks: [...state.blocks, {
          id: tool_call_id,
          type: 'tool_use',
          tool_call_id,
          tool_name,
          input: input || {},
          status: toolStatus,
          ts: action.ts,
        }],
      }
    }

    case 'TOOL_RESULT': {
      const { tool_call_id, output, duration_ms } = action.payload
      const updatedCalls = state.toolCalls.map(tc =>
        tc.tool_call_id === tool_call_id
          ? { ...tc, status: 'completed', output, duration_ms }
          : tc
      )
      const updatedBlocks = state.blocks.map(b =>
        b.id === tool_call_id
          ? { ...b, status: 'completed', output, duration_ms }
          : b
      )
      return { ...state, toolCalls: updatedCalls, blocks: updatedBlocks }
    }

    case 'TOOL_ERROR': {
      const { tool_call_id, error, duration_ms } = action.payload
      const updatedCalls = state.toolCalls.map(tc =>
        tc.tool_call_id === tool_call_id
          ? { ...tc, status: 'error', error, duration_ms }
          : tc
      )
      const updatedBlocks = state.blocks.map(b =>
        b.id === tool_call_id
          ? { ...b, status: 'error', error, duration_ms }
          : b
      )
      return { ...state, toolCalls: updatedCalls, blocks: updatedBlocks }
    }

    case 'PATCH': {
      const { tool_call_id, files } = action.payload
      return {
        ...state,
        blocks: [...state.blocks, {
          id: `patch_${tool_call_id}_${Date.now()}`,
          type: 'patch',
          tool_call_id,
          files: files || [],
          ts: action.ts,
        }],
      }
    }

    case 'MESSAGE_DELTA': {
      return {
        ...state,
        stopReason: action.payload.stop_reason,
        usage: action.payload.usage || state.usage,
      }
    }

    case 'FINAL_DONE': {
      // Flush any remaining streaming text
      let blocks = state.blocks
      if (state.streamingText) {
        const id = state.streamingBlockId || `text_${Date.now()}`
        blocks = [...blocks, {
          id,
          type: 'assistant',
          text: state.streamingText,
          ts: action.ts,
          thinking_ms: state.pendingThinkingDurationMs || null,
        }]
      }
      return {
        ...state,
        blocks,
        streamingText: '',
        streamingBlockId: null,
        lastAssistantBlockId: state.streamingText ? (state.streamingBlockId || state.lastAssistantBlockId) : state.lastAssistantBlockId,
        pendingThinkingDurationMs: state.streamingText ? null : state.pendingThinkingDurationMs,
        status: 'idle',
      }
    }

    case 'ERROR': {
      return {
        ...state,
        status: 'error',
        blocks: [...state.blocks, {
          id: `error_${Date.now()}`,
          type: 'error',
          text: action.payload.message || 'Unknown error',
          code: action.payload.code,
          ts: action.ts,
        }],
      }
    }

    // Legacy final events (backward compat with old protocol)
    case 'LEGACY_FINAL_STREAMING': {
      return { ...state, streamingText: state.streamingText + (action.delta || '') }
    }
    case 'LEGACY_FINAL_DONE': {
      const text = action.text || state.streamingText
      let blocks = state.blocks
      if (text) {
        blocks = [...blocks, {
          id: `assistant_${Date.now()}`,
          type: 'assistant',
          text,
          ts: action.ts,
        }]
      }
      return {
        ...state,
        blocks,
        streamingText: '',
        streamingBlockId: null,
        status: 'idle',
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

  const handleEvent = useCallback((data, eventId) => {
    if (eventId) {
      lastIdRef.current = eventId
      dispatch({ type: 'SET_LAST_EVENT_ID', id: eventId })
    }

    const evtType = data.type
    const payload = data.payload || {}
    const ts = data.ts || data.timestamp || Date.now() / 1000

    // New structured protocol events
    switch (evtType) {
      case 'status':
        dispatch({ type: 'STATUS', payload, run_id: data.run_id, ts })
        break
      case 'content_block_start':
        dispatch({ type: 'CONTENT_BLOCK_START', payload, ts })
        break
      case 'content_block_delta':
        dispatch({ type: 'CONTENT_BLOCK_DELTA', payload, ts })
        break
      case 'content_block_stop':
        dispatch({ type: 'CONTENT_BLOCK_STOP', payload, ts })
        break
      case 'thinking':
        dispatch({ type: 'THINKING', payload, ts })
        break
      case 'tool_use':
        dispatch({ type: 'TOOL_USE', payload, ts })
        break
      case 'tool_result':
        dispatch({ type: 'TOOL_RESULT', payload, ts })
        break
      case 'tool_error':
        dispatch({ type: 'TOOL_ERROR', payload, ts })
        break
      case 'patch':
        dispatch({ type: 'PATCH', payload, ts })
        break
      case 'message_delta':
        dispatch({ type: 'MESSAGE_DELTA', payload, ts })
        break
      case 'final_done':
        dispatch({ type: 'FINAL_DONE', payload, ts })
        break
      case 'error':
        dispatch({ type: 'ERROR', payload, ts })
        break

      // Legacy events (backward compat)
      case 'user':
        dispatch({ type: 'USER_MESSAGE', text: payload.text, ts })
        break
      case 'final':
        if (data.status === 'streaming') {
          dispatch({ type: 'LEGACY_FINAL_STREAMING', delta: payload.delta })
        } else if (data.status === 'done') {
          dispatch({ type: 'LEGACY_FINAL_DONE', text: payload.text, ts })
        }
        break
      default:
        console.log('Unknown event type:', evtType, data)
    }
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
        // Auto-reconnect
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

    if (sessionId) {
      connect()
    }

    return () => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
  }, [sessionId, connect])

  return state
}
