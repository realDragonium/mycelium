"""Documentation entry points: requesting, revising, reading and delivering documents.

A documentation run turns substrate knowledge into a human-facing document. It
is a projection, never evidence, so nothing here writes the substrate.
`request_documentation` and `revise_document` start a background run and
return its id; `deliver_document` hands a finished document to a configured
destination, such as a GitHub pull request.
"""

from __future__ import annotations

import json as _json
import sqlite3
from typing import Any, Literal

from .. import store
from ..require import require
from .registry import tool
from .runtime import _db, _drafts_db, _prompts_db


def _check_guideline_selection(
    guideline_set: str | None, document_type: str | None
) -> None:
    """Refuse a guideline set, or a document type within one, that nothing is
    stored under.

    Sets are not a registry to consult: they are prompt-store rows named
    `<set>/<slot>` (docs/GUIDELINE_SETS.md), so "does this set exist" is "are
    there live rows with that prefix" — answered from the same listing that
    names the alternatives back to the caller.

    A document type is only checkable once a set is named, since the template
    is a row of that set. Named together, both are checked here rather than
    left to fail deep inside a background run whose only report is an `error`
    column read minutes later.

    The listing comes from `guidelines.catalogue`, which is also what the
    generation loop resolves against — so a request this refuses is exactly a
    request the run could not have written, and vice versa.
    """
    from .. import guidelines

    if guideline_set is None:
        return

    catalogue = guidelines.catalogue(_prompts_db())
    if guideline_set not in catalogue:
        raise ValueError(
            f"unknown guideline set '{guideline_set}'; configured: {sorted(catalogue)}"
        )
    if document_type is None:
        return
    available = catalogue[guideline_set]
    if document_type not in available:
        raise ValueError(
            f"guideline set '{guideline_set}' has no template for document type "
            f"'{document_type}'; available: {available}"
        )


def _optional_name(value: str | None) -> str | None:
    """A caller-supplied optional name, normalized: blank is not a name."""
    return value.strip() or None if value is not None else None


