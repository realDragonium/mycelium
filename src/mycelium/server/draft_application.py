"""Applying a draft: replaying its operations against the live substrate.

Replay is all-or-nothing. One transaction owns every replayed write, and both
vector indexes are snapshotted first, so a failing operation rolls back the
substrate and restores the indexes. An approval also records a
receipt inside that same transaction. If the process dies after the substrate
commits but before the draft is marked approved, the receipt lets the next
attempt recover the result instead of replaying it twice.
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import re
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from typing import Any, NotRequired, TypedDict

from pydantic import JsonValue

from .. import auth, embed, link_authoring, store, timestamps
from .draft_review import _draft_operation_findings, _review_knowledge_preconditions
from .drafts import _identified_principal
from .indexes import _persisted_index_write, _restore_index_snapshots
from .names import _embed_name_ahead
from .registry import _ORIG_SIGNATURES, TOOLS, tool
from .runtime import (
    _db,
    _drafts_db,
    _idx,
    _idx_path,
    _name_idx,
    _name_idx_path,
    _prompts_db,
)

logger = logging.getLogger(__name__)
_MANUAL_REVIEW_PREFIX = "rev_manual_"


class DraftReplay(TypedDict):
    """What replaying a draft did: one entry per operation, applied or skipped.

    Stored as the application's receipt, which is where `recovered`
    comes from: an application recovered from an earlier attempt says so.
    """

    applied: int
    skipped: int
    results: list[dict[str, JsonValue]]
    recovered: NotRequired[bool]


class ReviewedApplicationReceipt(TypedDict):
    application_id: str
    applied: int
    skipped: int
    results: list[dict[str, JsonValue]]
    recovered: NotRequired[bool]


class RejectedStatement(TypedDict):
    """One statement a replayed operation refused, with the reasons why."""

    seq: int
    kind: str
    text: str | None
    reasons: list[str]


class DraftOpsRejectedError(RuntimeError):
    """Replay refused part of the draft, so none of it was applied."""

    def __init__(self, rejections: list[RejectedStatement]) -> None:
        self.rejections = rejections
        super().__init__(
            "; ".join(
                f"op seq={r['seq']} ({r['kind']}) was rejected during replay: "
                + ", ".join(r["reasons"])
                for r in rejections
            )
        )


def _rejection_reasons(item: dict[str, Any]) -> list[str]:
    violations = item.get("violations")
    if isinstance(violations, list) and violations:
        return [str(v.get("rule", v)) for v in violations if isinstance(v, dict)]
    errors = item.get("errors")
    if isinstance(errors, list) and errors:
        return [str(error) for error in errors]
    if item.get("reason") == "depends_on_rejected":
        return [
            "depends on rejected statement(s) at position "
            + ", ".join(str(i) for i in item.get("depends_on", []))
            + " of the same operation"
        ]
    return [str(item.get("reason", "rejected"))]


def _rejected_statements(
    seq: int, kind: str, payload: dict[str, Any], result: Any
) -> list[RejectedStatement]:
    if not isinstance(result, dict):
        return []
    if result.get("rejected") is True:
        text = payload.get("text")
        return [
            {
                "seq": seq,
                "kind": kind,
                "text": text if isinstance(text, str) else None,
                "reasons": _rejection_reasons(result),
            }
        ]
    items = result.get("results")
    specs = payload.get("statements")
    rejected: list[RejectedStatement] = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        if not (isinstance(item, dict) and item.get("rejected") is True):
            continue
        spec = specs[index] if isinstance(specs, list) and index < len(specs) else None
        text = spec.get("text") if isinstance(spec, dict) else None
        rejected.append(
            {
                "seq": seq,
                "kind": kind,
                "text": text if isinstance(text, str) else None,
                "reasons": _rejection_reasons(item),
            }
        )
    return rejected


_DRAFT_RESULT_REF = re.compile(r"^@(\d+):(\d+)$")


def _resolve_draft_refs(payload: Any, results_by_seq: dict[int, Any]) -> Any:
    """Resolve cross-operation statement references in a draft payload.

    `"@<seq>:<index>"` addresses the statement the op at `seq` created at that
    position. A bare `"@N"` is left alone: it belongs to `upsert_statements`'
    own sibling grammar and is resolved by that tool, not here.

    The walk is payload-wide rather than restricted to known id fields: an
    allowlist would have to track every tool's parameter names and would fail
    open — silently skipping resolution — the moment one grows a new endpoint
    argument. The cost is that a free-form value equal in its entirety to
    `@<int>:<int>` (never prose) would be substituted too.
    """
    if isinstance(payload, dict):
        return {
            key: _resolve_draft_refs(value, results_by_seq)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_resolve_draft_refs(value, results_by_seq) for value in payload]
    if not isinstance(payload, str):
        return payload

    match = _DRAFT_RESULT_REF.fullmatch(payload)
    if match is None:
        return payload
    seq, index = (int(value) for value in match.groups())
    result = results_by_seq.get(seq)
    items = result.get("results") if isinstance(result, dict) else None
    item = items[index] if isinstance(items, list) and index < len(items) else None
    if not isinstance(item, dict) or "statement_id" not in item:
        raise ValueError(f"@{seq}:{index} which did not produce a statement")
    return item["statement_id"]


def _replay_draft_op(
    op: sqlite3.Row,
    tools_by_name: dict[str, Callable[..., Any]],
    results_by_seq: dict[int, Any],
) -> tuple[dict[str, Any], list[RejectedStatement]]:
    """Resolve and replay one draft operation with contextual errors, and say
    which of its statements the tool refused."""
    from .. import drafts_store

    kind = op["kind"]
    seq = op["seq"]
    if kind in drafts_store.NON_REPLAYING_OP_KINDS:
        return {"seq": seq, "kind": kind, "skipped": kind}, []
    wrapper = tools_by_name.get(kind)
    if wrapper is None:
        # The tool was removed since this op was queued — notably
        # `add_mentions` / `remove_mentions`, now that mentions are derived.
        # Such an op is obsolete; skip it rather than fail the whole draft.
        return {"seq": seq, "kind": kind, "skipped": "obsolete_tool"}, []

    payload = _json.loads(op["payload_json"])
    try:
        payload = _resolve_draft_refs(payload, results_by_seq)
    except ValueError as ex:
        raise RuntimeError(f"op seq={seq} references {ex}") from ex

    if kind == "add_links":
        try:
            link_authoring.reject_entity_statement_additions(payload.get("links"))
        except ValueError as ex:
            raise RuntimeError(
                f"op seq={seq} ({kind}) failed during replay: {ex}"
            ) from ex

    # Drop payload keys the tool no longer accepts (e.g. a stale `mentions` /
    # `strict_mentions` on a queued upsert_statement) so an old draft replays
    # cleanly instead of raising on an unexpected kwarg.
    sig = _ORIG_SIGNATURES.get(kind)
    if sig is not None:
        for key in [key for key in payload if key not in sig.parameters]:
            payload.pop(key)
    try:
        result = wrapper(**payload)
    except Exception as ex:
        raise RuntimeError(f"op seq={seq} ({kind}) failed during replay: {ex}") from ex
    results_by_seq[seq] = result
    return (
        {"seq": seq, "kind": kind, "result": result},
        _rejected_statements(seq, kind, payload, result),
    )


def _replay_draft_ops(ops: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Replay every op in order, raising `DraftOpsRejectedError` if any
    statement was refused."""
    tools_by_name = {w.__name__: w for w in TOOLS}
    results: list[dict[str, Any]] = []
    results_by_seq: dict[int, Any] = {}
    rejections: list[RejectedStatement] = []
    for op in ops:
        try:
            item, refused = _replay_draft_op(op, tools_by_name, results_by_seq)
        except RuntimeError:
            # Usually a reference to a statement refused above; the refusal
            # is the reason worth reporting.
            if rejections:
                break
            raise
        results.append(item)
        rejections.extend(refused)
    if rejections:
        raise DraftOpsRejectedError(rejections)
    return results


