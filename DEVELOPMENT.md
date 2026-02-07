# Development

## Prereqs

- Python 3.12+
- Node.js 20+ (for `frontend/` build)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .

cd frontend
npm install
cd ..
```

## Run (Dev Mode)

Dev mode keeps the browser same-origin by proxying the Vite dev server through the backend.

```bash
make dev
```

Defaults:

- backend: `http://127.0.0.1:4096`
- frontend (vite): `http://127.0.0.1:4444`

## Run (Static Build)

```bash
make build
make start
```

The built assets are emitted to `nanobot/web/static/dist/` and served by FastAPI.

## Tests

```bash
pytest -q
```

## Key Concepts

### SSE Event Bus

- Subscribe: `GET /event?session_id=...&since=...`
- Replay (JSON): `GET /api/v2/sessions/{id}/events?since=...`

The UI streams `message_delta` events into a single assistant bubble and renders tool calls/diffs in the trace.

### Runner Loop (Web)

`nanobot/web/runner.py` runs a tight loop:

1. Model streaming response
2. If tool calls: permission gate -> execute -> emit `tool_result` and optional `diff`
3. Repeat until `finish_reason != tool_use`

### Pinned Context Injection

Pinned context items are stored in SQLite table `context_items`.

- The UI can pin a doc/file ref using `POST /api/v2/sessions/{id}/context/set_pinned_ref`.
- The runner injects pinned items into the system prompt on every LLM call.
- Large pinned files are summarized and cached via `context_items.summary`, keyed by `summary_sha256`.

This is prompt-only injection (no additional tool calls are generated).
