#!/usr/bin/env bash
set -euo pipefail

# deploy.sh - minimal deploy helper
#
# Goal: make production updates repeatable and reversible.
# - Production (live) should track origin/main
# - Staging (work) should track origin/dev
#
# This script is intentionally simple. Adjust service restart commands to your environment.

LIVE_DIR="${LIVE_DIR:-/opt/nanobot}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH="${BRANCH:-main}"

echo "Deploying ${REMOTE_NAME}/${BRANCH} -> ${LIVE_DIR}"

# Validate that LIVE_DIR exists and is a git repository
if [ ! -d "${LIVE_DIR}" ]; then
    echo "ERROR: LIVE_DIR '${LIVE_DIR}' does not exist." >&2
    exit 1
fi

if [ ! -d "${LIVE_DIR}/.git" ]; then
    echo "ERROR: LIVE_DIR '${LIVE_DIR}' is not a git repository." >&2
    exit 1
fi

cd "${LIVE_DIR}"

# Verify we're in a git worktree
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: LIVE_DIR '${LIVE_DIR}' is not inside a git work tree." >&2
    exit 1
fi

git fetch "${REMOTE_NAME}" --prune

# Force the working tree to match the remote branch.
# Only use this on the live directory, where you do NOT develop.
# NOTE: This preserves untracked files (e.g., local configs, logs).
# To remove untracked files, run: git clean -fd
git checkout -B "${BRANCH}" "${REMOTE_NAME}/${BRANCH}"
git reset --hard "${REMOTE_NAME}/${BRANCH}"

echo "Deployed commit: $(git log --oneline -1)"
echo "NOTE: restart your service here (systemd/supervisor/nohup/etc.)"
