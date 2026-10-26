"""The documentation workspace over every transport: its lists, a document's
history, a person's edits, retries and the decisions on a writing profile's
plan.

Reads are open to any caller; anything that writes or starts a run needs a real
writer, as in the web app, whose documentation routes call these same
functions.
"""

from __future__ import annotations

import difflib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .. import (
    auth,
    document_maintenance,
    documentation_planning,
    product_settings,
)
from ..docgen.schema import ManualDocument
from .documentation import (
    get_document_revision,
    get_documentation_run,
    list_document_revisions,
    list_documentation_destinations,
    list_documentation_models,
    list_documentation_runs,
    list_generated_documents,
    retry_documentation_run,
)
from .registry import tool
from .runtime import _caller, _drafts_db


def _profile_audiences() -> dict[str, dict[str, str] | None]:
    """Which audience each profile writes for, so the generate form can say."""
    from .. import documentation_profiles

    snapshot = documentation_profiles.capture()
    return {
        profile.name: (
            {"id": audience.id, "name": audience.name, "scope": audience.scope}
            if (audience := snapshot.audience(profile.name)) is not None
            else None
        )
        for profile in snapshot.profiles
    }


def documentation_options(principal: auth.Principal) -> dict[str, object]:
    from .. import guidelines, prompt_store
    from ..docgen.config import DocgenConfig

    return {
        **list_documentation_models(),
        "can_generate": auth.principal_has_real_role(principal, "writer"),
        "guideline_sets": guidelines.catalogue(prompt_store.connection()),
        "profile_audiences": _profile_audiences(),
        "max_prompt_chars": DocgenConfig.from_env().limits.max_prompt_chars,
    }


DocumentationList = Literal[
    "documents", "runs", "destinations", "options", "maintenance"
]


@tool
def list_documentation(
    kind: DocumentationList = "documents",
) -> dict[str, object]:
    """List what the Documents workspace shows.

    `documents`: every generated document with its profile, type, concept,
    revision and whether it is out of date. `runs`: recent documentation
    runs with their status. `destinations`: the configured places documents
    are delivered to. `options`: the models a run may use, the writing
    profiles with their document types and the audience each writes for,
    the longest request allowed and whether the caller may start runs.
    `maintenance`: documents kept current by their profile's maintenance
    policy, with what is waiting or failed."""
    if kind == "documents":
        return list_generated_documents()
    if kind == "runs":
        return list_documentation_runs()
    if kind == "destinations":
        return list_documentation_destinations()
    if kind == "options":
        return documentation_options(_caller())
    return document_maintenance.feed(_drafts_db()).model_dump(mode="json")


_DIFF_OPS: dict[str, Literal["+", "-", " "]] = {"+": "+", "-": "-", " ": " "}


class DiffLine(BaseModel):
    #: "+" added, "-" removed, " " unchanged context, "@" a hunk header.
    op: Literal["+", "-", " ", "@"]
    text: str


class RevisionDiff(BaseModel):
    document_id: str
    from_revision: int
    to_revision: int
    lines: list[DiffLine]


def revision_diff(document_id: str, revision: int) -> RevisionDiff:
    """A revision's body against the one it was revised from."""
    from .. import docs_store

    conn = _drafts_db()
    new = docs_store.get_revision(conn, document_id, revision)
    if new is None:
        raise LookupError("revision not found")
    previous_revision = int(new["parent_revision"] or revision - 1)
    old = docs_store.get_revision(conn, document_id, previous_revision)
    if old is None:
        raise LookupError("no earlier revision to compare")
    diff = list(
        difflib.unified_diff(
            str(old["body"]).splitlines(),
            str(new["body"]).splitlines(),
            lineterm="",
            n=2,
        )
    )[2:]  # the ---/+++ file headers
    lines = [
        DiffLine(op="@", text=line)
        if line.startswith("@@")
        else DiffLine(op=_DIFF_OPS[line[0]], text=line[1:])
        for line in diff
    ]
    return RevisionDiff(
        document_id=document_id,
        from_revision=previous_revision,
        to_revision=revision,
        lines=lines,
    )


@tool
def get_document_history(
    document_id: str, revision: int | None = None, diff: bool = False
) -> dict[str, object]:
    """Read a generated document's history, as its History tab shows it.

    Without `revision`: every revision with who or what made it and why.
    With `revision`: that revision's title and body; with `diff` as well,
    its body against the revision it was revised from, line by line."""
    if revision is None:
        return list_document_revisions(document_id)
    if diff:
        return revision_diff(document_id, revision).model_dump(mode="json")
    return get_document_revision(document_id, revision)


class EditSaved(ManualDocument):
    action: Literal["saved"]
    document_id: str
    #: The document's current revision; a stale one is refused.
    expected_revision: int = Field(ge=1, strict=True)
    provider: Literal["claude", "openai"] | None = None


class EditDraft(ManualDocument):
    action: Literal["draft"]
    run_id: str
    provider: Literal["claude", "openai"] | None = None


DocumentEdit = Annotated[EditSaved | EditDraft, Field(discriminator="action")]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_document_edit: TypeAdapter[DocumentEdit] = TypeAdapter(DocumentEdit)


def edit_saved(
    document_id: str,
    expected_revision: int,
    document: ManualDocument,
    provider: Literal["claude", "openai"] | None,
    created_by: str,
) -> dict[str, object]:
    from .. import document_edits

    run_id = document_edits.start_document_edit(
        _drafts_db(),
        document_id,
        expected_revision,
        document,
        created_by=created_by,
        provider=provider,
    )
    return get_documentation_run(run_id)


