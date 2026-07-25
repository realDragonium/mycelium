#!/usr/bin/env bash
# Deployment-agnostic engine entrypoint.
#
# Runs the MCP server against a local SQLite data dir and nothing more. The app
# opens each DB in WAL mode itself (see store/kernel.py, drafts_store.py, …), so
# there is no pragma priming to do here. Durability (WAL replication to object
# storage), restore ordering, and derived-artifact snapshotting are DEPLOYMENT
# concerns: the image that wraps this one overrides ENTRYPOINT with a supervisor
# that restores first and then execs this server. A bare `docker run` of this
# image just serves on a local, ephemeral data dir.
set -euo pipefail

mkdir -p "${MYCELIUM_DATA_DIR:-/data}"

exec mycelium-http