@tool(role="writer", real_role=True)
def request_documentation(
    prompt: str,
    guideline_set: str | None = None,
    document_type: str | None = None,
    provider: Literal["claude", "openai"] | None = None,
    anchor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Request a background documentation run: generate one document from
    `prompt` and store it as a generated document.

    Writers and admins only — `real_role`, so the drafter equivalence does not
    apply. A drafter clears write gates because the wrapper redirects their
    writes onto a reviewable draft, and this tool sits outside that machinery:
    what it produces lands live and is served to readers as it stands.

    Returns immediately with the serialized run row (its `status` will be
    "running"); poll `get_documentation_run(run_id)` for the outcome and
    `get_generated_document(document_id)` for what it wrote. `guideline_set`
    picks the writing guidance (see `list_prompt_texts(type="guideline-set")`)
    and `document_type` the template within it; left out, they stay null on
    the row and the run resolves them. Raises when the active-run cap is
    reached (saved documentation active-run limit, default 2), when `guideline_set` is
    unknown, when `document_type` is not one that set can write, or when
    `prompt` is blank or longer than the saved prompt length limit.
    `provider` selects claude or openai; omitted uses saved documentation settings
    (default claude). The configured model is captured for writing and review.
    Use list_documentation_models for available choices.
    `anchor_entity_id` names the entity the document is about. With
    `guideline_set` and `document_type` (both required alongside it) it is the
    document's identity: a repeat request revises the document holding that
    identity instead of creating a second one. Without an anchor the request
    creates a document; to change an existing one, call revise_document.
    Returns {run row: id, prompt, guideline_set, document_type, provider, model, status,
    created_at, created_by, started_at, finished_at, outcome, document_id,
    error}."""
    from .. import auth as _auth
    from .. import doc_runs, docs_store
    from ..docgen import DocgenConfig

    text = prompt.strip()
    if not text:
        raise ValueError("prompt is required")
    max_chars = DocgenConfig.from_env().max_prompt_chars
    if len(text) > max_chars:
        raise ValueError(
            f"prompt is {len(text)} characters; the limit is {max_chars} "
            "(documentation prompt limit)"
        )

    guideline_set = _optional_name(guideline_set)
    document_type = _optional_name(document_type)
    _check_guideline_selection(guideline_set, document_type)
    anchor_entity_id = _optional_name(anchor_entity_id)
    if anchor_entity_id is not None and (
        store.get_entity_by_id(_db(), anchor_entity_id) is None
    ):
        raise ValueError(f"anchor entity not found: {anchor_entity_id}")

    principal = _auth.current_principal.get()
    created_by = principal.id if principal is not None else None
    run_id = doc_runs.start_run(
        prompt=text,
        guideline_set=guideline_set,
        document_type=document_type,
        created_by=created_by,
        conn=_drafts_db(),
        provider=provider,
        anchor_entity_id=anchor_entity_id,
    )
    row = require(
        docs_store.get_run(_drafts_db(), run_id), "documentation run just created"
    )
    return docs_store.serialize_run(row)


@tool(role="writer", real_role=True)
def revise_document(
    document_id: str,
    expected_revision: int,
    prompt: str = "",
    provider: Literal["claude", "openai"] | None = None,
    start_from_destination: bool = False,
    update_sources: bool = False,
) -> dict[str, object]:
    """Iterate on exactly the selected internal document version.

    A delivered document's revision starts from its published copy when
    people edited it there and nothing here is unpublished. When both sides
    changed, the request is refused before a run exists; pass
    `start_from_destination` to start from the published text anyway, keeping
    the unpublished revision in history.

    `update_sources` brings an out-of-date document (see `stale` on
    get_generated_document) up to date: the run is briefed with the cited
    statements that changed, after any `prompt`, which may then be blank.
    Returns the serialized run row, whose `revision_base` says which text the
    run started from."""
    from .. import auth, doc_runs, docs_store, document_freshness
    from ..docgen.config import DocgenConfig

    text = prompt.strip()
    if not text and not update_sources:
        raise ValueError("prompt is required")
    if len(text) > DocgenConfig.from_env().max_prompt_chars:
        raise ValueError(
            "The revision instructions exceed the documentation prompt limit."
        )
    row = docs_store.require_revision(_drafts_db(), document_id, expected_revision)
    _check_guideline_selection(str(row["guideline_set"]), str(row["document_type"]))
    if update_sources:
        freshness = document_freshness.for_documents(_drafts_db(), _db, [document_id])[
            document_id
        ]
        if freshness.status != "out_of_date":
            raise ValueError("None of the statements this document cites changed.")
        brief = document_freshness.revision_brief(freshness.changes)
        text = f"{text}\n\n{brief}" if text else brief
    principal = auth.current_principal.get()
    run_id = doc_runs.start_run(
        prompt=text,
        guideline_set=str(row["guideline_set"]),
        document_type=str(row["document_type"]),
        created_by=principal.id if principal is not None else None,
        conn=_drafts_db(),
        provider=provider,
        target_document_id=document_id,
        expected_revision=expected_revision,
        start_from_destination=start_from_destination,
    )
    return docs_store.serialize_run(
        require(docs_store.get_run(_drafts_db(), run_id), "new documentation run")
    )


def _retry_refusal(row: sqlite3.Row) -> str | None:
    from .. import document_edits

    if row["outcome"] not in ("nothing_written", "failed"):
        return "Only a run that wrote nothing can be retried."
    if row["prompt"] == document_edits.MANUAL_EDIT_PROMPT:
        return "Edit the document again to retry a manual edit."
    return None


def retry_documentation_run(
    run_id: str, *, with_review_notes: bool = False
) -> dict[str, object]:
    """Start a run that wrote nothing again: the same request, profile, type
    and concept, or a revision of the same document. `with_review_notes`
    briefs the writer with what the refusing review found; the request text
    the next review reads stays as it was."""
    from .. import auth, doc_runs, docs_store

    row = docs_store.get_run(_drafts_db(), run_id)
    if row is None:
        raise LookupError(f"documentation run not found: {run_id}")
    refusal = _retry_refusal(row)
    if refusal is not None:
        raise ValueError(refusal)
    summary = _json.loads(row["summary"]) if row["summary"] else {}
    notes = summary.get("review_findings") or [] if with_review_notes else []
    if with_review_notes and not notes:
        raise ValueError("This run has no review notes to retry with.")
    if row["guideline_set"] and row["document_type"]:
        _check_guideline_selection(str(row["guideline_set"]), str(row["document_type"]))
    # An anchored run finds its concept's document afresh, at its current
    # revision; any other revision run retries the revision it started from.
    anchored = row["anchor_entity_id"] is not None
    principal = auth.current_principal.get()
    new_id = doc_runs.start_run(
        prompt=str(row["prompt"]),
        guideline_set=row["guideline_set"],
        document_type=row["document_type"],
        created_by=principal.id if principal is not None else None,
        conn=_drafts_db(),
        provider=row["provider"],
        target_document_id=None if anchored else row["target_document_id"],
        expected_revision=None if anchored else row["target_revision"],
        anchor_entity_id=row["anchor_entity_id"],
        start_from_destination=not anchored and row["revision_base"] == "destination",
        review_notes=notes,
    )
    return docs_store.serialize_run(
        require(docs_store.get_run(_drafts_db(), new_id), "new documentation run")
    )


@tool
def list_document_revisions(document_id: str) -> dict[str, object]:
    """List the stored versions of a document, newest first, without bodies."""
    from .. import docs_store

    if docs_store.get_document(_drafts_db(), document_id) is None:
        raise ValueError("generated document not found")
    return {
        "revisions": [
            docs_store.serialize_revision(row, include_body=False)
            for row in docs_store.list_revisions(_drafts_db(), document_id)
        ]
    }


@tool
def get_document_revision(document_id: str, revision: int) -> dict[str, object]:
    """Read an immutable version with grounding, review and generation backlink."""
    from .. import docs_store

    row = docs_store.get_revision(_drafts_db(), document_id, revision)
    if row is None:
        raise ValueError("generated document revision not found")
    result = docs_store.serialize_revision(row)
    delivery = (
        _drafts_db()
        .execute(
            "SELECT destination, target, path, reference, content_revision, created_at "
            "FROM generated_document_deliveries WHERE document_id = ? AND revision = ?",
            (document_id, revision),
        )
        .fetchone()
    )
    result["delivery"] = (
        None
        if delivery is None
        else {
            "destination": delivery["destination"],
            "coordinates": _json.loads(delivery["target"]),
            "path": delivery["path"],
            "reference": delivery["reference"],
            "content_revision": delivery["content_revision"],
            "created_at": delivery["created_at"],
        }
    )
    return result


@tool
def list_documentation_models() -> dict[str, object]:
    """List configured documentation providers and safe availability reasons."""
    from ..docgen.config import model_choices, resolve_provider

    return {"default_provider": resolve_provider(), "models": model_choices()}


@tool
def list_documentation_runs() -> dict[str, Any]:
    """List documentation runs, newest first, each with a derived `status`
    (queued/running/document_written/document_superseded/nothing_written/failed).
    A run whose page was replaced reports `document_superseded`, while its
    stored `outcome` remains `document_written`; the matching
    `document_superseded` boolean stays as explanatory detail.

    Each row carries `draft_chars` rather than the draft itself; fetch one run
    with get_documentation_run to read the text a refused run wrote.

    Returns {"runs": [run rows]}."""
    from .. import docs_store

    return {
        "runs": [
            docs_store.serialize_run(row) for row in docs_store.list_runs(_drafts_db())
        ]
    }


@tool
def get_documentation_run(run_id: str) -> dict[str, Any]:
    """Fetch one documentation run by id, including outcome, document_id,
    error, derived `status`, and `document_superseded`. A run whose page was
    replaced reports status `document_superseded`, not `document_written`,
    while its stored outcome remains `document_written`; the boolean stays as
    explanatory detail.

    A run the review gate turned down carries the draft it refused, as
    `draft_title` and `draft_body`, so the findings can be read against the
    text they quote. Both are null when no document was written.

    `retryable` says whether the run can be started again as it was.

    Returns the serialized run row. Raises for an unknown run_id."""
    from .. import docs_store

    row = docs_store.get_run(_drafts_db(), run_id)
    if row is None:
        raise ValueError(f"documentation run not found: {run_id}")
    return {
        **docs_store.serialize_run_detail(row),
        "retryable": _retry_refusal(row) is None,
    }


@tool
def list_generated_documents() -> dict[str, Any]:
    """List generated documents, newest first, omitting each document body.

    Each carries `stale`: {status, changes}. `status` is "out_of_date" once a
    statement the current revision cites was edited, deleted or merged away
    since it was reviewed, or relabelled so the document's audience may no
    longer see it; "current" otherwise, and "unknown" for a revision saved
    before citations were recorded. Each change gives `statement_id`, `change`
    (edited/deleted/merged/no_longer_visible), `old_text`, `new_text` and
    `merged_into`; revise_document(update_sources=True) addresses them.

    Returns {"documents": [document summaries]}; get_generated_document returns
    the body."""
    from .. import docs_store, principal_audience

    rows = docs_store.list_documents(_drafts_db(), limit=None)
    scope = principal_audience.current_scope()
    if scope is not None:
        readable = principal_audience.readable_documents(
            _drafts_db(), [str(row["id"]) for row in rows], scope
        )
        rows = [row for row in rows if row["id"] in readable]
    stale = _freshness([str(row["id"]) for row in rows], scoped=scope is not None)
    audiences = _document_audiences(rows)
    return {
        "documents": [
            {
                **docs_store.serialize_document_summary(row),
                "stale": stale[row["id"]],
                "audience": audiences[row["id"]],
            }
            for row in rows
        ]
    }


@tool
def get_generated_document(document_id: str) -> dict[str, Any]:
    """Fetch one generated document by id, including its body.

    A document with a pull request first asks GitHub what became of it, at
    most once a minute; `pull_request.refreshed_at` says when the state shown
    was read. `stale` is as in list_generated_documents. Returns the
    serialized document row. Raises for an unknown
    document_id."""
    from .. import docs_store, principal_audience
    from ..docgen import publication

    scope = principal_audience.current_scope()
    if scope is not None and document_id not in (
        principal_audience.readable_documents(_drafts_db(), [document_id], scope)
    ):
        raise ValueError(f"generated document not found: {document_id}")
    publication.refresh_pull_request(_drafts_db(), document_id)
    row = docs_store.get_document(_drafts_db(), document_id)
    if row is None:
        raise ValueError(f"generated document not found: {document_id}")
    return {
        **docs_store.serialize_document(row),
        "stale": _freshness([document_id], scoped=scope is not None)[document_id],
        "audience": _document_audiences([row])[document_id],
    }


def _document_audiences(
    rows: list[sqlite3.Row],
) -> dict[str, dict[str, str] | None]:
    """The audience the run behind each document's current revision wrote
    for, from that run's profile snapshot. None for a document written
    before runs recorded one."""
    run_ids = sorted({str(row["last_run_id"]) for row in rows if row["last_run_id"]})
    written: dict[str, dict[str, str]] = {}
    for offset in range(0, len(run_ids), 500):
        chunk = run_ids[offset : offset + 500]
        for run in _drafts_db().execute(
            "SELECT id, json_extract(profile_snapshot, '$.audience') AS audience "
            f"FROM documentation_runs WHERE id IN ({', '.join('?' for _ in chunk)})",
            chunk,
        ):
            if run["audience"] is None:
                continue
            audience = _json.loads(run["audience"])
            written[str(run["id"])] = {
                "id": str(audience["id"]),
                "name": str(audience["name"]),
                "scope": str(audience["scope"]),
            }
    return {str(row["id"]): written.get(str(row["last_run_id"])) for row in rows}


def _freshness(
    document_ids: list[str], *, scoped: bool = False
) -> dict[str, dict[str, object]]:
    """Each document's freshness. A scoped reader gets the status only: the
    changes quote statement text, old and new, whatever its audience."""
    from .. import document_freshness

    return {
        document_id: {**freshness.as_dict(), "changes": []}
        if scoped
        else freshness.as_dict()
        for document_id, freshness in document_freshness.for_documents(
            _drafts_db(), _db, document_ids
        ).items()
    }


@tool(role="writer", real_role=True)
def deliver_document(
    document_id: str,
    destination: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Publish a selected internal version through its GitHub review flow.

    Existing documents reuse recorded repository coordinates and path. A receipt
    belongs to the captured immutable version even when generation advances the
    document while GitHub is processing the publication. The pull request is
    tracked: get_generated_document reports whether it is open, merged or
    closed. Returns {destination, path, reference, content_revision,
    pull_request_number, revision}.
    """
    from ..docgen import publication

    return publication.publish(
        _drafts_db(), document_id, destination, expected_revision
    )


@tool
def list_documentation_destinations() -> dict[str, Any]:
    """List configured documentation destinations by generic identity.

    Returns no credential and no credential environment variable name.
    """
    from ..docgen import destinations

    try:
        configured = destinations.load_destinations()
    except destinations.DestinationError as exc:
        raise ValueError(str(exc)) from None
    return {
        "destinations": [
            {
                "name": destination.name,
                "type": destination.type,
                "path_template": destination.path_template,
                "coordinates": destinations.destination_coordinates(destination),
            }
            for destination in configured.values()
        ]
    }
