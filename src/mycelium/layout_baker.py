"""Debounced background runner for the entity-layout baker.

Server-side mutations that change the entity topology (create/delete
entity, add/remove entity-link) call ``schedule_rebake()``. This sets
a debounce timer; when the timer fires with no further calls in the
intervening window, the packaged layout module is spawned in a
detached subprocess. The browser picks up the new JSON on next reload.
If a bake is still running, the timer is re-armed until it finishes,
then one more bake captures the pending mutations.

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

# Wait this long after the last schedule_rebake() call before firing.
# Tuned to absorb the burst of writes from a single upsert_statements
# batch (typically completes well under 1s for normal workloads).
DEBOUNCE_SECONDS = 5.0


def _bake_argv(db_path: Path, output_path: Path) -> list[str]:
    """The subprocess argv for invoking the packaged layout module against
    `db_path`, writing positions to `output_path`. Shared by the initial
    synchronous bake and the debounced background rebake so both spawn
    the identical command."""
    return [
        sys.executable,
        "-m",
        "mycelium.entity_layout",
        "--db",
        str(db_path),
        "--output",
        str(output_path),
    ]


class LayoutBaker:
    """Owns the debounce timer and subprocess handle for one substrate's
    entity-layout bakes. Built by ``server.init`` against the substrate DB
    and held on the ``AppContext``; ``server`` and ``http`` reach it through
    that owner rather than a module singleton.

    The positions file lives next to the DB (i.e. in the data dir, not the
    source tree) so the bake artifact is co-located with the data it
    describes — a fresh data dir starts with no positions and gets one baked
    on first run; a backup snapshot of the data dir captures both the
    substrate and its layout. Co-location also keeps the write inside the
    systemd hardening's ProtectSystem=strict boundary.
    """

    def __init__(self, db_path: Path, *, enabled: bool = True) -> None:
        self._db_path = db_path
        self._enabled = enabled
        self._output_path = db_path.parent / "entity-positions.json"
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._process: subprocess.Popen[bytes] | None = None

    def output_path(self) -> Path:
        """The path the baker writes positions to."""
        return self._output_path

    def ensure_initial(self) -> None:
        """Run a synchronous initial bake if the positions file is missing.

        The positions file is gitignored — fresh checkouts will not have it.
        Without it the entity graph renders with degenerate positions, so we
        bake once on startup (blocks for a few seconds on the first run only;
        subsequent starts skip this entirely).
        """
        if not self._enabled:
            return
        if self._output_path.exists():
            return
        log.info(
            "entity-positions.json missing; running initial bake (db=%s)",
            self._db_path,
        )
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            _bake_argv(self._db_path, self._output_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            log.warning(
                "initial layout bake failed (rc=%s): %s",
                result.returncode,
                result.stderr.decode("utf-8", errors="replace").strip(),
            )

    def schedule_rebake(self) -> None:
        """Schedule a layout rebake. Safe to call from any thread. Rapid
        successive calls collapse to a single rebake after the debounce
        window elapses with no further calls."""
        if not self._enabled:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._arm_timer()

    def _arm_timer(self) -> None:
        self._timer = threading.Timer(DEBOUNCE_SECONDS, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        """Spawn the rebake subprocess, deferring while a prior bake runs."""
        with self._lock:
            self._timer = None
            if self._process is not None and self._process.poll() is None:
                log.info("previous rebake still running; deferring this trigger")
                self._arm_timer()
                return
            log.info("triggering layout rebake (db=%s)", self._db_path)
            self._process = subprocess.Popen(
                _bake_argv(self._db_path, self._output_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
