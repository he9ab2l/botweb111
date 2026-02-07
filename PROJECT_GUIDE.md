# Project Guide (Dev/Prod Workflow)

This document describes how the project is set up on the server, how to develop safely, and how production should be operated going forward.

It is intentionally pragmatic: minimal process, strong safety rails.

## Handoff Prompt (Copy/Paste)

Use this prompt when handing the project to a new engineer/agent.

```text
You are a senior full-stack execution agent taking over this repository. Your goal is to evolve the existing `nanobot` project to match the OpenCode-style agent UX/architecture and to rebrand the product to `fanfan`.

Operate with a strong bias for:
- verifying facts by reading the repo + checking the running instances
- making the smallest observable change that moves the system toward the target
- keeping the system runnable at every step

Only ask a question when it changes the architecture meaningfully and cannot be inferred. If you must ask, ask exactly ONE question, provide a recommended default, and state what would change.

## Fixed environment facts (server)
- Repo: https://github.com/he9ab2l/botweb111
- Production code: /opt/botweb111
- Service: botweb111.service (systemd)
- Local bind: 127.0.0.1:9936
- Reverse proxy: your domain -> 127.0.0.1:9936

## Project stack (repo)
- Backend: Python FastAPI + SSE
- Frontend: React + Vite + Tailwind
- DB: SQLite

Critical operational constraint:
- Frontend build output lives in nanobot/web/static/dist/ and is gitignored.
- Deploying code without rebuilding the frontend can make the UI appear unchanged.

## Target end state (must converge toward)
- OpenCode-style layout: left sessions/docs, center chat/docs, right inspector.
- Model settings in UI with server-side persistence (default + per-session override).
- Permission mode toggle (require approval vs allow all tools).
- Event model: stable SSE events (message_delta, thinking, tool_call, tool_result, diff, final).
- Tools: read/write/patch/search/fetch + subagents with approvals.

## How to deploy (production)

```bash
cd /opt/botweb111

git pull --ff-only
cd frontend && npm install && npm run build && cd ..

systemctl restart botweb111.service
curl -sS http://127.0.0.1:9936/api/v2/health
```

## Optional staging (dev branch)

If you want a staging instance, create a separate directory and port:

```bash
# Example layout
/opt/botweb111-dev  (branch: dev, port: 9937)
```

Example run command:

```bash
/opt/botweb111-dev/.venv/bin/python -m uvicorn nanobot.web.app:create_app \
  --factory --host 127.0.0.1 --port 9937 --log-level info
```

Then map a staging domain to 127.0.0.1:9937 via your reverse proxy.

## How to develop safely

- Work on branch dev, merge to main for production.
- Rebuild frontend after every UI change.
- Do not commit secrets. Use ~/.nanobot/config.json for API keys.
- Verify changes with:
  - /api/v2/health
  - /event (SSE)
  - UI: model switch + permission mode + docs view

## UI settings (runtime config)

- Model and API keys can be edited in the WebUI (Settings).
- Keys are stored in ~/.nanobot/config.json.
- Permission mode (require approval vs allow all) is stored in DB and applies globally.
