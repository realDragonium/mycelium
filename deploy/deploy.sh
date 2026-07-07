#!/usr/bin/env bash
# Push the local mycelium checkout to a remote server and restart the
# service. Run from your laptop. Assumes the server has already been
# bootstrapped with `deploy/install-server.sh`.
#
# Configure via env vars (or edit defaults below):
#   MYC_SSH_HOST   — e.g. mycelium@your-vps.example.com
#   MYC_SSH_PORT   — defaults to 22
#   MYC_REMOTE_DIR — defaults to /opt/mycelium
#   MYC_SERVICE    — defaults to mycelium
#
# Usage:
#   MYC_SSH_HOST=root@1.2.3.4 deploy/deploy.sh
#   MYC_SSH_HOST=root@1.2.3.4 deploy/deploy.sh --skip-restart
#
# What gets shipped: everything under the repo root except common
# transient/non-source paths (see EXCLUDES). uv on the remote installs
# the deps from pyproject.toml + uv.lock so dependency state is
# deterministic across deploys.

set -euo pipefail

SSH_HOST="${MYC_SSH_HOST:-}"
# Port is optional: if unset, defer to whatever `~/.ssh/config` says for
# this host alias. Explicit override wins when you need to bypass the
# config (one-off deploys to a different port).
SSH_PORT="${MYC_SSH_PORT:-}"
REMOTE_DIR="${MYC_REMOTE_DIR:-/opt/mycelium}"
SERVICE="${MYC_SERVICE:-mycelium}"
SKIP_RESTART=0

for arg in "$@"; do
    case "$arg" in
        --skip-restart) SKIP_RESTART=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown arg: $arg" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$SSH_HOST" ]]; then
    echo "MYC_SSH_HOST is required (e.g. MYC_SSH_HOST=root@1.2.3.4)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Exclude lists ride alongside the script so they stay version-controlled.
EXCLUDES=(
    --exclude '.git'
    --exclude '.venv'
    --exclude '__pycache__'
    --exclude '*.pyc'
    --exclude '.mycelium'        # local data dir; the server has its own
    --exclude '.env'             # local secrets; prod uses /etc/mycelium.env
    --exclude '.pytest_cache'
    --exclude '.ruff_cache'
    --exclude 'node_modules'
    --exclude 'tests'            # don't ship tests to prod
    --exclude 'bench'
    --exclude '*.log'
    --exclude 'anns.json'        # local cache
    --exclude 'entity-positions.json'
    --exclude 'cleanup_log.jsonl'
)

# Rsync into a staging dir under the SSH user's home (no sudo needed),
# then a single TTY-allocated SSH call moves it into place as root and
# runs uv sync as the mycelium user. Keeps the rsync transfer itself
# sudo-free, so the only password prompt is the final ssh call.
STAGE_DIR="\$HOME/.mycelium-staging"

echo "==> rsync $REPO_ROOT/ → $SSH_HOST:~/.mycelium-staging/"
rsync -avz --delete -e "ssh${SSH_PORT:+ -p $SSH_PORT}" \
    "${EXCLUDES[@]}" \
    "$REPO_ROOT/" "$SSH_HOST:.mycelium-staging/"

echo "==> remote: install + uv sync (will prompt for sudo password)"
# The remote rsync uses --delete to keep the app dir clean of stale
# source files, but the mycelium user's HOME is /opt/mycelium too —
# uv and its caches live there. Preserve those across deploys.
ssh -t ${SSH_PORT:+-p "$SSH_PORT"} "$SSH_HOST" "
    set -e
    sudo rsync -a --delete \
        --exclude='.local/' --exclude='.cache/' --exclude='.venv/' \
        $STAGE_DIR/ '$REMOTE_DIR/'
    sudo chown -R mycelium:mycelium '$REMOTE_DIR'
    sudo -u mycelium -H bash -lc \"cd '$REMOTE_DIR' && /opt/mycelium/.local/bin/uv sync --frozen\"
"

if [[ "$SKIP_RESTART" -eq 1 ]]; then
    echo "==> skipping restart (--skip-restart)"
    exit 0
fi

echo "==> remote: restart $SERVICE"
ssh -t ${SSH_PORT:+-p "$SSH_PORT"} "$SSH_HOST" "sudo systemctl restart $SERVICE && sudo systemctl is-active --quiet $SERVICE && echo 'active' || (sudo journalctl -u $SERVICE -n 50 --no-pager; exit 1)"

echo "==> done"
