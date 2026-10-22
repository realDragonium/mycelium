#!/usr/bin/env bash
# Server side of `deploy/deploy.sh`: snapshot the data, install the staged
# build, start it. Runs as the SSH user and uses sudo; deploy.sh ships it in
# the staging dir and calls it. Not meant to be run by hand.
#
# Usage: release.sh STAGE_DIR BUILD [--skip-restart]
#
# The snapshot is taken with the service stopped and before any code is
# replaced, so it is exactly what the running build last wrote — and what a
# rollback restores (docs/DEPLOYMENT.md, "Rolling back a deploy"). If it
# fails, the current build is started again and nothing is installed.
#
# Layout: $MYC_SNAPSHOT_DIR/<UTC time>/data/ is the copy; BUILD beside it
# names the build that wrote it. Both directories are root-only.

set -euo pipefail

STAGE_DIR="$1"
BUILD="$2"
SKIP_RESTART="${3:-}"

REMOTE_DIR="${MYC_REMOTE_DIR:-/opt/mycelium}"
SERVICE="${MYC_SERVICE:-mycelium}"
DATA_DIR="${MYC_DATA_DIR:-/var/lib/mycelium}"
SNAPSHOT_ROOT="${MYC_SNAPSHOT_DIR:-/var/lib/mycelium-snapshots}"
KEEP_SNAPSHOTS="${MYC_KEEP_SNAPSHOTS:-5}"

if ! [[ "$KEEP_SNAPSHOTS" =~ ^[1-9][0-9]*$ ]]; then
    echo "MYC_KEEP_SNAPSHOTS must be a positive integer" >&2
    exit 1
fi

copy_and_verify() {
    local dest="$1"
    # Check the source as its owner: root never parses files the service
    # could have shaped, and an unreadable database fails the deploy here.
    sudo -u mycelium find "$DATA_DIR" -maxdepth 1 -type f -name '*.db' -print0 |
        while IFS= read -r -d '' db; do
            sudo -u mycelium python3 -c '
import sqlite3, sys
result = sqlite3.connect(sys.argv[1]).execute("PRAGMA quick_check").fetchone()[0]
sys.exit(0 if result == "ok" else f"{sys.argv[1]}: {result}")
' "$db" || exit 1
        done || return 1
    # The uv cache lives in the data dir (see the systemd unit) but is not data.
    sudo rsync -a --exclude='.uv-cache/' "$DATA_DIR/" "$dest/data/" || return 1
    sudo diff -rq --no-dereference -x .uv-cache "$DATA_DIR" "$dest/data" || return 1
    # Which build wrote this data — the one to redeploy when restoring it.
    # Beside the copy, in the root-owned dir, so nothing in the data can
    # redirect the write.
    { sudo -u mycelium cat "$REMOTE_DIR/BUILD" 2>/dev/null || echo unknown; } |
        sudo tee "$dest/BUILD" >/dev/null
}

snapshot() {
    local dest
    dest="$SNAPSHOT_ROOT/$(date -u +%Y%m%dT%H%M%SZ)"
    sudo install -d -m 0700 "$SNAPSHOT_ROOT" "$dest" || return 1
    echo "==> snapshot $DATA_DIR → $dest"
    if ! copy_and_verify "$dest"; then
        sudo rm -rf -- "$dest"
        return 1
    fi
    # Keep the newest KEEP_SNAPSHOTS; names sort by time.
    sudo find "$SNAPSHOT_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' |
        sort -r | tail -n "+$((KEEP_SNAPSHOTS + 1))" | xargs -r sudo rm -rf --
}

if [[ "$SKIP_RESTART" != "--skip-restart" ]] && sudo test -f "$DATA_DIR/mycelium.db"; then
    echo "==> stop $SERVICE"
    sudo systemctl stop "$SERVICE"
    if ! snapshot; then
        echo "!! snapshot failed; restarting the current build, nothing installed" >&2
        sudo systemctl start "$SERVICE"
        exit 1
    fi
fi

echo "==> install $BUILD into $REMOTE_DIR"
# --delete keeps the app dir free of stale source, but the mycelium user's
# HOME is $REMOTE_DIR too — uv and its caches live there. Preserve those.
sudo rsync -a --delete \
    --exclude='.local/' --exclude='.cache/' --exclude='.venv/' \
    "$STAGE_DIR/" "$REMOTE_DIR/"
echo "$BUILD" | sudo tee "$REMOTE_DIR/BUILD" >/dev/null
sudo chown -R mycelium:mycelium "$REMOTE_DIR"
sudo -u mycelium -H bash -lc "cd '$REMOTE_DIR' && $REMOTE_DIR/.local/bin/uv sync --frozen"

if [[ "$SKIP_RESTART" == "--skip-restart" ]]; then
    echo "==> skipping restart (--skip-restart)"
    exit 0
fi

echo "==> start $SERVICE"
sudo systemctl restart "$SERVICE"
# A refused or failed migration exits within seconds; catch it here rather
# than report a deploy that systemd is already restarting in a loop.
sleep 3
if ! sudo systemctl is-active --quiet "$SERVICE"; then
    sudo journalctl -u "$SERVICE" -n 50 --no-pager
    echo "!! $SERVICE is not running; see docs/DEPLOYMENT.md, \"Rolling back a deploy\"" >&2
    exit 1
fi
echo "active"
