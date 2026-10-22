"""Documentation entry points: requesting, revising, reading and delivering documents.

A documentation run turns substrate knowledge into a human-facing document. It
is a projection, never evidence, so nothing here writes the substrate.
`request_documentation` and `revise_document` start a background run and
return its id; `deliver_document` hands a finished document to a configured
destination, such as a GitHub pull request.
"""

from __future__ import annotations

import json as _json
from typing import Any, Literal

from ..require import require
from .registry import tool
from .runtime import _drafts_db, _prompts_db


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
    match_existing: bool = True,
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
    match_existing defaults to True; False disables matching an existing document.
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

    principal = _auth.current_principal.get()
    created_by = principal.id if principal is not None else None
    run_id = doc_runs.start_run(
        prompt=text,
        guideline_set=guideline_set,
        document_type=document_type,
        created_by=created_by,
        conn=_drafts_db(),
        provider=provider,
        match_existing=match_existing,
    )
    row = require(
        docs_store.get_run(_drafts_db(), run_id), "documentation run just created"
    )
    return docs_store.serialize_run(row)


@tool(role="writer", real_role=True)
def revise_document(
    document_id: str,
    expected_revision: int,
    prompt: str,
    provider: Literal["claude", "openai"] | None = None,
) -> dict[str, object]:
    """Iterate on exactly the selected internal document version."""
    from .. import auth, doc_runs, docs_store
    from ..docgen.config import DocgenConfig

    text = prompt.strip()
    if not text:
        raise ValueError("prompt is required")
    if len(text) > DocgenConfig.from_env().max_prompt_chars:
        raise ValueError(
            "The revision instructions exceed the documentation prompt limit."
        )
    row = docs_store.require_revision(_drafts_db(), document_id, expected_revision)
    _check_guideline_selection(str(row["guideline_set"]), str(row["document_type"]))
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
        match_existing=False,
    )
    return docs_store.serialize_run(
        require(docs_store.get_run(_drafts_db(), run_id), "new documentation run")
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

    Returns the serialized run row. Raises for an unknown run_id."""
    from .. import docs_store

    row = docs_store.get_run(_drafts_db(), run_id)
    if row is None:
        raise ValueError(f"documentation run not found: {run_id}")
    return docs_store.serialize_run_detail(row)


@tool
def list_generated_documents() -> dict[str, Any]:
    """List generated documents, newest first, omitting each document body.

    Returns {"documents": [document summaries]}; get_generated_document returns
    the body."""
    from .. import docs_store

    return {
        "documents": [
            docs_store.serialize_document_summary(row)
            for row in docs_store.list_documents(_drafts_db(), limit=None)
        ]
    }


@tool
def get_generated_document(document_id: str) -> dict[str, Any]:
    """Fetch one generated document by id, including its body.

    Returns the serialized document row. Raises for an unknown document_id."""
    from .. import docs_store

    row = docs_store.get_document(_drafts_db(), document_id)
    if row is None:
        raise ValueError(f"generated document not found: {document_id}")
    return docs_store.serialize_document(row)


@tool(role="writer", real_role=True)
def deliver_document(
    document_id: str,
    destination: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Publish a selected internal version through its GitHub review flow.

    Existing documents reuse recorded repository coordinates and path. A receipt
    belongs to the captured immutable version even when generation advances the
    document while GitHub is processing the publication.
    """
    from .. import docs_store
    from ..docgen import destinations

    with destinations.publication_lock(document_id):
        row = docs_store.get_document(_drafts_db(), document_id)
        if row is None:
            raise ValueError("generated document not found")
        revision = (
            int(row["current_revision"])
            if expected_revision is None
            else expected_revision
        )
        row = docs_store.require_revision(_drafts_db(), document_id, revision)
        try:
            configured, binding = destinations.publishing_destination(row, destination)
        except destinations.DestinationError as exc:
            raise ValueError(str(exc)) from None
        document = destinations.DeliveryDocument(
            id=str(row["id"]),
            slug=str(row["slug"]),
            title=str(row["title"]),
            body=str(row["body"]),
            guideline_set=str(row["guideline_set"]),
            document_type=str(row["document_type"]),
            statement_ids=tuple(_json.loads(row["statement_ids"])),
            delivered_path=str(row["delivery_path"])
            if row["delivery_path"] is not None
            else None,
            delivered_content_revision=str(row["delivery_content_revision"])
            if row["delivery_content_revision"] is not None
            else None,
            revision_source_content_revision=str(
                row["revision_source_content_revision"]
            )
            if row["revision_source_content_revision"] is not None
            else None,
        )
        try:
            delivery = destinations.deliver_document(configured, document)
        except destinations.DestinationError as exc:
            raise ValueError(str(exc)) from None
        docs_store.record_delivery(
            _drafts_db(),
            document_id,
            destination=delivery.destination,
            path=delivery.path,
            reference=delivery.reference,
            content_revision=delivery.content_revision,
            target=destinations.target_identity(configured),
            revision=revision,
            binding=binding,
        )
        return {**delivery.serialize(), "revision": revision}


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