def _draft_texts(ops: list[sqlite3.Row]) -> Iterator[tuple[str, str]]:
    """Each statement text and name a draft's replay would embed, tagged
    `statement` or `name`."""
    for op in ops:
        payload = _json.loads(op["payload_json"])
        kind = op["kind"]
        if kind in ("upsert_statement", "patch_statement") and payload.get("text"):
            yield "statement", payload["text"]
        elif kind == "upsert_statements":
            for item in payload.get("statements") or []:
                yield "statement", item["text"]
        elif kind == "upsert_entity":
            yield "name", payload["name"]
        elif kind == "upsert_name":
            yield "name", payload["text"]
        elif kind == "rename_name":
            yield "name", payload["new_text"]


def embed_draft_ahead(draft_id: str) -> None:
    """Embed a draft's texts before its replay takes the write lock: replay
    holds the lock from its first operation to its commit, and every write
    and token check in the process queues behind it, while embedding is the
    slow part. Replay then finds these in `embed`'s cache. Texts a replay
    derives itself, such as `replace_text` results, are still embedded under
    the lock."""
    from .. import drafts_store

    try:
        for kind, text in _draft_texts(drafts_store.list_ops(_drafts_db(), draft_id)):
            if kind == "name":
                _embed_name_ahead(text)
            else:
                embed.embed(text)
    except Exception:  # noqa: BLE001
        # The replay embeds again and reports a failure in the operation's
        # terms; failing here would only report it worse.
        logger.warning("could not embed draft %s ahead of replay", draft_id)


