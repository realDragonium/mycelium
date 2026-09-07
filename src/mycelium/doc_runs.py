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
import json
import logging
import os
import sqlite3
import threading
from typing import TYPE_CHECKING, Any, Callable

from . import docs_store, product_settings, prompt_store
from .docgen.config import DocgenConfig, Provider
from .docgen.destinations import DestinationConfig, load_destinations
from .docgen.schema import CurrentDocument, ExistingDocument, RevisionTarget

if TYPE_CHECKING:
    from .documentation_profiles import CatalogueSnapshot


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
    provider: Provider | None = None,
    runner: Callable[..., Any] | None = None,
    target_document_id: str | None = None,
    expected_revision: int | None = None,
    match_existing: bool = True,
) -> str:
    # Explicit argument wins; the module-level RUNNER hook only fills in when
    # no runner is passed (tests monkeypatch RUNNER, HTTP callers pass none).
    selected_runner = runner or RUNNER or _default_runner
    config = DocgenConfig.from_env(provider=provider)
    if not config.model:
        raise ValueError(
            f"Choose a {config.provider} documentation model in AI settings."
        )
    if config.provider == "openai":
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError("Set OPENAI_API_KEY on the server.")
    max_active = product_settings.get(
        product_settings.ConcurrencySettings
    ).documentation_runs
    destinations = (
        load_destinations() if target_document_id is None and match_existing else {}
    )
    from . import documentation_profiles

    profiles = (
        documentation_profiles.capture() if prompt_store.is_configured() else None
    )
    target = None
    if target_document_id is not None:
        if expected_revision is None:
            raise ValueError("expected_revision is required to revise a document")
        row = docs_store.require_revision(conn, target_document_id, expected_revision)
        target = RevisionTarget(
            document=ExistingDocument(
                id=target_document_id,
                slug=str(row["slug"]),
                title=str(row["title"]),
                guideline_set=str(row["guideline_set"]),
                document_type=str(row["document_type"]),
                body_digest=docs_store.body_digest(str(row["body"])),
            ),
            revision=expected_revision,
            current=CurrentDocument(
                body=str(row["body"]),
                content_revision=str(row["delivery_content_revision"])
                if row["delivery_content_revision"] is not None
                else None,
            ),
        )
        guideline_set = target.document.guideline_set
        document_type = target.document.document_type
    elif expected_revision is not None:
        raise ValueError("expected_revision requires a target document")

    with _spawn_lock:
        if docs_store.count_active(conn) >= max_active:
            raise ValueError(
                f"too many active documentation runs (max {max_active}); retry when one finishes"
            )

        run_id = docs_store.create_run(
            conn,
            prompt=prompt,
            guideline_set=guideline_set,
            document_type=document_type,
            created_by=created_by,
            provider=config.provider,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            target_document_id=target_document_id,
            target_revision=expected_revision,
        )
        # Anything failing between here and thread.start() must not strand
        # the freshly committed row: finish it as failed, then re-raise.
        try:
            if profiles is not None and guideline_set and document_type:
                _record_profile(conn, run_id, profiles, guideline_set, document_type)
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
                    config,
                    destinations,
                    target,
                    profiles,
                    match_existing,
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


def _record_profile(
    conn: sqlite3.Connection,
    run_id: str,
    profiles: CatalogueSnapshot,
    set_name: str,
    document_type: str,
) -> None:
    from dataclasses import asdict

    references = {
        name: asdict(ref)
        for name, ref in profiles.references(set_name, document_type).items()
    }
    texts = dict(
        zip(
            ("guidance", "exposure", "template"),
            profiles.texts(set_name, document_type),
            strict=True,
        )
    )
    conn.execute(
        "UPDATE documentation_runs SET profile_revisions = ?, profile_snapshot = ? WHERE id = ?",
        (
            json.dumps(references),
            json.dumps(
                {
                    "guideline_set": set_name,
                    "document_type": document_type,
                    "texts": texts,
                    "references": references,
                }
            ),
            run_id,
        ),
    )
    conn.commit()


def wait_all(timeout: float = 10.0) -> None:
    for thread in list(_threads.values()):
        thread.join(timeout)


def _default_runner(
    prompt: str,
    *,
    guideline_set: str | None = None,
    document_type: str | None = None,
    existing_documents: tuple[ExistingDocument, ...] = (),
    load_current_document: Callable[[str], CurrentDocument] | None = None,
    config: DocgenConfig | None = None,
    revision_target: RevisionTarget | None = None,
    profiles: CatalogueSnapshot | None = None,
) -> Any:
    """The real generation loop.

    Imported inside the call, on the worker thread: the loop pulls the
    provider client, and requesting a documentation run must not be what makes
    an instance that never generates pay for it. Anything the loop cannot
    survive comes back as an exception here and lands on the row's `error`,
    which is where a caller polling the run will read it."""
    from .docgen import run_docgen

    return run_docgen(
        prompt,
        guideline_set=guideline_set,
        document_type=document_type,
        config=config,
        existing_documents=existing_documents,
        load_current_document=load_current_document,
        revision_target=revision_target,
        profiles=profiles,
    )


