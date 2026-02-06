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

echo "Deploying ${REMOTE_NAME}/${BRANCH} -> ${LIVE_DIR}"

cd "${LIVE_DIR}"
git fetch "${REMOTE_NAME}" --prune

# Force the working tree to match the remote branch.
# Only use this on the live directory, where you do NOT develop.
git checkout -B "${BRANCH}" "${REMOTE_NAME}/${BRANCH}"
git reset --hard "${REMOTE_NAME}/${BRANCH}"

echo "Deployed commit: $(git log --oneline -1)"
echo "NOTE: restart your service here (systemd/supervisor/nohup/etc.)"