def apply_draft(
    draft_id: str,
    *,
    application_id: str | None = None,
    review_id: str | None = None,
    strict: bool = False,
) -> DraftReplay:
    """Replay an `open` or `submitted` draft's ops against the substrate.

    Caller is responsible for having already verified the principal is
    a curator and the draft is in a state that allows approval. Iterates
    in seq order; each op invokes its matching MCP tool wrapper with the
    curator's principal already in the contextvar (so the role gate
    passes naturally). All-or-nothing: a single op raising halts replay
    and surfaces the error, and any statement a tool refuses (the phrasing
    linter, say) fails the whole replay with `DraftOpsRejectedError` listing
    every refusal. The same transaction resolves the knowledge gaps filed
    about the draft, so they close exactly when its knowledge lands. The
    caller records approval after a successful replay. A non-replaying op
    kind such as `flag` is skipped with its own marker. `strict` also
    refuses a draft with unresolved operation findings.

    Returns `{applied: int, skipped: int, results: [...]}`. On failure,
    raises with the seq/kind that exploded.
    """
    from .. import drafts_store

    if (application_id is None) != (review_id is None):
        raise ValueError("application_id and review_id must be supplied together")

    row = drafts_store.get_draft(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    status = drafts_store.status_for(row)
    if status not in ("open", "submitted"):
        raise ValueError(
            f"draft '{draft_id}' is {status}; only open or submitted "
            f"drafts can be approved"
        )
    active = drafts_store.active_application(_drafts_db(), draft_id)
    if active is not None and active["id"] != application_id:
        raise drafts_store.ActiveApplicationError(
            f"draft '{draft_id}' has an active reviewed application"
        )

    ops = drafts_store.list_ops(_drafts_db(), draft_id)
    from .. import alias_suggestions

    if alias_suggestions.pending(ops):
        raise ValueError(
            "Review pending alias suggestions individually before applying this draft."
        )
    findings = _draft_operation_findings(ops)
    if strict and findings:
        raise ValueError("draft has unresolved operation findings")
    results: list[dict[str, Any]] = []

    snapshot_id = uuid.uuid4().hex
    index_snapshot_path = _idx_path().with_name(
        _idx_path().name + ".pre-apply-" + snapshot_id
    )
    name_index_snapshot_path = _name_idx_path().with_name(
        _name_idx_path().name + ".pre-apply-" + snapshot_id
    )
    snapshots = (
        (_idx(), index_snapshot_path, _idx_path()),
        (_name_idx(), name_index_snapshot_path, _name_idx_path()),
    )

    # All-or-nothing replay: one transaction owns every op's substrate
    # writes. Each replayed tool opens its own `transaction(_db())`, which
    # joins this outer one (reentrant), so a single op raising rolls the
    # whole draft back. Per-attempt paths preserve recovery artifacts across
    # retries; the write lock serializes snapshots and both recovery paths
    # against index mutations in this process. The persisted-write wrapper
    # marks both indexes before the snapshots. A successful replay clears them
    # only after the outer commit; a failed replay leaves them for startup to
    # rebuild even when its best-effort snapshot restore succeeds.
    snapshots_taken = False
    restored = False
    try:
        with _persisted_index_write(statements=True, names=True):
            try:
                _idx().save(index_snapshot_path)
                _name_idx().save(name_index_snapshot_path)
            except BaseException:
                for _, snapshot_path, _ in snapshots:
                    with contextlib.suppress(OSError):
                        snapshot_path.unlink(missing_ok=True)
                raise
            snapshots_taken = True
            try:
                results = _replay_draft_ops(ops)
                approver = auth.current_principal.get()
                store.resolve_draft_gaps(
                    _db(), draft_id, approver.id if approver is not None else None
                )
                if application_id is not None:
                    replay_result: DraftReplay = {
                        "applied": sum("result" in item for item in results),
                        "skipped": sum("skipped" in item for item in results),
                        "results": results,
                    }
                    _db().execute(
                        "INSERT OR IGNORE INTO reviewed_draft_applications "
                        "(application_id, draft_id, review_id, committed_at, result_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            application_id,
                            draft_id,
                            review_id,
                            timestamps.now(),
                            _json.dumps(replay_result),
                        ),
                    )
            except BaseException:
                restored = True
                _restore_index_snapshots(snapshots)
                raise
    except BaseException:
        if snapshots_taken and not restored:
            # A failed commit leaves the connection's transaction open, so a
            # new transaction block could commit the replay it should recover.
            with store.write_lock():
                # Roll back before restoring so no writer can interleave or
                # later commit the failed replay's pending rows.
                with contextlib.suppress(sqlite3.Error):
                    _db().rollback()
                _restore_index_snapshots(snapshots)
        raise

    for _, snapshot_path, _ in snapshots:
        with contextlib.suppress(OSError):
            snapshot_path.unlink(missing_ok=True)
    return {
        "applied": sum("result" in item for item in results),
        "skipped": sum("skipped" in item for item in results),
        "results": results,
    }