def _execute_run(
    run_id: str,
    prompt: str,
    guideline_set: str | None,
    document_type: str | None,
    db_path: str,
    runner: Callable[..., Any],
    config: DocgenConfig | None = None,
    destinations: dict[str, DestinationConfig] | None = None,
    revision_target: RevisionTarget | None = None,
    profiles: CatalogueSnapshot | None = None,
    match_existing: bool = True,
) -> None:
    own_conn = None
    conn = _in_memory_conns.pop(run_id, None)

    outcome = "failed"
    document_id = None
    error = None
    draft_title = None
    draft_body = None
    matched_document_id = None

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
            if runner is _default_runner:
                result = runner(
                    prompt,
                    guideline_set=guideline_set,
                    document_type=document_type,
                    config=config,
                    existing_documents=_existing_documents(conn)
                    if match_existing and revision_target is None
                    else (),
                    revision_target=revision_target,
                    profiles=profiles,
                    load_current_document=lambda document_id: _load_current_document(
                        conn, document_id, destinations
                    ),
                )
            else:
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
            guideline_set=guideline_set
            if revision_target is not None
            else payload.get("guideline_set"),
            document_type=document_type
            if revision_target is not None
            else payload.get("document_type"),
        )
        reported = payload.get("outcome")
        matched_document_id = (
            revision_target.document.id
            if revision_target is not None
            else payload.get("matched_document_id")
        )
        if profiles is not None:
            selected_set = (
                guideline_set
                if revision_target is not None
                else payload.get("guideline_set") or guideline_set
            )
            selected_type = (
                document_type
                if revision_target is not None
                else payload.get("document_type") or document_type
            )
            if selected_set and selected_type:
                _record_profile(conn, run_id, profiles, selected_set, selected_type)
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
            # Written before `outcome` is set, so a rejected document (a
            # refused collision, blank slug, or unwritable DB) finishes the run
            # failed rather than claiming a document that is not there.
            matched_row = (
                docs_store.get_document(conn, matched_document_id)
                if matched_document_id is not None
                else None
            )
            if matched_document_id is not None and matched_row is None:
                raise ValueError("matched generated document no longer exists")
            draft_title = payload["title"]
            draft_body = payload["body"]
            document_id = docs_store.upsert_document(
                conn,
                slug=(
                    str(matched_row["slug"])
                    if matched_row is not None
                    else payload["slug"]
                ),
                title=payload["title"],
                body=payload["body"],
                # The run may resolve what the request left unnamed; what it
                # actually wrote against belongs on the document.
                guideline_set=guideline_set
                if revision_target is not None
                else payload.get("guideline_set") or guideline_set,
                document_type=document_type
                if revision_target is not None
                else payload.get("document_type") or document_type,
                statement_ids=payload.get("statement_ids"),
                # The loop and DocumentWritten enforce that review ran. This
                # overridable runner seam accepts older canned runners instead
                # of making their missing record fatal; the store writes `{}`.
                review=payload.get("review"),
                run_id=run_id,
                updates=matched_document_id,
                expected_revision=revision_target.revision
                if revision_target is not None
                else None,
                replacing=(
                    revision_target.document.body_digest
                    if revision_target is not None
                    else (
                        str(payload["matched_body_digest"])
                        if payload.get("matched_body_digest") is not None
                        else (
                            docs_store.body_digest(str(matched_row["body"]))
                            if matched_row is not None
                            else None
                        )
                    )
                ),
                revision_source_content_revision=(
                    revision_target.current.content_revision
                    if revision_target is not None
                    else payload.get("matched_content_revision")
                ),
            )
            outcome = "document_written"
            draft_title = None
            draft_body = None
        else:
            outcome = "nothing_written"
            # Keeping the reason verbatim is how a rejected document's review
            # findings reach the run row; a bare status would discard them.
            error = payload.get("reason")
            # The findings quote a document, so the document is kept beside
            # them. Present only when one was written and refused.
            draft_title = payload.get("title")
            draft_body = payload.get("body")
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
                draft_title=draft_title,
                draft_body=draft_body,
                matched_document_id=matched_document_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not finalize documentation run %s", run_id)
        finally:
            if own_conn is not None:
                own_conn.close()
            _threads.pop(run_id, None)


def _existing_documents(conn: sqlite3.Connection) -> tuple[ExistingDocument, ...]:
    return tuple(
        ExistingDocument(
            id=str(row["id"]),
            slug=str(row["slug"]),
            title=str(row["title"]),
            guideline_set=str(row["guideline_set"]),
            document_type=str(row["document_type"]),
            body_digest=docs_store.body_digest(str(row["body"])),
        )
        for row in docs_store.list_documents(conn, limit=None)
    )


def _load_current_document(
    conn: sqlite3.Connection,
    document_id: str,
    configured_destinations: dict[str, DestinationConfig] | None = None,
) -> CurrentDocument:
    from .docgen import destinations

    row = docs_store.get_document(conn, document_id)
    if row is None:
        raise ValueError("matched generated document no longer exists")
    destination = row["delivery_destination"]
    path = row["delivery_path"]
    if destination and path:
        configured = (
            destinations.get_destination(str(destination))
            if configured_destinations is None
            else configured_destinations.get(str(destination))
        )
        if configured is None:
            raise ValueError(
                "The document destination was unavailable when this run started."
            )
        destinations.require_recorded_target(configured, row["delivery_target"])
        return destinations.read_document(
            configured, str(path), document_id, str(row["slug"])
        )
    return CurrentDocument(body=str(row["body"]))
