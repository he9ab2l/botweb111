# Project Guide (Dev/Prod Workflow)

This document describes how the project is set up on the server, how to develop safely, and how production should be operated going forward.

It is intentionally pragmatic: minimal process, strong safety rails.

## Handoff Prompt (Copy/Paste)

Use this prompt when handing the project to a new engineer/agent. It is written to bias toward verification (read code + check running behavior) and to avoid irreversible operations.

```text
You are a senior full-stack execution agent taking over this repository. Your goal is to refactor the existing `nanobot` project to match the OpenCode-style agent UX/architecture and to rebrand the product to `fanfan`.

Operate with a strong bias for:
- verifying facts by reading the repo + checking the running instances
- making the smallest observable change that moves the system toward the target
- keeping the system runnable at every step

Only ask a question when it changes the architecture meaningfully and cannot be inferred. If you must ask, ask exactly ONE question, provide a recommended default, and state what would change.

## Fixed environment facts (server)
- Repo: https://github.com/he9ab2l/botweb111
- Directories:
  - Work/dev: `/opt/nanobot-work`
  - Live/prod: `/opt/nanobot-live`
- Production:
  - Domain: `https://nanobot.heabl.xyz/`
  - Reverse proxy: `127.0.0.1:9936`
  - Process manager: systemd unit `nanobot-web.service`
- Preview/staging:
  - Domain: `https://workweb.heabl.xyz/`
  - Reverse proxy: `127.0.0.1:9937`
  - Process manager: currently `nohup` uvicorn
  - PID/log:
    - `/opt/nanobot-work/work-uvicorn.pid`
    - `/opt/nanobot-work/work-uvicorn.log`

## Project stack (repo)
- Backend: Python FastAPI + SSE
- Frontend: React + Vite + Tailwind
- DB: SQLite

Critical operational constraint:
- Frontend build output lives in `nanobot/web/static/dist/` and is gitignored.
- Therefore deploying code without rebuilding the frontend can make the UI appear unchanged/broken.

## Target end state (must converge toward)
- Product rename: `nanobot` -> `fanfan` across naming, UI strings, prompts, logs, package/service names (can be staged, but keep a plan).
- Execution model: `agent.run()` as a loop:
  - generate -> if tool calls: execute tools -> continue
  - else: final -> stop
- Event model: unify to a small stable set (OpenCode-like):
  - `message_delta`, `thinking`, `tool_call`, `tool_result`, `terminal_chunk`, `diff`, `final`, `error`
  - every event carries `session_id`, `turn_id`, `step_id`, `timestamp`, monotonic `seq`
- Transport: global SSE bus (`GET /event`) with:
  - `connected` + heartbeat
  - `Last-Event-ID` reconnect
  - event persistence + replay
- UI: three-column layout:
  - left: sessions/projects
  - center: turn/step/part execution timeline (foldable thinking, tool cards, diff highlight, terminal stream)
  - right: inspector tabs (Trace / Files / Terminal / Context / Permissions)
- Permissions: tool allow/deny/ask with a UI approval modal.
- Optional architecture: local API server proxies the UI at `/` (supports remote UI_URL or local built assets).

## Required deliverables (in order)
1) `DESIGN.md`: protocol, DB schema, SSE bus, API routes, frontend state model, permissions flow, migration strategy
2) Backend: SSE bus + event store/replay + session/turn/step/part + tool registry/permissions + agent loop + UI proxy
3) Frontend: three-column UI + SSE client + timeline rendering + inspector + permissions modal + diff/terminal viewers
4) Scripts/docs: dev/build/start + README updates + demo/self-check checklist

## Mandatory workflow/safety rules
- NEVER edit `/opt/nanobot-live` directly. Do work in `/opt/nanobot-work` and deploy via script.
- Avoid destructive git operations (e.g. `reset --hard`, force-push) unless explicitly requested by the user.
- Do not commit/push unless explicitly asked.
- Never include secrets in commits (`~/.nanobot/config.json` holds runtime config).

## First 30 minutes (verification checklist)
Run these commands to establish ground truth:

1) Confirm branches and dirty state:
   - `git -C /opt/nanobot-work status`
   - `git -C /opt/nanobot-work rev-parse --abbrev-ref HEAD`
   - `git -C /opt/nanobot-live status`
   - `git -C /opt/nanobot-live rev-parse --abbrev-ref HEAD`

2) Confirm services are healthy:
   - `curl -sS http://127.0.0.1:9936/api/v1/health`
   - `curl -sS http://127.0.0.1:9937/api/v1/health`
   - `systemctl status nanobot-web.service --no-pager -n 50`

3) Confirm frontend build expectations:
   - `ls -la /opt/nanobot-work/nanobot/web/static/dist/`
   - `cd /opt/nanobot-work/frontend && npm ci && npm run build`

## How to proceed when implementing
- Make changes as a sequence of small, observable slices; after each slice, verify via browser and/or curl.
- Prefer adding new parallel endpoints/types first (behind feature flags if needed), then migrating callers, then removing old paths.
- Every response you give should state:
  - what changed
  - which files
  - how to verify
  - 1-2 concrete next commands
