#!/usr/bin/env bash
# Mycelium server container entrypoint.
#
# Ordering is the whole point: Litestream restore MUST complete and the DB
# files MUST be in WAL mode BEFORE the server opens them. Litestream then
# supervises the server and replicates the WAL to S3 continuously.
set -euo pipefail

DATA_DIR="${MYCELIUM_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# Every SQLite file Mycelium persists (enumerated from the repo). All four are
# replicated independently by Litestream; mycelium-history.db is attached to
# mycelium.db at runtime but is a separate file on disk.
DBS=(mycelium.db mycelium-history.db mycelium-auth.db mycelium-drafts.db)

# Derive the OIDC issuer from the injected Auth0 DOMAIN secret. The app reads
# MYCELIUM_OIDC_ISSUER; the secret convention only carries DOMAIN.
if [[ -n "${AUTH0_DOMAIN:-}" && "${AUTH0_DOMAIN}" != "REPLACE_ME" ]]; then
  export MYCELIUM_OIDC_ISSUER="https://${AUTH0_DOMAIN%/}/"
fi

# 1) Restore derived (non-SQLite) artifacts from the latest periodic snapshot:
#    the hnswlib vector indexes (*.vec) and baked layout (entity-positions.json).
#    These are rebuildable from the DB but expensive to regenerate, so we cache
#    them. Best-effort: a fresh env simply has no snapshot yet.
if [[ -n "${SNAPSHOT_S3_URL:-}" ]]; then
  echo "[entrypoint] fetching derived-artifact snapshot from ${SNAPSHOT_S3_URL}/latest.tar.zst"
  if aws s3 cp "${SNAPSHOT_S3_URL}/latest.tar.zst" /tmp/snapshot.tar.zst --only-show-errors; then
    tar --use-compress-program=unzstd -xf /tmp/snapshot.tar.zst -C "$DATA_DIR" || true
    rm -f /tmp/snapshot.tar.zst
  else
    echo "[entrypoint] no snapshot yet (fresh env) — continuing"
  fi
fi

# 2) Restore each SQLite DB from Litestream if it isn't already local. S3 is
#    authoritative; the local copy is just a working copy.
for db in "${DBS[@]}"; do
  target="$DATA_DIR/$db"
  if [[ ! -f "$target" ]]; then
    echo "[entrypoint] litestream restore ${db}"
    litestream restore -if-replica-exists -config /etc/litestream.yml "$target" \
      || echo "[entrypoint] no replica for ${db} (fresh) — it will be created"
  fi
  # 3) Ensure WAL (Litestream requirement). On a brand-new env the file does
  #    not exist yet; running the pragma creates it in WAL so the app opens it
  #    in WAL from the very first write.
  sqlite3 "$target" "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;" >/dev/null
done

# 4) Background snapshotter for the derived artifacts Litestream can't cover
#    (they aren't SQLite). The DBs remain authoritative via Litestream; this
#    just speeds recovery of the semantic index / layout.
if [[ -n "${SNAPSHOT_S3_URL:-}" ]]; then
  (
    interval="${SNAPSHOT_INTERVAL_SECONDS:-900}"
    while true; do
      sleep "$interval"
      artifacts=$(cd "$DATA_DIR" && ls *.vec entity-positions.json 2>/dev/null || true)
      [[ -z "$artifacts" ]] && continue
      tmp="$(mktemp /tmp/snap.XXXXXX.tar.zst)"
      if (cd "$DATA_DIR" && tar --use-compress-program='zstd -3' -cf "$tmp" $artifacts); then
        aws s3 cp "$tmp" "${SNAPSHOT_S3_URL}/latest.tar.zst" --only-show-errors || true
      fi
      rm -f "$tmp"
    done
  ) &
fi

# 5) Hand off to Litestream as supervisor: it replicates the WAL of every DB in
#    its config and execs the server. When the server exits, Litestream does a
#    final checkpoint + sync before the container stops.
echo "[entrypoint] starting: litestream replicate -exec mycelium-http"
exec litestream replicate -config /etc/litestream.yml -exec "mycelium-http"
