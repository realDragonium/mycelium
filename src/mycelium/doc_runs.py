"""Thread-per-run documentation executor.

A generation run is one long agent loop rather than a drainable queue, so each
run gets one daemon thread; the concurrency bound is counted from the database
and therefore survives a restart; and `finally: finish_run` means no runner
crash can leave a row unfinished once the worker starts.

The runner hands back the DOCUMENT — slug, title, body — and this module
persists it. That is what lets the whole executor be
proven against a stub returning a canned document, and it puts the write where
the run id and the connection already are, so `last_run_id` needs no extra
plumbing to be correct.

`RUNNER` is that seam's override. Left None — which is the normal case — a
run drives `docgen.run_docgen`; tests set it to a stub, and an explicit
`runner=` argument beats both.

Which document a run writes is decided here, before the run starts, and never
by the model. A revision names its document; a request naming an anchor entity
revises the document holding that identity, if one exists. A request without
either creates a document.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

from . import ai, ai_prompts, docs_store, product_settings, prompt_store
from .ai import Provider
from .docgen import publication
from .docgen.config import DocgenConfig
from .docgen.schema import (
    CurrentDocument,
    ExistingDocument,
    ManualDocument,
    ReviewCheck,
    ReviewRecord,
    RevisionTarget,
)
from .docgen.trace import ReviewNote, RunSummary

if TYPE_CHECKING:
    from .documentation_profiles import CatalogueSnapshot


logger = logging.getLogger(__name__)
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
    manual_document: ManualDocument | None = None,
    anchor_entity_id: str | None = None,
    start_from_destination: bool = False,
    review_notes: Sequence[ReviewNote] = (),
) -> str:
    """Admit a run, deciding first which document it writes.

    `start_from_destination` makes a revision start from the published copy
    even when an unpublished internal revision would otherwise refuse it.
    `review_notes` brief the writer, and only the writer, with what an earlier
    review found.
    """
    # Explicit argument wins; the module-level RUNNER hook only fills in when
    # no runner is passed (tests monkeypatch RUNNER, HTTP callers pass none).
    selected_runner = runner or RUNNER or _default_runner
    config = DocgenConfig.from_env(provider=provider)
    instructions = ai_prompts.resolve("docgen", default_path=config.doctrine_path)
    review_instructions = ai_prompts.resolve("document_review")
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
    from . import documentation_profiles

    profiles = (
        documentation_profiles.capture() if prompt_store.is_configured() else None
    )
    target = _target(
        conn,
        target_document_id,
        expected_revision,
        anchor_entity_id=anchor_entity_id,
        guideline_set=guideline_set,
        document_type=document_type,
        manual=manual_document is not None,
        start_from_destination=start_from_destination,
    )
    if target is not None:
        guideline_set = target.document.guideline_set
        document_type = target.document.document_type
    # A revision of an anchored document is still about its concept.
    writer_anchor = anchor_entity_id or (
        _document_anchor(conn, target.document.id) if target is not None else None
    )

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
            target_document_id=None if target is None else target.document.id,
            target_revision=None if target is None else target.revision,
            anchor_entity_id=anchor_entity_id,
            revision_base=None if target is None else target.base,
            review_notes=review_notes,
        )
        # Anything failing between here and thread.start() must not strand
        # the freshly committed row: finish it as failed, then re-raise.
        try:
            if profiles is not None and guideline_set and document_type:
                _record_profile(conn, run_id, profiles, guideline_set, document_type)
            if manual_document is not None:
                conn.execute(
                    "UPDATE documentation_runs SET draft_title = ?, draft_body = ? WHERE id = ?",
                    (manual_document.title, manual_document.body, run_id),
                )
                conn.commit()
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
            ctx.run(ai.usage.attribute, run_id=run_id)
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
                    target,
                    profiles,
                    instructions,
                    review_instructions,
                    manual_document,
                    anchor_entity_id,
                    writer_anchor,
                    review_notes,
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
                    draft_title=manual_document.title if manual_document else None,
                    draft_body=manual_document.body if manual_document else None,
                )
            except Exception:  # noqa: BLE001 — startup orphan sweep is the backstop
                logger.exception("could not finalize failed start of %s", run_id)
            raise
        return run_id


def _target(
    conn: sqlite3.Connection,
    document_id: str | None,
    expected_revision: int | None,
    *,
    anchor_entity_id: str | None,
    guideline_set: str | None,
    document_type: str | None,
    manual: bool,
    start_from_destination: bool,
) -> RevisionTarget | None:
    """The document a run revises, or None when it creates one."""
    if anchor_entity_id is not None:
        if document_id is not None or manual:
            raise ValueError("A revision already names its document; omit the anchor.")
        anchored = _anchored_document(
            conn, anchor_entity_id, guideline_set, document_type
        )
        if anchored is not None:
            document_id, expected_revision = anchored
    if document_id is None:
        if expected_revision is not None:
            raise ValueError("expected_revision requires a target document")
        if start_from_destination:
            raise ValueError("start_from_destination applies only to a revision.")
        return None
    if expected_revision is None:
        raise ValueError("expected_revision is required to revise a document")
    return _revision_target(
        conn,
        document_id,
        expected_revision,
        manual=manual,
        start_from_destination=start_from_destination,
    )


def _document_anchor(conn: sqlite3.Connection, document_id: str) -> str | None:
    row = docs_store.get_document(conn, document_id)
    return None if row is None else row["anchor_entity_id"]


def _anchored_document(
    conn: sqlite3.Connection,
    anchor_entity_id: str,
    guideline_set: str | None,
    document_type: str | None,
) -> tuple[str, int] | None:
    """The document and head revision an anchored request revises, if one exists."""
    if not guideline_set or not document_type:
        raise ValueError(
            "An anchor entity needs guideline_set and document_type: together "
            "they identify the document."
        )
    anchored = docs_store.find_by_anchor(
        conn, guideline_set, document_type, anchor_entity_id
    )
    if anchored is None:
        return None
    return str(anchored["id"]), int(anchored["current_revision"])


def _revision_target(
    conn: sqlite3.Connection,
    document_id: str,
    expected_revision: int,
    *,
    manual: bool,
    start_from_destination: bool,
) -> RevisionTarget:
    """Pin the version a revision replaces and the text it starts from.

    A model revision of a delivered document reads the published copy first, so
    edits people made on GitHub are its starting point rather than something
    publication later refuses to overwrite. A manual edit keeps the stored sync
    point instead: its text was written against the internal version, and
    publication still refuses it over edits it did not see.
    """
    row = docs_store.require_revision(conn, document_id, expected_revision)
    start = publication.RevisionStart(
        CurrentDocument(body=str(row["body"])), "internal"
    )
    delivered = bool(row["delivery_destination"] and row["delivery_path"])
    if start_from_destination and (manual or not delivered):
        raise ValueError(
            "This document has no published copy to start from."
            if not delivered
            else "A manual edit supplies its own text; it cannot start from GitHub's."
        )
    if delivered and not manual:
        start = publication.revision_start(
            row,
            publication.destination_text(row),
            docs_store.published_blobs(conn, document_id),
            start_from_destination=start_from_destination,
        )
    return RevisionTarget(
        document=ExistingDocument(
            id=document_id,
            slug=str(row["slug"]),
            title=str(row["title"]),
            guideline_set=str(row["guideline_set"]),
            document_type=str(row["document_type"]),
            body_digest=docs_store.body_digest(str(row["body"])),
        ),
        revision=expected_revision,
        current=start.current,
        base=start.base,
    )


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
    audience = profiles.audience(set_name)
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
                    "audience": asdict(audience) if audience is not None else None,
                }
            ),
            run_id,
        ),
    )
    conn.commit()


def _review_notes(review: object) -> list[ReviewNote]:
    """The failed checks' findings of a review the runner reported."""
    if review is None:
        return []
    record = ReviewRecord.model_validate(review)
    checks: list[tuple[Literal["exposure", "conformance"], ReviewCheck]] = [
        ("exposure", record.exposure),
        ("conformance", record.conformance),
    ]
    return [
        ReviewNote(check=name, where=finding.where, problem=finding.problem)
        for name, check in checks
        if check.status == "fail"
        for finding in check.findings
    ]


