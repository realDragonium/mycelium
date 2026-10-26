"""The draft lifecycle tools: submitting, listing and correcting drafts.

A draft is a queue of substrate operations awaiting review; the `@tool` wrapper
fills it (see `draft_queue`). These tools act on the queue itself — submit it
for review, inspect it, attach its source and evidence, revise or strike an
operation — and never touch the substrate. Applying a reviewed draft lives in
`draft_application`.
"""

from __future__ import annotations

import sqlite3
from typing import Any, TypedDict

from pydantic import JsonValue, TypeAdapter

from .. import auth as _auth
from .. import drafts_store, media, store
from ..auth import Principal as AuthPrincipal
from ..draft_review_store import Application as AssessmentApplication
from ..draft_review_store import Label as AssessmentLabel
from .draft_queue import _require_draft_owner
from .registry import tool
from .runtime import _drafts_db

_evidence_list = TypeAdapter(list[drafts_store.Evidence])

# --- draft management tools -----------------------------------------------
# These manipulate the draft queue itself rather than the substrate.
# Their names don't start with substrate mutation prefixes, so the @tool
# wrapper doesn't auto-attach a `draft_id` parameter — they accept one
# as a normal positional/keyword arg referring to the draft they operate
# on. `submit_draft` requires writer rank, which a drafter satisfies via
# the role-equivalence in auth.principal_satisfies.


@tool
def submit_draft(draft_id: str | None = None) -> dict[str, Any]:
    """Submit a draft for curator review.

    `draft_id` is optional — when omitted, submits the caller's
    currently-open auto-draft (the one their MCP session has been
    accumulating ops into). After submission the draft can no longer
    accept new ops via tool calls; the curator either approves it
    (replays the ops against the substrate) or rejects it.

    Returns the submitted draft's id and final op count.
    """
    from .. import auth as _auth
    from .. import drafts_store

    principal = _auth.current_principal.get()

    if draft_id is None:
        if principal is None:
            raise ValueError("no draft_id given and no caller identity")
        session_id = _auth.current_session_id.get() or f"actor:{principal.id}"
        row = drafts_store.find_open_session_draft(
            _drafts_db(), session_id, principal.id
        )
        if row is None:
            raise ValueError("no open draft to submit for this caller")
        draft_id = row["id"]
    else:
        row = drafts_store.get_draft(_drafts_db(), draft_id)
        if row is None:
            raise ValueError(f"draft '{draft_id}' not found")
        if drafts_store.status_for(row) != "open":
            raise ValueError(
                f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
                f"only open drafts can be submitted"
            )
        _require_draft_owner(principal, row)

    _submit_for_review(draft_id)
    ops = drafts_store.list_ops(_drafts_db(), draft_id)
    return {"draft_id": draft_id, "op_count": len(ops)}


def _submit_for_review(draft_id: str) -> None:
    from .. import draft_review_runs, drafts_store

    with store.transaction(_drafts_db()):
        drafts_store.set_submitted(_drafts_db(), draft_id)
    draft_review_runs.on_submitted(draft_id)


def _auto_submit(draft_id: str) -> bool:
    """Submit a model-produced draft while internal review is on, so it reaches
    the reviewer instead of waiting for someone to submit it. With review off
    the draft stays open for a person to curate."""
    from .. import draft_review_runs, draft_review_settings, drafts_store

    try:
        if draft_review_runs.mode() == "off":
            return False
    except draft_review_settings.Unavailable:
        return False
    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None or drafts_store.status_for(row) != "open":
        return False
    if not drafts_store.list_ops(_drafts_db(), draft_id):
        return False
    _submit_for_review(draft_id)
    return True


@tool(role="writer", real_role=True)
def request_draft_review(draft_id: str, rerun: bool = False) -> dict[str, JsonValue]:
    """Start internal GPT review, or return its latest run; rerun starts a new attempt.

    Requires an identified curator. Mode off refuses requests; configuration and
    execution failures remain visible on the draft's review_assessment.
    """
    from .. import draft_review_runs

    _identified_principal()
    return draft_review_runs.start(draft_id, rerun=rerun).model_dump(mode="json")


