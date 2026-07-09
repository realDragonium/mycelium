"""Thread-per-run research executor.

Unlike `mention_worker`, a research run is one long agent loop, not a
drainable queue, so each run gets one daemon thread. The concurrency bound
is DB-derived and therefore restart-safe: started-but-unfinished rows count
against the cap until they finish or startup marks them orphaned.

Finalization is guaranteed with `finally: finish_run`, so no runner crash
leaves an unfinished row once the worker starts. The `error` column holds
the failure message, or the nothing-found reason on `nothing_found`.
"""

from __future__ import annotations

import contextvars
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from . import research_store

logger = logging.getLogger(__name__)
MAX_ACTIVE_ENV = "MYCELIUM_RESEARCH_MAX_ACTIVE"
RUNNER: Callable[..., Any] | None = None
_spawn_lock = threading.Lock()
_threads: dict[str, threading.Thread] = {}
_in_memory_conns: dict[str, sqlite3.Connection] = {}


def start_run(
    *,
    topic: str,
    source: str,
    created_by: str | None,
    data_dir: Path,
    conn: sqlite3.Connection,
    runner: Callable[..., Any] | None = None,
) -> str:
    # Explicit argument wins; the module-level RUNNER hook only fills in when
    # no runner is passed (tests monkeypatch RUNNER, HTTP callers pass none).
    selected_runner = runner or RUNNER or _default_runner(str(data_dir))
    max_active = int(os.environ.get(MAX_ACTIVE_ENV) or 2)

    with _spawn_lock:
        if research_store.count_active(conn) >= max_active:
            raise ValueError(
                f"too many active research runs (max {max_active}); "
                "retry when one finishes"
            )

        run_id = research_store.create_run(
            conn, topic=topic, source=source, created_by=created_by
        )
        # Anything failing between here and thread.start() must not strand
        # the freshly committed row: finish it as failed, then re-raise.
        try:
            research_store.mark_started(conn, run_id)
            rows = conn.execute("PRAGMA database_list").fetchall()
            main = next((row for row in rows if row["name"] == "main"), None)
            db_path = main["file"] if main is not None else ""

            # Tests and occasional embedded use can run against :memory:. In
            # that case there is no file path for the worker to reopen, so
            # reuse the already thread-safe connection handed to start_run.
            if not db_path:
                _in_memory_conns[run_id] = conn

            ctx = contextvars.copy_context()
            t = threading.Thread(
                target=lambda: ctx.run(
                    _execute_run,
                    run_id,
                    topic,
                    source,
                    db_path,
                    str(data_dir),
                    selected_runner,
                ),
                daemon=True,
                name=f"research-{run_id}",
            )
            _threads[run_id] = t
            t.start()
        except Exception as exc:
            _in_memory_conns.pop(run_id, None)
            _threads.pop(run_id, None)
            try:
                research_store.finish_run(
                    conn,
                    run_id,
                    outcome="failed",
                    error=f"failed to start: {type(exc).__name__}: {exc}",
                )
            except Exception:  # noqa: BLE001 — startup orphan sweep is the backstop
                logger.exception("could not finalize failed start of %s", run_id)
            raise
        return run_id


def wait_all(timeout: float = 10.0) -> None:
    for thread in list(_threads.values()):
        thread.join(timeout)


def _default_runner(data_dir: str) -> Callable[..., Any]:
    """The real research loop, wired for a worker thread.

    - The trace JSONL is defaulted under the data dir (mirroring the `ingest`
      tool's wiring) so `trace_ref` points at a file that actually gets
      written; an env-configured path wins.
    - The draft emitter writes through `server._drafts_db()`, which hands this
      worker thread its OWN drafts connection (per-thread provider), so a long
      run's draft write never contends with HTTP-thread commits on a shared
      connection object.
    """
    import dataclasses

    def run(topic: str, *, source: str | None = None) -> Any:
        from . import server
        from .ingest.draft import InProcessDraftEmitter
        from .research import run_research
        from .research.config import ResearchConfig

        config = ResearchConfig.from_env()
        if not config.trace_log_path:
            config = dataclasses.replace(
                config, trace_log_path=_trace_log_path(data_dir)
            )
        return run_research(
            topic, source, config=config, emitter=InProcessDraftEmitter(server)
        )

    return run


def _trace_log_path(data_dir: str) -> str:
    """The trace JSONL sink for research runs: the env override when set, else
    the default under the data dir. `trace_ref` and the runner's config must
    agree, so both derive from here."""
    return os.environ.get("MYCELIUM_RESEARCH_TRACE_LOG") or str(
        Path(data_dir) / "research_trace.jsonl"
    )


def _execute_run(
    run_id: str,
    topic: str,
    source: str,
    db_path: str,
    data_dir: str,
    runner: Callable[..., Any],
) -> None:
    own_conn = None
    conn = _in_memory_conns.pop(run_id, None)

    trace_ref = _trace_log_path(data_dir)
    outcome = "failed"
    draft_id = None
    error = None

    try:
        # Inside the try: a failed connect must still reach the finally-side
        # finalization attempt, never strand the row as 'running'.
        if conn is None:
            own_conn = research_store.connect(db_path)
            conn = own_conn
        result = runner(topic, source=source)
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        if payload.get("outcome") == "draft_created":
            outcome = "draft_created"
            draft_id = payload.get("draft_id")
        else:
            outcome = "nothing_found"
            error = payload.get("reason")
    except Exception as exc:
        logger.exception("research run failed: %s", run_id)
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if conn is None:
                # The connect above failed; one fresh attempt so the row is
                # not left 'running' holding a capacity slot. If this fails
                # too, the startup orphan sweep is the backstop.
                conn = own_conn = research_store.connect(db_path)
            research_store.finish_run(
                conn,
                run_id,
                outcome=outcome,
                draft_id=draft_id,
                error=error,
                trace_ref=trace_ref,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not finalize research run %s", run_id)
        finally:
            if own_conn is not None:
                own_conn.close()
            _threads.pop(run_id, None)
