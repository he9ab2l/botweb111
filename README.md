# botweb111

A self-hosted AI chat agent with a web UI. Python (FastAPI + SSE) backend with a React (Vite + Tailwind) frontend.

## Features

- **Streaming responses** via Server-Sent Events (SSE)
- **Dual mode UI** — Chat mode (clean conversation view) and Agent mode (full execution trace)
- **Mobile-friendly layout** — drawer sidebar/inspector with safe-area padding
- **PWA support** — installable web app (manifest + service worker)
- **Tool execution** — the agent can run tools, apply patches, and show thinking steps
- **Session persistence** — conversations are stored in SQLite and survive restarts
- **Auto session naming** — sessions are automatically titled by the LLM
- **Trace drawer** — compact execution summary in chat mode (tool count, thinking time)
- **Inspector panel** — developer-console style side panel for examining events
- **Keyboard shortcuts** — Ctrl+K search, Esc to close panels
- **Optimistic UI** — messages appear instantly before server confirms

## Architecture

```
browser  <──SSE──>  FastAPI (uvicorn)  <──>  LLM API (any litellm-compatible model)
                         │
                     SQLite DB
                   (sessions, messages, events, memory)
```

## Project Structure

```
botweb111/
├── nanobot/
│   ├── web/
│   │   ├── app.py          # FastAPI app, REST + SSE endpoints
│   │   ├── database.py     # SQLite DAO
│   │   ├── events.py       # EventHub for SSE broadcasting
│   │   ├── protocol.py     # Event protocol definitions
│   │   └── static/dist/    # Built frontend (served by FastAPI)
│   ├── agent/
│   │   ├── loop.py         # Agent loop (LLM <-> tool execution)
│   │   ├── context.py      # Prompt builder
│   │   ├── memory.py       # Persistent memory
│   │   └── tools/          # Built-in tools
│   ├── providers/          # LLM provider adapters
│   ├── config/             # Configuration
│   └── cli/                # CLI commands
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Main app, Chat/Agent toggle
│   │   ├── components/
│   │   │   ├── ChatTimeline.jsx   # Dual-mode message timeline
│   │   │   ├── MessageBlock.jsx   # Chat bubbles / agent timeline
│   │   │   ├── TraceDrawer.jsx    # Execution summary drawer
│   │   │   ├── Inspector.jsx      # Event inspector panel
│   │   │   ├── Sidebar.jsx        # Session list
│   │   │   ├── InputArea.jsx      # Message input
│   │   │   ├── ThinkingBlock.jsx  # LLM thinking display
│   │   │   ├── ToolUseBlock.jsx   # Tool execution display
│   │   │   ├── PatchBlock.jsx     # Code patch display
│   │   │   ├── ErrorBlock.jsx     # Error display
│   │   │   ├── CodeBlock.jsx      # Syntax-highlighted code
│   │   │   └── ScrollToBottom.jsx # Auto-scroll button
│   │   ├── hooks/
│   │   │   └── useEventStream.js  # SSE connection hook
│   │   └── api.js                 # REST API client
│   ├── tailwind.config.js
│   └── vite.config.js
├── pyproject.toml
├── Dockerfile
└── LICENSE (MIT)
```

## Deploy

### Prerequisites

- Python >= 3.11
- Node.js >= 18
- An LLM API key (OpenRouter, Anthropic, OpenAI, ZhiPu, etc.)

### 1. Clone

```bash
git clone https://github.com/he9ab2l/botweb111.git
cd botweb111
```

### 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### 3. Build frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

Important:

- Run `npm` commands inside `frontend/` only.
- The backend does not have Node dependencies.

The build output goes to `nanobot/web/static/dist/` and is served by FastAPI automatically.

### 4. Configure

Create `~/.nanobot/config.json` (quick start: copy `config.example.json` and edit keys):

```bash
mkdir -p ~/.nanobot
cp ./config.example.json ~/.nanobot/config.json
```

Example:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

If the API key is not configured, opening the web UI will show a setup page instead of the chat UI.

### 5. Run

```bash
source .venv/bin/activate
python -m uvicorn nanobot.web.app:create_app --factory --host 127.0.0.1 --port 9936
```

Open `http://localhost:9936` in your browser.

### Production (systemd + reverse proxy)

systemd unit example:

```ini
[Unit]
Description=botweb111
After=network.target

[Service]
WorkingDirectory=/opt/botweb111
ExecStart=/opt/botweb111/.venv/bin/python -m uvicorn nanobot.web.app:create_app --factory --host 127.0.0.1 --port 9936
Restart=always

[Install]
WantedBy=multi-user.target
```

Caddy reverse proxy example:

```
yourdomain.example {
    reverse_proxy 127.0.0.1:9936
}
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sessions` | List all sessions |
| POST | `/api/v1/sessions` | Create a new session |
| GET | `/api/v1/sessions/{id}/messages` | Get message history |
| GET | `/api/v1/sessions/{id}/events` | SSE event stream |
| POST | `/api/v1/sessions/{id}/messages` | Send a message |

## License

MIT