@tool
def get_draft_review_run(run_id: str) -> dict[str, JsonValue]:
    """Inspect an internal review attempt, including failure and staleness."""
    from .. import draft_review_store

    return draft_review_store.get(_drafts_db(), run_id).model_dump(mode="json")


@tool(role="drafter")
def set_draft_review_evidence(
    draft_id: str, evidence: str, expected_revision: int
) -> dict[str, JsonValue]:
    """Replace evidence supplied by the draft creator and invalidate old assessments.

    Supply source excerpts, change descriptions, or concrete supporting facts,
    up to 30000 characters. URLs alone do not provide their contents.
    """
    from .. import drafts_store

    principal = _identified_principal()
    if len(evidence) > 30000:
        raise ValueError("review evidence exceeds 30000 characters")
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        if row["created_by"] != principal.id:
            from .. import auth as _auth

            raise _auth.RoleRequired(
                "only the draft creator can supply review evidence"
            )
        drafts_store._check_revision(row, expected_revision)
        if row["review_evidence"] != evidence:
            conn.execute(
                "UPDATE drafts SET review_evidence = ?, revision = revision + 1 "
                "WHERE id = ?",
                (evidence, draft_id),
            )
    draft: dict[str, JsonValue] = get_draft(draft_id)
    return draft


@tool(role="drafter")
def set_operation_evidence(
    draft_id: str,
    operation_ref: str,
    evidence: list[drafts_store.Evidence],
    expected_revision: int,
) -> DraftMutationReceipt:
    """Replace the evidence behind one operation of your draft, which the
    reviewer weighs; an empty list removes it.

    Use it for what you checked in the product itself: each item has a
    `kind` (code, ui, doc, media or other), where it is (`path` relative to
    the repository root with optional `lines` such as "40-52" and `commit`,
    or a `url`), a short `excerpt` (at most 1500 characters) and a one-line
    `claim` saying what it shows. Media evidence names a `media_id` from
    `create_media_upload` instead of a place; applying the draft attaches
    that screenshot or recording to what the operation writes. At most five
    items per operation. A link
    backed by a concrete code excerpt can be accepted on that basis; a link
    without evidence is judged more strictly. `operation_ref` is in the
    receipt of the queued write and in `get_draft`. Only the draft's creator
    may set it, and a change makes an earlier review stale.
    """
    principal = _identified_principal()
    # In-process callers pass plain dicts; MCP and HTTP have validated already.
    items = media.describe_evidence(_evidence_list.validate_python(evidence))
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        if row["created_by"] != principal.id:
            raise _auth.RoleRequired(
                "only the draft creator can supply operation evidence"
            )
        revision = drafts_store.set_op_evidence(
            conn,
            draft_id,
            operation_ref,
            items,
            expected_revision=expected_revision,
        )
    return {"draft_id": draft_id, "operation_ref": operation_ref, "revision": revision}


@tool
def list_my_drafts() -> list[dict[str, Any]]:
    """List drafts created by the calling principal, newest first.

    Useful for an agent to inspect what it queued in earlier sessions
    or check on the review state of submitted work.
    """
    from .. import auth as _auth
    from .. import drafts_store

    principal = _auth.current_principal.get()
    creator = principal.id if principal is not None else None
    rows = drafts_store.list_drafts_by_creator(_drafts_db(), creator)
    return [drafts_store.serialize_draft(r) for r in rows]


_DRAFT_STATUS_VALUES = (
    "all",
    "open",
    "submitted",
    "approved",
    "rejected",
    "withdrawn",
)