def edit_draft(
    run_id: str,
    document: ManualDocument,
    provider: Literal["claude", "openai"] | None,
    created_by: str,
) -> dict[str, object]:
    from .. import document_edits

    new_run_id = document_edits.start_draft_edit(
        _drafts_db(),
        run_id,
        document,
        created_by=created_by,
        provider=provider,
    )
    return get_documentation_run(new_run_id)


@tool(role="writer", real_role=True)
def edit_document(request: DocumentEdit) -> dict[str, object]:
    """Save a person's own edit of a document's title and body, as the
    document editor does. The edit goes through the same review a written
    revision does, as a run. Real writers and admins only.

    `saved` edits a saved document (`document_id`) at its
    `expected_revision`; `draft` edits the result of a run (`run_id`) that
    has not been saved.
    `provider` picks the reviewing model, or the saved choice when omitted.
    Returns the run; follow it with `get_documentation_run`."""
    request = _document_edit.validate_python(request)
    document = ManualDocument(title=request.title, body=request.body)
    if isinstance(request, EditSaved):
        return edit_saved(
            request.document_id,
            request.expected_revision,
            document,
            request.provider,
            _caller().id,
        )
    return edit_draft(request.run_id, document, request.provider, _caller().id)


@tool(role="writer", real_role=True)
def retry_documentation(
    run_id: str | None = None,
    item_id: str | None = None,
    with_review_notes: bool = False,
) -> dict[str, object]:
    """Start a documentation run that wrote nothing again, as Retry does in
    the web app: the run `run_id` with the same request, profile, type and
    concept, or the run of the plan item `item_id`. Give exactly one.
    `with_review_notes` briefs the writer with the findings of the review
    that refused it. A person's retry starts the profile's recovery count
    again. Real writers and admins only. Returns the new run."""
    if (run_id is None) == (item_id is None):
        raise ValueError("Give exactly one of run_id or item_id.")
    if run_id is not None:
        return retry_documentation_run(run_id, with_review_notes=with_review_notes)
    assert item_id is not None
    return documentation_planning.retry(item_id, with_review_notes=with_review_notes)


class ApprovedItem(BaseModel):
    item_id: str
    run: dict[str, object] | None = None
    error: str | None = None


def approve_items(item_ids: list[str], decided_by: str) -> list[ApprovedItem]:
    """Approve several items; each starts its own run, and one that cannot
    start reports why without stopping the rest."""
    limit = product_settings.get(
        product_settings.DocumentationPlanningSettings
    ).approve_batch
    if len(item_ids) > limit:
        raise ValueError(f"Approve at most {limit} items at a time.")
    results: list[ApprovedItem] = []
    for item_id in dict.fromkeys(item_ids):
        try:
            run = documentation_planning.approve(item_id, decided_by=decided_by)
        except (ValueError, LookupError) as exc:
            results.append(ApprovedItem(item_id=item_id, error=str(exc)))
        else:
            results.append(ApprovedItem(item_id=item_id, run=run))
    return results


class ApproveItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve"]
    item_ids: list[str] = Field(min_length=1)


class DismissItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["dismiss_item"]
    item_id: str


class UncoveredStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["dismiss_uncovered", "restore_uncovered"]
    guideline_set: str
    statement_id: str


class DismissStale(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["dismiss_stale"]
    guideline_set: str
    document_id: str
    #: The out-of-date revision being dismissed.
    revision: int = Field(ge=1, strict=True)


PlanDecision = Annotated[
    ApproveItems | DismissItem | UncoveredStatement | DismissStale,
    Field(discriminator="action"),
]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_plan_decision: TypeAdapter[PlanDecision] = TypeAdapter(PlanDecision)


class PlanDecided(BaseModel):
    #: Per approved item: the run it started, or why it could not start.
    approved: list[ApprovedItem] | None = None
    done: bool = True


@tool(role="writer", real_role=True)
def decide_documentation_plan(request: PlanDecision) -> dict[str, JsonValue]:
    """Decide on a writing profile's documentation plan as a person does in
    Documents → Plan, recorded as the caller's. Real writers and admins
    only.

    `approve` approves plan items (`item_ids`), each starting its run;
    `dismiss_item` dismisses one; `dismiss_uncovered` and
    `restore_uncovered` take a statement (`guideline_set`, `statement_id`)
    out of or back into what the profile's documents should cover;
    `dismiss_stale` says an out-of-date document (`guideline_set`,
    `document_id`, `revision`) needs no update. Read the plan with
    `get_documentation_plan` first; retry an item with
    `retry_documentation`."""
    request = _plan_decision.validate_python(request)
    return _decide(request).model_dump(mode="json", exclude_none=True)


def _decide(request: PlanDecision) -> PlanDecided:
    decided_by = _caller().id
    if isinstance(request, ApproveItems):
        return PlanDecided(approved=approve_items(request.item_ids, decided_by))
    if isinstance(request, DismissItem):
        documentation_planning.dismiss_item(request.item_id, decided_by=decided_by)
    elif isinstance(request, DismissStale):
        documentation_planning.dismiss_stale(
            request.guideline_set,
            request.document_id,
            request.revision,
            decided_by=decided_by,
        )
    elif request.action == "dismiss_uncovered":
        documentation_planning.dismiss_statement(
            request.guideline_set, request.statement_id, decided_by=decided_by
        )
    else:
        documentation_planning.restore_statement(
            request.guideline_set, request.statement_id
        )
    return PlanDecided()
