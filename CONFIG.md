# Configuration

`fanfan` uses two configuration layers:

1. Web runtime settings (environment / `.env`)
2. LLM provider settings (stored in `~/.nanobot/config.json`, editable via WebUI)

The WebUI settings panel calls `POST /api/v2/config`, which updates `~/.nanobot/config.json`.

## 1) Web Runtime Settings (.env)

The FastAPI app reads `FANFAN_*` variables via `nanobot/web/settings.py`.

Common keys:

- `FANFAN_HOST` (default `0.0.0.0`)
- `FANFAN_PORT` (default `4096`)
- `FANFAN_DATA_DIR` (default `data`)
- `FANFAN_DB_PATH` (optional, overrides DB location)
- `FANFAN_FS_ROOT` (default `.`)
  - The allowed root for `read_file`, `write_file`, `apply_patch`
- `FANFAN_UI_MODE` (default `static`)
  - `static`: serve built UI from `FANFAN_UI_STATIC_DIR`
  - `dev`: proxy Vite dev server from `FANFAN_UI_DEV_SERVER_URL`
  - `remote`: proxy a remote UI origin from `FANFAN_UI_URL`
- `FANFAN_TOOL_POLICY_DEFAULT` (default `ask`)
  - `deny | ask | allow`
- `FANFAN_TOOL_POLICY_READ_FILE`, `FANFAN_TOOL_POLICY_WRITE_FILE`, etc (optional overrides)
- `FANFAN_TOOL_ENABLED_READ_FILE`, etc (feature flags)

Notes:

- The helper scripts use `BACKEND_HOST`/`BACKEND_PORT` to set the uvicorn bind address.
- `.env` affects the app settings because `WebSettings` loads `.env` directly.

## 2) Provider Settings (Saved on Server)

Providers and the default model are stored in `~/.nanobot/config.json`.

You can edit it directly or use the WebUI Settings panel.

Example keys:

- `providers.openai.apiKey`
- `providers.anthropic.apiKey`
- `providers.openrouter.apiKey`
- `providers.zhipu.apiKey` (GLM / Z.ai)
- `providers.<provider>.apiBase` (optional)

Model naming convention:

- `openai/gpt-4o`
- `anthropic/claude-opus-4-5`
- `openrouter/stepfun/step-3.5-flash:free`
- `openrouter/anthropic/claude-3.5-sonnet`
- `zai/glm-4.7` (GLM via Z.ai)
- `zai/glm-4`

Per-session model override:

- The UI can set a session model override.
- Stored in SQLite table `session_settings`.

## Permissions Mode

The WebUI supports a global permission mode:

- `ask`: tools require approval in a modal
- `allow`: run all tool calls without prompting

API:

- `GET /api/v2/permissions/mode`
- `POST /api/v2/permissions/mode` `{ mode: "ask" | "allow" }`

## Pinned Context

The UI can pin docs/files/URLs as session context items. Pinned items are injected into the system prompt on every model call.

- Large pinned files are summarized and cached (sha256-based) in `context_items.summary*`.

API:

- `GET /api/v2/sessions/{id}/context`
- `POST /api/v2/sessions/{id}/context/set_pinned_ref` `{ kind, title?, content_ref, pinned }`