```

## Current State (What Exists Today)

### Two running instances (physical isolation)

- Production ("live")
  - Purpose: stable, user-facing
  - Reverse proxy: `nanobot.heabl.xyz` -> `127.0.0.1:9936`
  - Code directory: `/opt/nanobot-live`
  - Process: `systemd` service `nanobot-web.service` (binds `127.0.0.1:9936`)

- Preview/Staging ("work")
  - Purpose: development preview, safe to change
  - Reverse proxy: `workweb.heabl.xyz` -> `127.0.0.1:9937`
  - Code directory: `/opt/nanobot-work`
  - Process: currently started via `nohup` (binds `127.0.0.1:9937`)

This separation means: you can iterate quickly on `work` without risking `live`.

### GitHub repository + branches

- Repo: `git@github.com:he9ab2l/botweb111.git`
- Branches:
  - `main`: deployable stable branch (production should only deploy from here)
  - `dev`: daily development branch (preview/staging should track this)
- Tagging:
  - `v0.1.0`: initial stable tag (example baseline for rollback)

Important note about the server right now:

- `/opt/nanobot-live` tracks your repo (`he9ab2l/botweb111`) on branch `main` and is what production runs.
- `/opt/nanobot-work` tracks your repo (`he9ab2l/botweb111`) on branch `dev` and is what preview runs.
- `/opt/nanobot` is legacy/old and should be treated as rollback-only (do not develop there).

## Target Operating Rules (How We Work From Now On)

### Rule 1: Never edit production code in place

- Do NOT directly edit files in `/opt/nanobot-live`.
- All edits happen in `/opt/nanobot-work`.

### Rule 2: Development happens on `dev`

Typical cycle:

1. Work in `/opt/nanobot-work` on branch `dev`.
2. Validate on preview domain (`workweb.heabl.xyz`).
3. Create a PR: `dev -> main`.
4. Merge PR.
5. Deploy production from `main` only.

### Rule 3: Always keep a rollback point

- For each production release, ensure there is a Git tag (or at minimum a known commit SHA).
- Rollback is then `git checkout <tag-or-sha>` (or deploying that tag) + restart service.

## How To Develop (Preview /opt/nanobot-work)

### Start/stop the preview server

Preview server is currently run via `nohup` and writes:

- PID file: `/opt/nanobot-work/work-uvicorn.pid`
- Log file: `/opt/nanobot-work/work-uvicorn.log`

Suggested commands:

```bash
# stop
kill $(cat /opt/nanobot-work/work-uvicorn.pid)

# start
nohup /opt/nanobot-work/.venv/bin/python -m uvicorn nanobot.web.app:create_app \
  --factory --host 127.0.0.1 --port 9937 --log-level info \
  > /opt/nanobot-work/work-uvicorn.log 2>&1 &
echo $! > /opt/nanobot-work/work-uvicorn.pid

# health check
curl -sS http://127.0.0.1:9937/api/v1/health
```

### Frontend build

The web server serves built frontend assets from `nanobot/web/static/dist/`.

PWA note:

- The PWA assets are served from the site root (e.g. `/manifest.webmanifest`, `/sw.js`, `/icons/*`).
- After updating the frontend, rebuild so these files are refreshed.

```bash
cd /opt/nanobot-work/frontend
npm install
npm run build
```

## How Production Runs (Today)

- systemd unit: `/etc/systemd/system/nanobot-web.service`
  - WorkingDirectory: `/opt/nanobot-live`
  - Uvicorn bind: `127.0.0.1:9936`

Useful commands:

```bash
systemctl status nanobot-web.service --no-pager -n 50
systemctl restart nanobot-web.service
curl -sS http://127.0.0.1:9936/api/v1/health
```

## Deployment (What We Want Next)

### Minimal deploy script (already added)

In the repo there is a minimal deploy helper:

- `/opt/nanobot-work/deploy.sh`

It force-syncs a live directory to `origin/main`.

It also rebuilds the frontend and restarts the service by default.

Why this matters:

- The frontend build output (`nanobot/web/static/dist/`) is gitignored, so simply updating the git commit is not enough.
- If you deploy new backend event protocol changes without rebuilding the frontend, the web UI can appear broken (no streaming / no tool trace).

In this server setup, production lives at `/opt/nanobot-live`.

Usage:

```bash
cd /opt/nanobot-work
./deploy.sh
```

Optional flags:

```bash
# deploy code only
BUILD_FRONTEND=0 RESTART_SERVICE=0 ./deploy.sh
```

## Security / Secrets

- Never commit tokens, API keys, or `.env` files.
- Prefer `~/.nanobot/config.json` for runtime configuration.
- `.gitignore` is set up to ignore common sensitive/runtime files (e.g. `data/`, `*.db`, `*.log`, `*.pid`).

## What Was Simplified (Channels)

Channels have been simplified to reduce maintenance surface:

- Kept: `Telegram` channel
- Removed: WhatsApp/Discord/Feishu channel implementations and WhatsApp bridge

Web UI remains available via the `nanobot.web` FastAPI app.

## Quick Checks (When Something Breaks)

```bash
# production health
curl -sS https://nanobot.heabl.xyz/api/v1/health

# preview health
curl -sS https://workweb.heabl.xyz/api/v1/health

# check ports
ss -ltnp | awk 'NR==1 || $4 ~ /:9936|:9937/'
```

## Rollback (If Production Deployment Breaks)

The immediate rollback path is the legacy directory:

- `/opt/nanobot` (old live)

Rollback steps (high-level):

1. Edit `/etc/systemd/system/nanobot-web.service` to point back to `/opt/nanobot`.
2. Run `systemctl daemon-reload`.
3. Run `systemctl restart nanobot-web.service`.
