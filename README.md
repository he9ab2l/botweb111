# fanfan

`fanfan` is a self-hosted AI agent with an OpenCode-style WebUI.

Stack:
- Backend: FastAPI + SSE
- Frontend: React + Vite + Tailwind
- DB: SQLite (default)

## What You Get

- OpenCode-style 3-column UI:
  - left: sessions + docs
  - center: chat/docs timeline
  - right: inspector (Trace / Files / Context / Permissions)
- View modes:
  - Chat / Docs / Agent
- Model management (saved on server):
  - global default model
  - per-session override
  - editable via WebUI settings
- Providers:
  - OpenAI / Anthropic / OpenRouter / DeepSeek / Gemini / Groq / Moonshot / vLLM / GLM (Z.ai)
  - GLM uses `zai/` prefix (example: `zai/glm-4`)
- Docs/knowledge panel:
  - built-in project docs + auto-discovered markdown
  - pin docs/files into session context (auto-injected into prompts; large items summarized + cached)
  - APIs: `/api/v2/docs`, `/api/v2/docs/file?path=...`
- Tools (with permissions):
  - `read_file`, `write_file`, `apply_patch`, `search`, `http_fetch`, `spawn_subagent`
  - permission gate: `deny | ask | allow` + UI approval modal
  - global permission mode toggle: require approval or allow all
  - no shell/CLI tool exposed in the WebUI

## Quick Start

### 1) Configure LLM (required)

You can edit the config file or use the WebUI settings panel.

Config file (copy template and fill at least one provider key):

```bash
mkdir -p ~/.nanobot
cp ./config.example.json ~/.nanobot/config.json
```

WebUI settings (recommended):
- open the UI
- click `Settings`
- add API key and choose model

GLM/Z.ai example:
- provider key: `providers.zhipu.apiKey`
- model: `zai/glm-4` or `zai/glm-4-plus`

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
- `GET /api/v2/health`

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
- `FANFAN_FS_ROOT`: allowed root for file tools (default: repo root)
- `FANFAN_TOOL_POLICY_DEFAULT`: `deny | ask | allow`
- `FANFAN_TOOL_POLICY_READ_FILE`, etc

## API (v2)

Config / Models:
- `GET /api/v2/config`
- `POST /api/v2/config`
- `GET /api/v2/sessions/{id}/model`
- `POST /api/v2/sessions/{id}/model`
- `DELETE /api/v2/sessions/{id}/model`

Docs:
- `GET /api/v2/docs`
- `GET /api/v2/docs/file?path=...`

Sessions:
- `POST /api/v2/sessions`
- `GET /api/v2/sessions`
- `GET /api/v2/sessions/{id}`
- `PATCH /api/v2/sessions/{id}`
- `DELETE /api/v2/sessions/{id}`

Turns:
- `POST /api/v2/sessions/{id}/turns` `{ content }`
- `POST /api/v2/sessions/{id}/cancel`

Events:
- `GET /event?session_id=...&since=...` (SSE)
- `GET /api/v2/sessions/{id}/events?since=...` (replay JSON)

Permissions:
- `GET /api/v2/permissions/mode`
- `POST /api/v2/permissions/mode`
- `GET /api/v2/sessions/{id}/permissions/pending`
- `POST /api/v2/permissions/{request_id}/resolve`

Inspector:
- `GET /api/v2/sessions/{id}/file_changes`
- `GET /api/v2/sessions/{id}/context`
- `POST /api/v2/sessions/{id}/context/pin` `{ context_id }`
- `POST /api/v2/sessions/{id}/context/unpin` `{ context_id }`
- `POST /api/v2/sessions/{id}/context/set_pinned_ref` `{ kind, title?, content_ref, pinned }`
- `GET /api/v2/sessions/{id}/terminal`

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
3. Permission mode:
   - open `Settings` and toggle Require Approval / Allow All
4. Permission modal:
   - ask fanfan to run a tool, approve once
5. Docs:
   - open `Docs` mode and select a document from the sidebar
6. Diff + versions:
   - ask to `write_file` or `apply_patch`, observe diff in timeline and Files tab
   - open Files tab, preview file versions, and rollback

## Design

See `DESIGN.md` for protocol, routes, DB schema, and migration strategy.

More:
- See `CONFIG.md` for configuration and providers
- See `DEVELOPMENT.md` for local development
- See `DEPLOY.md` for server deployment