@tool(role="writer", real_role=True)
def list_drafts(
    status: str = "all",
    created_by: str | None = None,
    label: AssessmentLabel | None = None,
    application: AssessmentApplication | None = None,
) -> list[dict[str, Any]]:
    """List *every* draft across all creators, newest first (curators only).

    Unlike `list_my_drafts` (scoped to the caller), this returns the whole
    review queue so a curator can discover work awaiting review and then
    `get_draft(<id>)` to inspect the queued ops and review assessment. Each
    entry carries an `op_count` and a summary of the latest automatic review
    (`run_id`, `status`, `label`, `application`, `stale`), not its evidence.
    Filter with `status`: all / open / submitted / approved / rejected /
    withdrawn; `created_by`: one creator's principal id; `label`: the
    review's label (good / changes_suggested / reject / needs_context); and
    `application`: what the review did (unapplied / applied / rejected /
    needs_human / held). Drafts the automatic reviewer rejected are
    `status="rejected", application="rejected"`; corrections held for a
    curator are `status="submitted", application="held"`.

    Requires a real writer or admin role — same bar as approving or
    rejecting a draft. Drafters (whose writes get redirected into their own
    draft) do not pass, so they can't enumerate other people's drafts.
    """
    from .. import auth as _auth
    from .. import drafts_store

    # The role gate is the decorator's (`real_role=True`, so a drafter does
    # not clear it). What remains here is the identity requirement: the
    # review queue spans every creator, so an anonymous caller has no
    # standing to read it even where the wrapper's gate stays out of the way.
    principal = _auth.current_principal.get()
    if principal is None:
        raise _auth.RoleRequired(
            "tool 'list_drafts' requires an identified caller; "
            "use list_my_drafts to see your own drafts"
        )
    if status not in _DRAFT_STATUS_VALUES:
        raise ValueError("status must be one of: " + ", ".join(_DRAFT_STATUS_VALUES))

    conn = _drafts_db()
    counts = drafts_store.count_ops_by_draft(conn)
    out = []
    for d in drafts_store.list_draft_summaries(
        conn, status=status, label=label, application=application
    ):
        if created_by is not None and d["created_by"] != created_by:
            continue
        d["op_count"] = counts.get(d["id"], 0)
        out.append(d)
    return out


@tool
def get_draft(draft_id: str) -> dict[str, Any]:
    """Return a draft and its queued ops, in seq order.

    Anyone with read access can fetch any draft — drafts are intended
    for curator review so visibility is broad. The shape mirrors the
    HTTP `/api/drafts/<id>` response, plus `missing`: always present,
    empty when the draft resolved, and `[draft_id]` when no draft
    carries that id (an id that was never minted, or a draft already
    applied and swept). `decisions` lists, in order, who approved,
    rejected, reopened or asked about the draft, with their reason and
    evidence.
    """
    from .. import drafts_store

    conn = _drafts_db()
    row, ops = drafts_store.get_draft_snapshot(conn, draft_id)
    if row is None:
        return {"id": draft_id, "missing": [draft_id]}
    decisions = drafts_store.list_decisions(conn, draft_id)
    return {
        **drafts_store.serialize_draft(row, ops=ops, decisions=decisions),
        "missing": [],
    }


class DraftSourceInput(TypedDict):
    repository: str
    pull_request: int
    merged_commit: str
    workflow_run_id: int
    workflow_run_attempt: int


class DraftMutationReceipt(TypedDict):
    draft_id: str
    operation_ref: str
    revision: int


def _identified_principal() -> AuthPrincipal:
    from .. import auth as _auth

    principal = _auth.current_principal.get()
    if principal is None:
        raise _auth.RoleRequired("draft source operations require an identified caller")
    return principal


def _require_mutable_draft(draft_id: str) -> sqlite3.Row:
    from .. import drafts_store

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        raise ValueError(f"cannot modify operations on a {status} draft")
    if drafts_store.active_application(_drafts_db(), draft_id) is not None:
        raise drafts_store.ActiveApplicationError(
            f"draft '{draft_id}' has an active reviewed application"
        )
    return row