def wait_all(timeout: float = 10.0) -> None:
    for thread in list(_threads.values()):
        thread.join(timeout)


def _default_runner(
    prompt: str,
    *,
    guideline_set: str | None = None,
    document_type: str | None = None,
    config: DocgenConfig | None = None,
    revision_target: RevisionTarget | None = None,
    manual_document: ManualDocument | None = None,
    profiles: CatalogueSnapshot | None = None,
    instructions: ai_prompts.Snapshot | None = None,
    review_instructions: ai_prompts.Snapshot | None = None,
    anchor_entity_id: str | None = None,
    run_id: str | None = None,
    on_progress: Callable[[RunSummary], None] | None = None,
    review_notes: Sequence[ReviewNote] = (),
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
        revision_target=revision_target,
        manual_document=manual_document,
        profiles=profiles,
        instructions=instructions,
        review_instructions=review_instructions,
        anchor_entity_id=anchor_entity_id,
        run_id=run_id,
        on_progress=on_progress,
        review_notes=review_notes,
    )


def _execute_run(
    run_id: str,
    prompt: str,
    guideline_set: str | None,
    document_type: str | None,
    db_path: str,
    runner: Callable[..., Any],
    config: DocgenConfig | None = None,
    revision_target: RevisionTarget | None = None,
    profiles: CatalogueSnapshot | None = None,
    instructions: ai_prompts.Snapshot | None = None,
    review_instructions: ai_prompts.Snapshot | None = None,
    manual_document: ManualDocument | None = None,
    anchor_entity_id: str | None = None,
    writer_anchor: str | None = None,
    review_notes: Sequence[ReviewNote] = (),
) -> None:
    own_conn = None
    conn = _in_memory_conns.pop(run_id, None)

    outcome = "failed"
    document_id = None
    error = None
    draft_title = manual_document.title if manual_document else None
    draft_body = manual_document.body if manual_document else None
    matched_document_id = None
    summary = None

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
        # and the saved documentation run limit already bounds how many can be
        # queued behind it. The row stays 'running' while waiting, which is honest:
        # the run has been accepted and nothing else needs to happen to it.
        from . import server

        def progress(update: RunSummary) -> None:
            assert conn is not None
            docs_store.record_progress(conn, run_id, update)

        with server.model_loop_slot():
            if runner is _default_runner:
                result = runner(
                    prompt,
                    guideline_set=guideline_set,
                    document_type=document_type,
                    config=config,
                    revision_target=revision_target,
                    manual_document=manual_document,
                    profiles=profiles,
                    instructions=instructions,
                    review_instructions=review_instructions,
                    anchor_entity_id=writer_anchor,
                    run_id=run_id,
                    on_progress=progress,
                    review_notes=review_notes,
                )
            else:
                result = runner(
                    prompt, guideline_set=guideline_set, document_type=document_type
                )
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        trace = payload.get("trace")
        summary = trace.get("summary") if isinstance(trace, dict) else None
        # The request may have named neither, in which case the run chose. Put
        # the choice on the row before the outcome is decided, so a run that
        # settled on a set and then found nothing to say still shows what it
        # was trying to write. COALESCE in the store means a runner that
        # reports neither leaves whatever the request named standing. A
        # revision or an anchored request named both as part of its identity.
        fixed = revision_target is not None or anchor_entity_id is not None
        selected_set = (
            guideline_set if fixed else payload.get("guideline_set") or guideline_set
        )
        selected_type = (
            document_type if fixed else payload.get("document_type") or document_type
        )
        docs_store.mark_started(
            conn,
            run_id,
            guideline_set=guideline_set if fixed else payload.get("guideline_set"),
            document_type=document_type if fixed else payload.get("document_type"),
        )
        reported = payload.get("outcome")
        matched_document_id = (
            revision_target.document.id if revision_target is not None else None
        )
        if profiles is not None and selected_set and selected_type:
            _record_profile(conn, run_id, profiles, selected_set, selected_type)
        if reported not in ("document_written", "nothing_written"):
            # Not folded into `nothing_written`: a runner that returns junk, or
            # reports its own failure, would otherwise be recorded as a clean
            # refusal with no reason. Raising lands it on `error` as what it is.
            raise ValueError(f"runner returned an unknown outcome: {reported!r}")
        if reported == "document_written":
            if manual_document is not None and (
                payload.get("title") != manual_document.title
                or payload.get("body") != manual_document.body
            ):
                raise ValueError(
                    "Manual document text changed during review; edit not saved"
                )
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
            draft_title = payload["title"]
            draft_body = payload["body"]
            # Written before `outcome` is set, so a rejected document (a
            # refused collision, blank slug, or unwritable DB) finishes the run
            # failed rather than claiming a document that is not there. A
            # creation run never writes into an existing document.
            document_id = docs_store.upsert_document(
                conn,
                slug=revision_target.document.slug
                if revision_target is not None
                else payload["slug"],
                title=payload["title"],
                body=payload["body"],
                guideline_set=selected_set,
                document_type=selected_type,
                statement_ids=payload.get("statement_ids"),
                cited_statements=payload.get("cited_statements"),
                # The loop and DocumentWritten enforce that review ran. This
                # overridable runner seam accepts older canned runners instead
                # of making their missing record fatal; the store writes `{}`.
                review=payload.get("review"),
                run_id=run_id,
                updates=revision_target.document.id
                if revision_target is not None
                else None,
                expected_revision=revision_target.revision
                if revision_target is not None
                else None,
                replacing=revision_target.document.body_digest
                if revision_target is not None
                else None,
                revision_source_content_revision=revision_target.current.content_revision
                if revision_target is not None
                else None,
                anchor_entity_id=anchor_entity_id if revision_target is None else None,
            )
            outcome = "document_written"
            draft_title = None
            draft_body = None
        else:
            outcome = "nothing_written"
            # Keeping the reason verbatim is how a rejected document's review
            # findings reach the run row; a bare status would discard them.
            error = payload.get("reason")
            if summary is not None and (notes := _review_notes(payload.get("review"))):
                summary = {**summary, "review_findings": notes}
            # The findings quote a document, so the document is kept beside
            # them. Present only when one was written and refused.
            draft_title = payload.get("title") or draft_title
            draft_body = payload.get("body") or draft_body
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
                summary=summary,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not finalize documentation run %s", run_id)
        finally:
            if own_conn is not None:
                own_conn.close()
            _threads.pop(run_id, None)