def _reviewed_apply_enabled() -> bool:
    from .. import draft_review_settings

    return draft_review_settings.load_controls(_prompts_db()).application_enabled


def _substrate_application_result(
    application_id: str,
) -> DraftReplay | None:
    row = (
        _db()
        .execute(
            "SELECT result_json FROM reviewed_draft_applications WHERE application_id = ?",
            (application_id,),
        )
        .fetchone()
    )
    if row is None:
        return None
    replay: DraftReplay = _json.loads(row["result_json"])
    return replay


def approve_draft(draft_id: str, *, decided_by: str) -> DraftReplay:
    """Record a curator's acceptance and apply it with durable replay recovery.

    The caller enforces the real curator role. Manual acceptance permits open
    drafts and operation findings, independently of automated review settings.
    """
    from .. import drafts_store

    conn = _drafts_db()
    embed_draft_ahead(draft_id)
    with store.write_lock():
        with store.transaction(conn):
            draft = drafts_store.get_draft(conn, draft_id)
            if draft is None:
                raise ValueError(f"draft '{draft_id}' not found")
            status = drafts_store.status_for(draft)
            if status not in ("open", "submitted"):
                raise ValueError(
                    f"draft '{draft_id}' is {status}; only open or submitted "
                    "drafts can be approved"
                )
            active = drafts_store.active_application(conn, draft_id)
            if active is not None:
                review_id = str(active["review_id"])
                if not review_id.startswith(_MANUAL_REVIEW_PREFIX):
                    raise drafts_store.ActiveApplicationError(
                        f"draft '{draft_id}' has an active reviewed application"
                    )
                application_id = str(active["id"])
            else:
                review_id = drafts_store.create_review(
                    conn,
                    draft_id=draft_id,
                    outcome="accepted",
                    rationale="Approved by hand.",
                    draft_revision=int(draft["revision"]),
                    preconditions=[],
                    unresolved_questions=[],
                    reviewed_by=decided_by,
                    review_id=_MANUAL_REVIEW_PREFIX + uuid.uuid4().hex[:12],
                )
                application_id = drafts_store.claim_application(
                    conn,
                    draft_id=draft_id,
                    review_id=review_id,
                    claimed_by=decided_by,
                )
        result = _apply_claimed_draft(
            draft_id,
            application_id,
            review_id,
            decided_by=decided_by,
            strict=False,
        )
    return {
        "applied": result["applied"],
        "skipped": result["skipped"],
        "results": result["results"],
    }