@tool(role="drafter")
def attach_draft_source(
    draft_id: str,
    source: DraftSourceInput,
    expected_revision: int | None = None,
) -> dict[str, JsonValue]:
    """Attach complete PR and workflow evidence to the caller's draft."""
    from .. import drafts_store

    principal = _identified_principal()
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        if row["created_by"] != principal.id:
            from .. import auth as _auth

            raise _auth.RoleRequired(
                "draft source evidence may only be set by its creator"
            )
        try:
            drafts_store.set_source(
                conn, draft_id, source, expected_revision=expected_revision
            )
        except sqlite3.IntegrityError as ex:
            existing = drafts_store.find_draft_by_source(conn, principal.id, source)
            owner = existing["id"] if existing is not None else "another draft"
            detail = f"source evidence already belongs to draft '{owner}'"
            raise ValueError(detail) from ex
    draft: dict[str, JsonValue] = get_draft(draft_id)
    return draft


@tool(role="drafter")
def find_my_draft_by_source(source: DraftSourceInput) -> dict[str, JsonValue]:
    """Locate the caller's draft from its complete PR workflow identity."""
    from .. import drafts_store

    principal = _identified_principal()
    row = drafts_store.find_draft_by_source(_drafts_db(), principal.id, source)
    if row is None:
        return {"draft": None}
    return {"draft": get_draft(row["id"])}


@tool(role="writer", real_role=True)
def revise_draft_operation(
    draft_id: str,
    operation_ref: str,
    payload: dict[str, JsonValue],
    expected_revision: int | None = None,
) -> DraftMutationReceipt:
    """Replace one operation payload using its stable reference."""
    from .. import drafts_store

    conn = _drafts_db()
    with store.transaction(conn):
        _require_mutable_draft(draft_id)
        revision = drafts_store.update_op_payload_by_ref(
            conn,
            draft_id,
            operation_ref,
            payload,
            expected_revision=expected_revision,
        )
    if revision is None:
        raise ValueError(f"operation '{operation_ref}' not found in draft '{draft_id}'")
    return {"draft_id": draft_id, "operation_ref": operation_ref, "revision": revision}


@tool(role="writer", real_role=True)
def strike_draft_operation(
    draft_id: str,
    operation_ref: str,
    expected_revision: int | None = None,
) -> DraftMutationReceipt:
    """Remove one operation using its stable reference."""
    from .. import drafts_store

    conn = _drafts_db()
    with store.transaction(conn):
        _require_mutable_draft(draft_id)
        revision = drafts_store.remove_op_by_ref(
            conn,
            draft_id,
            operation_ref,
            expected_revision=expected_revision,
        )
    if revision is None:
        raise ValueError(f"operation '{operation_ref}' not found in draft '{draft_id}'")
    return {"draft_id": draft_id, "operation_ref": operation_ref, "revision": revision}


@tool
def discard_draft_op(
    draft_id: str, seq: int, expected_revision: int | None = None
) -> dict[str, Any]:
    """Remove a queued op from an open draft by its seq number.

    Lets a drafter self-correct a mistake without abandoning the whole
    draft. The op's seq stays burned — remaining ops keep their original
    sequence numbers (no renumbering) so any external references to a
    `(draft_id, seq)` pair stay stable.
    """
    from .. import drafts_store

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    if drafts_store.status_for(row) != "open":
        raise ValueError(
            f"draft '{draft_id}' is {drafts_store.status_for(row)}; "
            f"can't modify ops on a non-open draft"
        )
    _require_draft_owner(_auth.current_principal.get(), row)
    with store.transaction(_drafts_db()):
        revision = drafts_store.remove_op(
            _drafts_db(), draft_id, seq, expected_revision=expected_revision
        )
    if revision is None:
        raise ValueError(f"no op with seq {seq} in draft '{draft_id}'")
    return {
        "draft_id": draft_id,
        "seq": seq,
        "removed": True,
        "revision": revision,
    }
