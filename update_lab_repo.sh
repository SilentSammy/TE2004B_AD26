#!/usr/bin/env bash
# Force the lab checkout to exactly match the latest published origin/main.
# Ignored files such as .venv are preserved.

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=${1:-$SCRIPT_DIR}

cd "$REPO_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a Git repository: $REPO_DIR" >&2
    exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
    echo "This repository has no 'origin' remote." >&2
    exit 1
fi

echo "Updating $REPO_DIR from origin/main..."
git fetch --prune origin main
git checkout -f -B main origin/main
git clean -fd

echo "Lab checkout now matches origin/main at:"
git --no-pager log -1 --oneline
