#!/usr/bin/env bash
# Push the local mycelium checkout to a remote server, snapshot its data
# and restart into the new build. Run from your laptop. Assumes the server
# has already been bootstrapped with `deploy/install-server.sh`.
#
# Configure via env vars (or edit defaults below):
#   MYC_SSH_HOST        — e.g. mycelium@your-vps.example.com
#   MYC_SSH_PORT        — defaults to whatever ~/.ssh/config says
#   MYC_REMOTE_DIR      — defaults to /opt/mycelium
#   MYC_SERVICE         — defaults to mycelium
#   MYC_DATA_DIR        — defaults to /var/lib/mycelium
#   MYC_SNAPSHOT_DIR    — defaults to /var/lib/mycelium-snapshots
#   MYC_KEEP_SNAPSHOTS  — defaults to 5
#
# Usage:
#   MYC_SSH_HOST=root@1.2.3.4 deploy/deploy.sh
#   MYC_SSH_HOST=root@1.2.3.4 deploy/deploy.sh --skip-restart
#
# Before installing the new build the server stops the service and copies
# the data dir to $MYC_SNAPSHOT_DIR/<UTC time>/, keeping the newest
# $MYC_KEEP_SNAPSHOTS. If the snapshot fails the deploy aborts and the
# current build is started again. --skip-restart installs without stopping,
# snapshotting or restarting (first deploy). The server side is
# deploy/release.sh.
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
DATA_DIR="${MYC_DATA_DIR:-/var/lib/mycelium}"
SNAPSHOT_DIR="${MYC_SNAPSHOT_DIR:-/var/lib/mycelium-snapshots}"
KEEP_SNAPSHOTS="${MYC_KEEP_SNAPSHOTS:-5}"
SKIP_RESTART=

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
    --exclude '*.log'
    --exclude 'anns.json'        # local cache
    --exclude 'entity-positions.json'
    --exclude 'cleanup_log.jsonl'
)

# Which build this is, recorded on the server and in each snapshot so a
# rollback knows what to redeploy.
BUILD="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
git -C "$REPO_ROOT" diff --quiet HEAD -- || BUILD="$BUILD-dirty"

# Rsync into a staging dir under the SSH user's home (no sudo needed), then
# one TTY-allocated SSH call runs release.sh from it, so the only password
# prompt is sudo's.
echo "==> rsync $REPO_ROOT/ → $SSH_HOST:~/.mycelium-staging/"
rsync -avz --delete -e "ssh${SSH_PORT:+ -p $SSH_PORT}" \
    "${EXCLUDES[@]}" \
    "$REPO_ROOT/" "$SSH_HOST:.mycelium-staging/"

echo "==> remote: snapshot, install $BUILD, restart (will prompt for sudo password)"
ssh -t ${SSH_PORT:+-p "$SSH_PORT"} "$SSH_HOST" \
    "MYC_REMOTE_DIR='$REMOTE_DIR' MYC_SERVICE='$SERVICE' MYC_DATA_DIR='$DATA_DIR'" \
    "MYC_SNAPSHOT_DIR='$SNAPSHOT_DIR' MYC_KEEP_SNAPSHOTS='$KEEP_SNAPSHOTS'" \
    "bash .mycelium-staging/deploy/release.sh \"\$HOME/.mycelium-staging\" '$BUILD'" \
    "${SKIP_RESTART:+--skip-restart}"

echo "==> done"
