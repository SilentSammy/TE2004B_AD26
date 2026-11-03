#!/usr/bin/env bash
# Update any checkout to exactly match the latest published origin/main.
# Ignored files such as .venv are preserved.
# Usage: bash update_repo.sh [path/to/checkout]

set -euo pipefail

update_repo() {
    if [[ ${1:-} == --help || ${1:-} == -h ]]; then
        echo "Usage: bash update_repo.sh [path/to/checkout]"
        echo "Replaces local changes and untracked files with origin/main; ignored files are preserved."
        return 0
    fi
    if (( $# > 1 )); then
        echo "Usage: bash update_repo.sh [path/to/checkout]" >&2
        return 1
    fi

    local script_dir repo_dir
    script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    repo_dir=${1:-$script_dir}
    cd -- "$repo_dir"

    if [[ $(git rev-parse --is-inside-work-tree 2>/dev/null) != true ]]; then
        echo "Not a Git working tree: $repo_dir" >&2
        return 1
    fi
    repo_dir=$(git rev-parse --show-toplevel)
    cd -- "$repo_dir"

    if ! git remote get-url origin >/dev/null 2>&1; then
        echo "This repository has no 'origin' remote." >&2
        return 1
    fi

    echo "Updating $repo_dir from origin/main..."
    # Fetch must succeed before any local changes are discarded. An explicit
    # refspec also supports clones whose fetch configuration omits main.
    git fetch --prune origin '+refs/heads/main:refs/remotes/origin/main'
    git checkout -f -B main origin/main
    git clean -fd

    echo "Checkout now matches origin/main at:"
    git --no-pager log -1 --oneline
}

# Load the whole function before updating: checkout/clean may replace this script.
update_repo "$@"
