#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-4096}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-4444}"

export FANFAN_UI_MODE="${FANFAN_UI_MODE:-dev}"
export FANFAN_UI_DEV_SERVER_URL="${FANFAN_UI_DEV_SERVER_URL:-http://${FRONTEND_HOST}:${FRONTEND_PORT}}"

cd "$ROOT_DIR"

PY="${PYTHON:-$ROOT_DIR/.venv/bin/python}"

cleanup() {
  if [[ -n "${BACK_PID:-}" ]]; then
    kill "$BACK_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[dev] backend: http://${BACKEND_HOST}:${BACKEND_PORT} (UI proxied from ${FANFAN_UI_DEV_SERVER_URL})"
echo "[dev] frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT} (vite)"

# Start backend first so the browser can always use the same origin.
$PY -m uvicorn nanobot.web.app:create_app --factory \
  --host "$BACKEND_HOST" --port "$BACKEND_PORT" --log-level info &
BACK_PID=$!

cd "$ROOT_DIR/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"

