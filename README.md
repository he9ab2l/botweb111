# fanfan

`fanfan` is a self-hosted AI agent with an OpenCode-style WebUI.

Stack:
- Backend: FastAPI + SSE
- Frontend: React + Vite + Tailwind
- DB: SQLite (default)

## What You Get (MVP)

- Two-stage WebUI (same-origin):
  - UI served or reverse-proxied at `/`
  - API at `/api/v2/*`
- Global SSE event bus:
  - `GET /event` (reconnect + replay)
  - `connected` + `heartbeat`
- Execution model:
  - session -> turn -> step -> parts (events)
  - OpenCode-style agent loop: tool_call -> tool_result -> continue -> final
- Tools (with permissions):
  - `read_file`, `write_file`, `apply_patch`, `search`, `http_fetch`, `spawn_subagent`
  - Permission gate: `deny | ask | allow` + UI approval modal
  - No shell/CLI tool is exposed in the WebUI.
- Inspector tabs:
  - Trace / Files / Context / Permissions

## Quick Start

### 1) Configure LLM (required)

Create `~/.nanobot/config.json` (copy from `config.example.json`) and set at least one provider apiKey:

```bash
mkdir -p ~/.nanobot
cp ./config.example.json ~/.nanobot/config.json
```

### 2) Build UI (static mode)

```bash
make build
```

### 3) Start Server

```bash
make start
```

Open:
- `http://localhost:4096`

Health:
- `GET /healthz`

## Dev Mode (Two-Stage, Same-Origin)

Starts:
- backend: `127.0.0.1:4096`
- frontend dev server: `127.0.0.1:4444`
- backend proxies the dev server at `/` (API stays same-origin)

```bash
make dev
```

## Configuration (.env)

Copy:

```bash
cp .env.example .env
```

Key variables:
- `FANFAN_UI_MODE`: `static | dev | remote`
- `FANFAN_UI_URL`: remote UI origin when `remote`
- `FANFAN_UI_DEV_SERVER_URL`: dev server origin when `dev`
- `FANFAN_DB_PATH`: override DB path (default: `./data/fanfan.db`)
- `FANFAN_FS_ROOT`: allowed root for file tools (`read_file`/`write_file`/`apply_patch`) (default: repo root)
- `FANFAN_TOOL_POLICY_DEFAULT`: `deny | ask | allow`
- `FANFAN_TOOL_POLICY_READ_FILE`, etc

## API (v2)

Sessions:
- `POST /api/v2/sessions`
- `GET /api/v2/sessions`
- `GET /api/v2/sessions/{id}`

Turns:
- `POST /api/v2/sessions/{id}/turns` `{ content }`
- `POST /api/v2/sessions/{id}/cancel`

Events:
- `GET /event?session_id=...&since=...` (SSE)
- `GET /api/v2/sessions/{id}/events?since=...` (replay JSON)

Inspector:
- `GET /api/v2/sessions/{id}/file_changes`
- `GET /api/v2/sessions/{id}/context`
- `GET /api/v2/sessions/{id}/permissions/pending`
- `POST /api/v2/permissions/{request_id}/resolve`

FS (File Tree + Versions):
- `GET /api/v2/sessions/{id}/fs/tree`
- `GET /api/v2/sessions/{id}/fs/read?path=...`
- `GET /api/v2/sessions/{id}/fs/versions?path=...`
- `GET /api/v2/sessions/{id}/fs/version/{version_id}`
- `POST /api/v2/sessions/{id}/fs/rollback`

Export:
- `GET /api/v2/sessions/{id}/export.json`
- `GET /api/v2/sessions/{id}/export.md`

## Self-Check Checklist

1. SSE bus + heartbeat:
   - open UI, confirm connection indicator turns green
   - `curl -N http://localhost:4096/event`
2. Streaming:
   - send a message, watch assistant text stream
3. Permission modal:
   - ask fanfan to run a tool, approve once
4. Subagent tree:
   - ask fanfan to use `spawn_subagent` for a focused task, open the tool card and inspect nested events
5. Diff + versions:
   - ask to `write_file` or `apply_patch`, observe diff in timeline and Files tab
   - open Files tab, preview file versions, and rollback

## Design

See `DESIGN.md` for protocol, routes, DB schema, and migration strategy.
