# fanfan (Nanobot) OpenCode-Style WebUI Refactor Design

This document defines the target architecture and protocols to refactor the existing `nanobot` (FastAPI + React/Vite/Tailwind) into an OpenCode-style "two-stage WebUI + event bus + agent trace" system, and rebrand it as **fanfan**.

Scope: MVP first (runnable end-to-end), then iterate toward the full checklist.

## Goals (Must-Have MVP)

1. Two-stage WebUI (same-origin, no CORS):
   - A local **API/Event Server** (FastAPI) runs on a single port.
   - The server **serves or reverse-proxies** the WebUI at `/`.
   - SPA fallback: unknown routes fall back to the UI entry (client-side routing).
   - Support modes:
     - `UI_MODE=remote`: proxy `UI_URL` to `/`
     - `UI_MODE=static`: serve built assets from a local directory
     - `UI_MODE=dev`: proxy a local Vite dev server (HMR)
   - Inject CSP (at minimum `default-src 'self'`).
   - Health check: `GET /healthz`.

2. Global SSE event bus:
   - `GET /event` for global subscription (optionally filtered by `session_id`).
   - `connected` event on open; `heartbeat` every 10-20s.
   - Reconnect support: `Last-Event-ID` header and `?since=` query.
   - Multi-client subscribers.
   - Persistent event log with replay: `GET /api/v2/sessions/{id}/events?since=...`.
   - Event ordering:
     - `id`: global monotonic event id (for SSE `id:`).
     - `seq`: per-session monotonic sequence.

3. Execution data model:
   - session: many turns
   - turn: many steps
   - step: many parts (parts are persisted as events)

4. Agent execution engine:
   - Loop:
     - model generate (stream deltas)
     - if tool calls: emit tool_call -> permission gate -> execute -> tool_result (+ diff/terminal chunks)
     - repeat until no tool calls
   - Emits parts immediately to SSE and persists them.
   - Supports cancellation and timeouts.

5. Tools + permissions:
   - Tool registry with JSON schema:
     - `read_file`, `write_file`, `apply_patch`, `search`, `http_fetch`, `spawn_subagent`
   - Tool execution:
     - emits `tool_call` then `tool_result`
     - records timing, errors
     - for file mutations emits `diff` and persists `file_change`
     - captures per-session file versions for rollback
     - `spawn_subagent` emits nested subagent events under the parent tool call
   - Permission gate (per tool): `deny` / `ask` / `allow`
     - `ask` triggers a UI approval modal and blocks tool execution until resolved
     - decisions can be "once / this session / always"
   - Global permission mode:
     - `ask` (require approval) or `allow` (run all tools without prompts)
     - stored in DB and exposed via `/api/v2/permissions/mode`

6. Frontend UX (OpenCode-like information architecture):
   - Three columns:
     - left: sessions + docs
     - center: chat/docs timeline
     - right: Inspector tabs: Trace / Files / Context / Permissions
   - View modes:
     - Chat: conversation-only
     - Docs: active document only
     - Agent: full execution timeline
   - Streaming rendering:
     - `message_delta` appends incrementally
     - tool cards update per `tool_call`/`tool_result`
     - diffs render with highlight and fold
     - subagent trees render inside the parent tool card

## Two-Stage WebUI Architecture

### Runtime Modes

The FastAPI server owns port `FANFAN_PORT` (default `4096`) and is the single origin for the browser.

`UI_MODE` controls how `/` is served:

1. `UI_MODE=static`
   - Server serves files from `UI_STATIC_DIR` (default: `nanobot/web/static/dist`)
   - SPA fallback to `index.html`

2. `UI_MODE=remote`
   - Server reverse-proxies `UI_URL` (e.g. official hosted UI) to `/`
   - For SPA: unknown routes also proxy to `UI_URL` entry

3. `UI_MODE=dev`
   - Server reverse-proxies `UI_DEV_SERVER_URL` (default: `http://127.0.0.1:4444`) to `/`
   - Used by `fanfan dev web` to keep API + UI same-origin

### Routing & CSP

API endpoints live under `/api/v2/...` (legacy `/api/v1/...` remains during migration).

Non-API routes:
- `/`, `/assets/*`, `/icons/*`, `/manifest.webmanifest`, `/sw.js`, etc are handled by the UI mode.
- Unknown non-API paths fall back to the UI entry.

CSP:
- Production-like: `default-src 'self'`
- Dev mode may add `connect-src` for HMR websocket and `script-src 'unsafe-eval'` if required.

## API Route Plan (v2)

### Health
- `GET /healthz`
- `GET /api/v2/health`

### Config / Models
- `GET /api/v2/config`
- `POST /api/v2/config`
- `GET /api/v2/sessions/{session_id}/model`
- `POST /api/v2/sessions/{session_id}/model`
- `DELETE /api/v2/sessions/{session_id}/model`

### Docs
- `GET /api/v2/docs`
- `GET /api/v2/docs/file?path=...`


### SSE / Events
- `GET /event`
  - Query:
    - `session_id` (optional)
    - `since` (optional, global event id)
  - Headers:
    - `Last-Event-ID` (optional, global event id)
- `GET /api/v2/sessions/{session_id}/events`
  - Query:
    - `since` (optional global event id) OR `since_seq` (optional session seq)

### Sessions
- `POST /api/v2/sessions`
- `GET /api/v2/sessions`
- `GET /api/v2/sessions/{session_id}`
- `PATCH /api/v2/sessions/{session_id}`
- `DELETE /api/v2/sessions/{session_id}`

### Export
- `GET /api/v2/sessions/{session_id}/export.json`
- `GET /api/v2/sessions/{session_id}/export.md`

