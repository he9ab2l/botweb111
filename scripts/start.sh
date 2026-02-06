#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-4096}"

export FANFAN_UI_MODE="${FANFAN_UI_MODE:-static}"

cd "$ROOT_DIR"

PY="${PYTHON:-$ROOT_DIR/.venv/bin/python}"

exec $PY -m uvicorn nanobot.web.app:create_app --factory \
  --host "$BACKEND_HOST" --port "$BACKEND_PORT" --log-level info

