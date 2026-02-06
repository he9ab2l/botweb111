#!/usr/bin/env bash
set -euo pipefail

# deploy.sh - minimal deploy helper
#
# Goal: make production updates repeatable and reversible.
# - Production (live) should track origin/main
# - Staging (work) should track origin/dev
#
# This script is intentionally simple. Adjust service restart commands to your environment.

LIVE_DIR="${LIVE_DIR:-/opt/nanobot-live}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-main}"
BUILD_FRONTEND="${BUILD_FRONTEND:-1}"
RESTART_SERVICE="${RESTART_SERVICE:-1}"
SERVICE_NAME="${SERVICE_NAME:-nanobot-web.service}"

echo "Deploying ${REMOTE_NAME}/${BRANCH} -> ${LIVE_DIR}"

if [[ "${LIVE_DIR}" == "/opt/nanobot-work" ]]; then
  echo "ERROR: LIVE_DIR points to /opt/nanobot-work (refusing)."
  exit 2
fi

cd "${LIVE_DIR}"
git fetch "${REMOTE_NAME}" --prune

# Force the working tree to match the remote branch.
# Only use this on the live directory, where you do NOT develop.
git checkout -B "${BRANCH}" "${REMOTE_NAME}/${BRANCH}"
git reset --hard "${REMOTE_NAME}/${BRANCH}"

echo "Deployed commit: $(git log --oneline -1)"

if [[ "${BUILD_FRONTEND}" == "1" ]]; then
  if [[ -d "frontend" ]]; then
    echo "Building frontend (this updates nanobot/web/static/dist/)"
    pushd frontend >/dev/null
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
    npm run build
    popd >/dev/null
  else
    echo "WARN: frontend/ not found, skipping frontend build"
  fi
else
  echo "Skipping frontend build (BUILD_FRONTEND=${BUILD_FRONTEND})"
fi

if [[ "${RESTART_SERVICE}" == "1" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    echo "Restarting service: ${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    systemctl status "${SERVICE_NAME}" --no-pager -n 20 || true
  else
    echo "WARN: systemctl not found, skipping service restart"
  fi
else
  echo "Skipping service restart (RESTART_SERVICE=${RESTART_SERVICE})"
fi