### Turns / Steps
- `POST /api/v2/sessions/{session_id}/turns`
  - body: `{ content: string }`
  - creates `turn`, starts agent run in background, emits events
- `GET /api/v2/sessions/{session_id}/turns`
- `GET /api/v2/turns/{turn_id}`
- `GET /api/v2/turns/{turn_id}/steps`

### Tools (registry/metadata)
- `GET /api/v2/tools`
  - returns schemas, current permission policy, enabled/disabled, permission_mode

### Files / Artifacts (MVP subset)
- `GET /api/v2/sessions/{session_id}/file_changes`
- `GET /api/v2/sessions/{session_id}/terminal`
- `GET /api/v2/sessions/{session_id}/context`
- `POST /api/v2/sessions/{session_id}/context/pin`
- `POST /api/v2/sessions/{session_id}/context/unpin`

### Permissions
- `GET /api/v2/sessions/{session_id}/permissions/pending`
- `POST /api/v2/permissions/{request_id}/resolve`

### Cancellation
- `POST /api/v2/sessions/{session_id}/cancel`

## Event Schema (JSON)

All persisted parts are emitted to SSE using a stable envelope:

```json
{
  "id": 123,
  "seq": 42,
  "ts": 1738888888.123,
  "type": "message_delta",
  "session_id": "ses_...",
  "turn_id": "turn_...",
  "step_id": "step_...",
  "payload": { }
}
```

Required `type` values (MVP):
- `connected`
  - payload: `{ server_time, latest_id }`
- `heartbeat`
  - payload: `{ }`
- `message_delta`
  - payload: `{ role: "assistant", message_id, delta }`
- `thinking`
  - payload: `{ status: "start"|"delta"|"end", text?: string, duration_ms?: number }`
- `tool_call`
  - payload: `{ tool_call_id, tool_name, input, status }`
  - status: `permission_required | running | completed | error`
  - if `permission_required`: payload includes `{ permission_request_id, choices }`
- `tool_result`
  - payload: `{ tool_call_id, tool_name, ok: boolean, output?: string, error?: string, duration_ms }`
- `terminal_chunk`
  - payload: `{ tool_call_id, stream: "stdout"|"stderr", text }`
- `diff`
  - payload: `{ tool_call_id, path, diff }`
- `final`
  - payload: `{ role: "assistant", message_id, text, finish_reason, usage? }`
- `error`
  - payload: `{ code, message }`

Relationships:
- A **turn** is created for each user message.
- A **step** is created per agent iteration (LLM call + tool executions).
- Every emitted event is associated with `(session_id, turn_id, step_id)` and persisted.

## Persistence (SQLite Default)

SQLite is default; Postgres can be added later with the same logical schema.

### Tables (MVP)

- `sessions`
  - id, title, created_at, updated_at
- `session_settings`
  - session_id, model, updated_at
- `turns`
  - id, session_id, user_text, created_at
- `steps`
  - id, turn_id, idx, status, started_at, finished_at
- `events`
  - id INTEGER PK AUTOINCREMENT (global event id)
  - session_id, turn_id, step_id
  - seq (per-session)
  - ts (REAL)
  - type (TEXT)
  - payload_json (TEXT)
- `file_changes`
  - id, session_id, turn_id, step_id, path, diff, created_at
- `permission_requests`
  - id, session_id, turn_id, step_id
  - tool_name, input_json
  - status (pending/approved/denied/expired)
  - scope (once/session/always)
  - created_at, resolved_at
- `tool_permissions`
  - tool_name PRIMARY KEY
  - policy (deny/ask/allow)
  - updated_at
- `context_items`
  - id, session_id, kind (file/web/summary/memory)
  - title, content_ref, pinned, created_at
- `terminal_chunks`
  - id, session_id, turn_id, step_id, tool_call_id
  - stream, text, ts

### Migrations

Migrations use `PRAGMA user_version` and run on startup.

Legacy `/api/v1` continues to work during migration; v2 endpoints become the new frontend's default.

## Frontend State Model

The frontend uses a single SDK client (`createClient`) with:
- REST methods for sessions/turns/events/permissions/context
- `subscribeEvents()` (SSE) which dispatches into stores

Stores (conceptual):
- `sessionsStore`: list/search/rename/delete, active session id
- `timelineStore`: per session timeline derived from events
- `inspectorStore`: active tab (Trace/Files/Terminal/Context/Permissions), selected step/part
- `permissionsStore`: pending permission requests, modal state
- `contextStore`: pinned/unpinned context items

Rendering:
- Chat Mode:
  - shows only user/assistant message stream
  - trace drawer summarizes tools/timing/tokens
- Agent Mode:
  - shows full event timeline grouped by step
- Inspector:
  - Trace: last N events and step summaries
  - Files: file_changes diffs
  - Terminal: terminal chunks (grouped by tool_call_id)
  - Context: pinned/unpinned items
  - Permissions: pending requests + history

## Security Model

Same-origin by default.

Auth (MVP):
- optional `FANFAN_AUTH_TOKEN` (bearer) for write endpoints
- dev mode can disable auth

CSP always set; dev may relax.

## Compatibility / Migration Strategy

1. Keep `/api/v1` as-is initially.
2. Introduce `/api/v2` + `/event` global bus in parallel.
3. Update frontend SDK to use `/api/v2` and `/event?session_id=...`.
4. Gradually migrate:
   - session list and history from v1 to v2
   - streaming protocol from legacy event types to the new stable set
5. Provide a one-time DB migration script to map legacy `messages` into `turns` (optional for MVP).
