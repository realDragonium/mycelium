"""Debounced background runner for the entity-layout baker.

Server-side mutations that change the entity topology (create/delete
entity, add/remove entity-link) call ``schedule_rebake()``. This sets
a debounce timer; when the timer fires with no further calls in the
intervening window, the offline layout script is spawned in a
detached subprocess. The browser picks up the new JSON on next reload.

Why debounce: a single MCP request that creates a statement with 8
new mentions calls ``store.create_entity`` 8 times. Without debouncing
we'd spawn 8 rebake subprocesses, which is wasteful and races on the
output file. The 5-second window lets a burst of mutations land first
and then triggers exactly one rebake at the end.

Why a subprocess: keeps the layout computation off the request path
(rebake takes ~3 seconds, doesn't block the API response) and ensures
a crashing baker can't crash the server.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "build_entity_layout.py"

_lock = threading.Lock()
_timer: threading.Timer | None = None
_process: subprocess.Popen[bytes] | None = None
_db_path: Path | None = None
_output_path: Path | None = None


def _bake_argv(db_path: Path, output_path: Path) -> list[str]:
    """The subprocess argv for invoking the offline layout script against
    `db_path`, writing positions to `output_path`. Shared by the initial
    synchronous bake and the debounced background rebake so both spawn
    the identical command."""
    return [
        sys.executable,
        str(_SCRIPT),
        "--db",
        str(db_path),
        "--output",
        str(output_path),
    ]


def output_path() -> Path | None:
    """The path the baker writes positions to. Lives next to the DB
    (i.e. in the data dir, not the source tree) so deploys can't wipe
    it and the systemd hardening's ProtectSystem=strict permits the
    write. Returns None when configure() hasn't been called yet."""
    return _output_path


# Wait this long after the last schedule_rebake() call before firing.
# Tuned to absorb the burst of writes from a single upsert_statements
# batch (typically completes well under 1s for normal workloads).
DEBOUNCE_SECONDS = 5.0


def configure(db_path: Path) -> None:
    """Tell the baker which DB to bake from. Called once by ``server.init``.

    The positions file lives next to the DB so the bake artifact is
    co-located with the data it describes — a fresh data dir starts
    with no positions and gets one baked on first run; a backup
    snapshot of the data dir captures both the substrate and its
    layout.
    """
    global _db_path, _output_path
    _db_path = db_path
    _output_path = db_path.parent / "entity-positions.json"


def ensure_initial() -> None:
    """Run a synchronous initial bake if the positions file is missing.

    The positions file is gitignored — fresh checkouts will not have it.
    Without it the entity graph renders with degenerate positions, so we
    bake once on startup (blocks for a few seconds on the first run only;
    subsequent starts skip this entirely).
    """
    if _db_path is None or _output_path is None or not _SCRIPT.exists():
        return
    if _output_path.exists():
        return
    log.info("entity-positions.json missing; running initial bake (db=%s)", _db_path)
    _output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        _bake_argv(_db_path, _output_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        log.warning(
            "initial layout bake failed (rc=%s): %s",
            result.returncode,
            result.stderr.decode("utf-8", errors="replace").strip(),
        )


def schedule_rebake() -> None:
    """Schedule a layout rebake. Safe to call from any thread. Rapid
    successive calls collapse to a single rebake after the debounce
    window elapses with no further calls."""
    global _timer
    if _db_path is None:
        # configure() was never called — running in a test or other
        # mode where rebakes are unwanted. Silent no-op.
        return
    if not _SCRIPT.exists():
        log.warning("layout baker script not found at %s", _SCRIPT)
        return
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(DEBOUNCE_SECONDS, _fire)
        _timer.daemon = True
        _timer.start()


def _fire() -> None:
    """Spawn the rebake subprocess. Skipped if a previous rebake is
    still running — the next schedule_rebake() call will catch it."""
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            log.info("previous rebake still running; skipping this trigger")
            return
        assert _db_path is not None and _output_path is not None
        log.info("triggering layout rebake (db=%s)", _db_path)
        _process = subprocess.Popen(
            _bake_argv(_db_path, _output_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(_REPO_ROOT),
        )
