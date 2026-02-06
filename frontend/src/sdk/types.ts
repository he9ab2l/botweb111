export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export type EventType =
  | 'connected'
  | 'heartbeat'
  | 'message_delta'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'terminal_chunk'
  | 'diff'
  | 'final'
  | 'error'

export type EventEnvelope = {
  id?: number
  seq?: number
  ts?: number
  type: EventType | string
  session_id?: string
  turn_id?: string
  step_id?: string
  payload?: any
}

export type SessionRecord = {
  id: string
  title: string
  created_at?: string
  updated_at?: string
  status?: 'idle' | 'running' | 'error'
}