@tool(role="writer", real_role=True)
def apply_reviewed_draft(draft_id: str, review_id: str) -> ReviewedApplicationReceipt:
    """Apply an accepted exact-version review with durable replay recovery."""
    from .. import drafts_store

    principal = _identified_principal()
    conn = _drafts_db()
    embed_draft_ahead(draft_id)
    with store.write_lock():
        if not _reviewed_apply_enabled():
            raise ValueError("reviewed draft application is disabled")
        stale_knowledge = False
        with store.transaction(conn):
            draft = drafts_store.get_draft(conn, draft_id)
            review = drafts_store.get_review(conn, review_id)
            if draft is None or review is None or review["draft_id"] != draft_id:
                raise ValueError("draft or review not found")
            existing = drafts_store.application_for_review(conn, draft_id, review_id)
            if existing is not None and existing["status"] == "committed":
                stored: DraftReplay = _json.loads(existing["result_json"])
                return {"application_id": existing["id"], **stored, "recovered": True}
            if drafts_store.status_for(draft) != "submitted":
                raise ValueError("only submitted drafts can be applied")
            if review["outcome"] not in ("accepted", "refined"):
                raise ValueError("review outcome does not permit application")
            if _json.loads(review["unresolved_json"]):
                raise ValueError("review has unresolved questions")
            if int(draft["revision"]) != int(review["draft_revision"]):
                raise drafts_store.StaleDraftRevisionError(
                    "draft changed after the recorded review"
                )
            application_id = drafts_store.claim_application(
                conn,
                draft_id=draft_id,
                review_id=review_id,
                claimed_by=principal.id,
            )
            result = _substrate_application_result(application_id)
            if result is None:
                current = _review_knowledge_preconditions(
                    drafts_store.list_ops(conn, draft_id),
                    _json.loads(review["preconditions_json"]),
                )
                if current != _json.loads(review["preconditions_json"]):
                    stale_knowledge = True

        if stale_knowledge:
            failure = "affected knowledge changed after the recorded review"
            with store.transaction(conn):
                drafts_store.finish_application(
                    conn, application_id, status="failed", failure=failure
                )
            raise ValueError(failure)

        result = _apply_claimed_draft(
            draft_id,
            application_id,
            review_id,
            decided_by=principal.id,
            strict=True,
        )
    return {"application_id": application_id, **result}


def _apply_claimed_draft(
    draft_id: str,
    application_id: str,
    review_id: str,
    *,
    decided_by: str,
    strict: bool,
) -> DraftReplay:
    """Replay or recover a durable claim while the caller holds the write lock."""
    from .. import drafts_store

    conn = _drafts_db()
    result = _substrate_application_result(application_id)
    if result is None:
        try:
            result = apply_draft(
                draft_id,
                application_id=application_id,
                review_id=review_id,
                strict=strict,
            )
        except BaseException as exc:
            committed = _substrate_application_result(application_id)
            if committed is None:
                with store.transaction(conn):
                    drafts_store.finish_application(
                        conn, application_id, status="failed", failure=str(exc)
                    )
                raise
            with store.transaction(conn):
                drafts_store.note_application_failure(
                    conn,
                    application_id,
                    f"replay returned after substrate commit: {exc}",
                )
            result = {**committed, "recovered": True}
    else:
        result = {**result, "recovered": True}

    try:
        with store.transaction(conn):
            drafts_store.finish_application(
                conn, application_id, status="committed", result=result
            )
            drafts_store.set_decision(
                conn,
                draft_id,
                decision="approved",
                by=decided_by,
                application_id=application_id,
            )
    except BaseException as exc:
        with store.transaction(conn):
            drafts_store.note_application_failure(
                conn, application_id, f"draft finalization failed: {exc}"
            )
        logger.warning(
            "draft application %s for %s awaits recovery",
            application_id,
            draft_id,
        )
        raise
    return result
