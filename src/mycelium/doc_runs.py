"""Thread-per-run documentation executor.

The same shape as `research_runs`, for the same reasons: a generation run is
one long agent loop rather than a drainable queue, so each run gets one daemon
thread; the concurrency bound is counted from the database and therefore
survives a restart; and `finally: finish_run` means no runner crash can leave
a row unfinished once the worker starts.

Where it differs is the seam. A research runner writes its own draft and hands
back an id. A documentation runner hands back the DOCUMENT — slug, title,
body — and this module persists it. That is what lets the whole executor be
proven against a stub returning a canned document, and it puts the write where
the run id and the connection already are, so `last_run_id` needs no extra
plumbing to be correct.

`RUNNER` is that seam's override. Left None — which is the normal case — a
run drives `docgen.run_docgen`; tests set it to a stub, and an explicit
`runner=` argument beats both.
"""

from __future__ import annotations

import contextvars
import logging
import os
import sqlite3
import threading
from typing import Any, Callable

from . import docs_store

logger = logging.getLogger(__name__)
MAX_ACTIVE_ENV = "MYCELIUM_DOCGEN_MAX_ACTIVE"
RUNNER: Callable[..., Any] | None = None
_spawn_lock = threading.Lock()
_threads: dict[str, threading.Thread] = {}
_in_memory_conns: dict[str, sqlite3.Connection] = {}


def start_run(
    *,
    prompt: str,
    guideline_set: str | None,
    document_type: str | None,
    created_by: str | None,
    conn: sqlite3.Connection,
    runner: Callable[..., Any] | None = None,
) -> str:
    # Explicit argument wins; the module-level RUNNER hook only fills in when
    # no runner is passed (tests monkeypatch RUNNER, HTTP callers pass none).
    selected_runner = runner or RUNNER or _default_runner
    max_active = int(os.environ.get(MAX_ACTIVE_ENV) or 2)

    with _spawn_lock:
        if docs_store.count_active(conn) >= max_active:
            raise ValueError(
                f"too many active documentation runs (max {max_active}, from "
                f"{MAX_ACTIVE_ENV}); retry when one finishes"
            )

        run_id = docs_store.create_run(
            conn,
            prompt=prompt,
            guideline_set=guideline_set,
            document_type=document_type,
            created_by=created_by,
        )
        # Anything failing between here and thread.start() must not strand
        # the freshly committed row: finish it as failed, then re-raise.
        try:
            docs_store.mark_started(conn, run_id)
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
                    prompt,
                    guideline_set,
                    document_type,
                    db_path,
                    selected_runner,
                ),
                daemon=True,
                name=f"docgen-{run_id}",
            )
            _threads[run_id] = t
            t.start()
        except Exception as exc:
            _in_memory_conns.pop(run_id, None)
            _threads.pop(run_id, None)
            try:
                docs_store.finish_run(
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


def _default_runner(
    prompt: str,
    *,
    guideline_set: str | None = None,
    document_type: str | None = None,
) -> Any:
    """The real generation loop.

    Imported inside the call, on the worker thread: the loop pulls the
    anthropic SDK, and requesting a documentation run must not be what makes
    an instance that never generates pay for it. Anything the loop cannot
    survive comes back as an exception here and lands on the row's `error`,
    which is where a caller polling the run will read it."""
    from .docgen import run_docgen

    return run_docgen(prompt, guideline_set=guideline_set, document_type=document_type)


def _execute_run(
    run_id: str,
    prompt: str,
    guideline_set: str | None,
    document_type: str | None,
    db_path: str,
    runner: Callable[..., Any],
) -> None:
    own_conn = None
    conn = _in_memory_conns.pop(run_id, None)

    outcome = "failed"
    document_id = None
    error = None

    try:
        # Inside the try: a failed connect must still reach the finally-side
        # finalization attempt, never strand the row as 'running'.
        if conn is None:
            own_conn = docs_store.connect(db_path)
            conn = own_conn
        # A generation run is a model loop like `ask` and `ingest`, so it draws
        # on the same budget rather than a private one — otherwise the two caps
        # add up and the box holds more model contexts than either intended.
        # The wait happens on this daemon thread, which costs nothing shared,
        # and MYCELIUM_DOCGEN_MAX_ACTIVE already bounds how many can be queued
        # behind it. The row stays 'running' while waiting, which is honest:
        # the run has been accepted and nothing else needs to happen to it.
        from . import server

        with server.model_loop_slot():
            result = runner(
                prompt, guideline_set=guideline_set, document_type=document_type
            )
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        # The request may have named neither, in which case the run chose. Put
        # the choice on the row before the outcome is decided, so a run that
        # settled on a set and then found nothing to say still shows what it
        # was trying to write. COALESCE in the store means a runner that
        # reports neither leaves whatever the request named standing.
        docs_store.mark_started(
            conn,
            run_id,
            guideline_set=payload.get("guideline_set"),
            document_type=payload.get("document_type"),
        )
        reported = payload.get("outcome")
        if reported not in ("document_written", "nothing_written"):
            # Not folded into `nothing_written`: a runner that returns junk, or
            # reports its own failure, would otherwise be recorded as a clean
            # refusal with no reason. Raising lands it on `error` as what it is.
            raise ValueError(f"runner returned an unknown outcome: {reported!r}")
        if reported == "document_written":
            # The loop refuses an ungrounded document at its emit gate; this is
            # the same rule at the place that actually records one, so "a
            # stored document cites the statements it rests on" holds however
            # the runner was wired. Raising rather than downgrading to
            # `nothing_written`: a runner reporting a document with no
            # provenance is broken, and that belongs on `error`.
            if not payload.get("statement_ids"):
                raise ValueError(
                    "runner reported a document with no statement ids; a "
                    "document that rests on nothing is not recorded"
                )
            # Written before `outcome` is set, so a rejected document (blank
            # slug, unwritable DB) finishes the run failed rather than claiming
            # a document that is not there.
            document_id = docs_store.upsert_document(
                conn,
                slug=payload["slug"],
                title=payload["title"],
                body=payload["body"],
                # The run may resolve what the request left unnamed; what it
                # actually wrote against belongs on the document.
                guideline_set=payload.get("guideline_set") or guideline_set,
                document_type=payload.get("document_type") or document_type,
                statement_ids=payload.get("statement_ids"),
                # The loop and DocumentWritten enforce that review ran. This
                # overridable runner seam accepts older canned runners instead
                # of making their missing record fatal; the store writes `{}`.
                review=payload.get("review"),
                run_id=run_id,
            )
            outcome = "document_written"
        else:
            outcome = "nothing_written"
            # Keeping the reason verbatim is how a rejected document's review
            # findings reach the run row; a bare status would discard them.
            error = payload.get("reason")
    except Exception as exc:
        logger.exception("documentation run failed: %s", run_id)
        outcome = "failed"
        document_id = None
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if conn is None:
                # The connect above failed; one fresh attempt so the row is
                # not left 'running' holding a capacity slot. If this fails
                # too, the startup orphan sweep is the backstop.
                conn = own_conn = docs_store.connect(db_path)
            docs_store.finish_run(
                conn,
                run_id,
                outcome=outcome,
                document_id=document_id,
                error=error,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not finalize documentation run %s", run_id)
        finally:
            if own_conn is not None:
                own_conn.close()
            _threads.pop(run_id, None)
