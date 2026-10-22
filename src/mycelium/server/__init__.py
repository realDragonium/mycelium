"""MCP server exposing the Mycelium substrate over stdio.

Tools are registered with the local `@tool` decorator (not the bare
`mcp.tool()`) so they show up in the HTTP transport in `mycelium/http.py`
and in the in-process loops. Only the names in `MCP_TOOLS` are also
advertised over MCP: every MCP client pays for each schema it is sent, so
that surface is a deliberate, documented subset (`docs/MCP_TOOLS.md`).
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import os
import re
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from pydantic import JsonValue

from .. import databases, link_authoring, store, timestamps, vector
from ..app_context import AppContext
from ..layout_baker import LayoutBaker
from . import runtime
from .admission import limiter_for, model_loop_slot
from .authoring import (
    delete_statement,
    merge_statements,
    patch_statement,
    replace_text,
    upsert_statement,
    upsert_statements,
)
from .documentation import (
    deliver_document,
    get_document_revision,
    get_documentation_run,
    get_generated_document,
    list_document_revisions,
    list_documentation_destinations,
    list_documentation_models,
    list_documentation_runs,
    list_generated_documents,
    request_documentation,
    revise_document,
)
from .draft_review import (
    DraftCorrectionReceipt,
    DraftOperationFinding,
    DraftReviewInspection,
    DraftReviewRecord,
    KnowledgePrecondition,
    _draft_operation_findings,
    _review_knowledge_preconditions,
    append_draft_correction,
    inspect_draft_review,
    record_draft_review,
)
from .drafts import (
    _identified_principal,
    attach_draft_source,
    discard_draft_op,
    find_my_draft_by_source,
    get_draft,
    get_draft_review_run,
    list_drafts,
    list_my_drafts,
    request_draft_review,
    revise_draft_operation,
    set_draft_review_evidence,
    strike_draft_operation,
    submit_draft,
)
from .entities import (
    add_entity_links,
    delete_entity,
    get_entity,
    list_entities,
    merge_entities,
    remove_entity_links,
    search_entities,
    upsert_entity,
)
from .gaps import report_knowledge_gap
from .indexes import (
    _clear_dirty_marker,
    _dirty_marker_path,
    _fsync_file,
    _persisted_index_write,
    _rebuild_vector_index,
    _restore_index_snapshots,
    _write_dirty_marker,
)
from .links import add_links, remove_links
from .lookups import get_statements, grep_statements, list_statements, retrieve_context
from .model_loops import (
    ask,
    get_research_run,
    ingest,
    list_research_runs,
    list_research_sources,
    start_research,
)
from .names import (
    delete_name,
    find_entity_duplicates,
    get_mention_candidates,
    move_name,
    rename_name,
    upsert_name,
)
from .prompt_texts import (
    _seed_prompt_texts,
    get_documentation_profile,
    get_prompt_text,
    list_documentation_profiles,
    list_prompt_text_versions,
    list_prompt_texts,
    restore_prompt_text,
    retire_documentation_profile,
    retire_prompt_text,
    save_documentation_profile,
    save_prompt_text,
)
from .registry import _ORIG_SIGNATURES, MCP_TOOLS, TOOLS, mcp, publish, tool
from .runtime import (
    _auth_db,
    _db,
    _drafts_db,
    _idx,
    _idx_path,
    _name_idx,
    _name_idx_path,
    _prompts_db,
)
from .search import (
    NEAR_DUPLICATE_THRESHOLD,
    SNIPPET_CHARS,
    discover_facts,
    find_duplicates,
    find_statement_connections,
    search_statements,
    survey_statements,
)
from .specs import (
    BatchStatementSpec,
    EdgeSpec,
    EntityEdgeSpec,
    IncomingLinkSpec,
    LinkSpec,
    ResultLimit,
)
from .vocabulary import (
    ALIAS_PROVENANCE,
    delete_entity_link_type,
    delete_link_type,
    delete_link_type_alias,
    delete_statement_kind,
    list_entity_link_types,
    list_link_type_aliases,
    list_link_types,
    list_statement_kinds,
    upsert_entity_link_type,
    upsert_link_type,
    upsert_link_type_alias,
    upsert_statement_kind,
)

#: The public names, tools first: their order here is the order `publish` gives
#: `TOOLS`, and so the order of every surface built from it.
__all__ = [
    "get_mention_candidates",
    "search_statements",
    "find_statement_connections",
    "survey_statements",
    "ask",
    "ingest",
    "start_research",
    "list_research_runs",
    "get_research_run",
    "request_documentation",
    "revise_document",
    "list_document_revisions",
    "get_document_revision",
    "list_documentation_models",
    "list_documentation_runs",
    "get_documentation_run",
    "list_generated_documents",
    "get_generated_document",
    "deliver_document",
    "list_documentation_destinations",
    "list_research_sources",
    "upsert_entity",
    "upsert_statement",
    "upsert_statements",
    "replace_text",
    "patch_statement",
    "upsert_name",
    "merge_entities",
    "move_name",
    "rename_name",
    "delete_name",
    "delete_entity",
    "merge_statements",
    "delete_statement",
    "add_links",
    "remove_links",
    "get_statements",
    "retrieve_context",
    "get_entity",
    "list_entities",
    "search_entities",
    "list_statements",
    "find_duplicates",
    "find_entity_duplicates",
    "discover_facts",
    "list_link_types",
    "add_entity_links",
    "remove_entity_links",
    "list_statement_kinds",
    "list_entity_link_types",
    "upsert_statement_kind",
    "delete_statement_kind",
    "upsert_link_type",
    "delete_link_type",
    "upsert_link_type_alias",
    "delete_link_type_alias",
    "list_link_type_aliases",
    "upsert_entity_link_type",
    "delete_entity_link_type",
    "grep_statements",
    "report_knowledge_gap",
    "save_prompt_text",
    "get_prompt_text",
    "list_prompt_texts",
    "list_prompt_text_versions",
    "retire_prompt_text",
    "list_documentation_profiles",
    "get_documentation_profile",
    "save_documentation_profile",
    "retire_documentation_profile",
    "restore_prompt_text",
    "submit_draft",
    "request_draft_review",
    "get_draft_review_run",
    "set_draft_review_evidence",
    "list_my_drafts",
    "list_drafts",
    "get_draft",
    "attach_draft_source",
    "find_my_draft_by_source",
    "revise_draft_operation",
    "strike_draft_operation",
    "discard_draft_op",
    "inspect_draft_review",
    "append_draft_correction",
    "record_draft_review",
    "apply_reviewed_draft",
    "MCP_TOOLS",
    "TOOLS",
    "limiter_for",
    "mcp",
    "model_loop_slot",
    "tool",
    "BatchStatementSpec",
    "EdgeSpec",
    "EntityEdgeSpec",
    "IncomingLinkSpec",
    "LinkSpec",
    "ResultLimit",
    "NEAR_DUPLICATE_THRESHOLD",
    "SNIPPET_CHARS",
    "ALIAS_PROVENANCE",
    "KnowledgePrecondition",
    "DraftOperationFinding",
    "DraftReviewRecord",
    "DraftReviewInspection",
    "DraftCorrectionReceipt",
]

logger = logging.getLogger(__name__)


def init(data_dir: Path) -> None:
    """Open the substrate + auth DBs and load (or create) the two
    vector indexes (statements, entity names).

    Auth lives in its own SQLite file (`mycelium-auth.db`) so the
    substrate file can be replaced without disturbing identity or
    tokens — drop `mycelium.db` and restart, every existing user
    session and bearer token keeps working.
    """
    # Invalidate before reconfiguring: if init is re-entered and fails partway
    # (store providers already repointed at the new data dir), leave the
    # process cleanly uninitialized rather than serving the old context's
    # indexes against the new substrate.
    runtime._ctx = None

    from .. import auth_store, docs_store, drafts_store, prompt_store, research_store

    data_dir.mkdir(parents=True, exist_ok=True)
    # Before anything below recreates a missing database empty.
    partial_restore = databases.check_restore(data_dir)
    prompt_store.configure(data_dir / "mycelium-prompts.db")
    prompts = _prompts_db()
    existing_settings_instance = (data_dir / "mycelium.db").exists() or prompts.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name IN ('prompt_texts', 'model_settings', 'draft_review_settings')"
    ).fetchone() is not None
    # Persist fresh-instance provenance before other databases can make a
    # retry after interrupted startup look like a legacy upgrade.
    prompt_store.prepare_settings(
        prompts, import_environment=existing_settings_instance
    )
    prompt_store.migrate(prompts)
    prompt_store.initialize_settings(
        prompts, import_environment=existing_settings_instance
    )

    store.configure_substrate(
        data_dir / "mycelium.db",
        history_path=data_dir / "mycelium-history.db",
    )
    baker = LayoutBaker(data_dir / "mycelium.db")
    store.migrate(_db())
    baker.ensure_initial()

    # Point each provider at its file and run the one-time migration on this
    # thread's connection; every other thread reopens lazily against the same
    # file (see the provider in each store module).
    auth_store.configure(data_dir / "mycelium-auth.db")
    auth_store.migrate(_auth_db())

    drafts_store.configure(data_dir / "mycelium-drafts.db")
    drafts_store.migrate(_drafts_db())
    from .. import draft_review_store

    draft_review_store.mark_orphaned(
        _drafts_db(),
        lambda application_id: (
            _substrate_application_result(application_id) is not None
        ),
    )
    research_store.migrate(_drafts_db())
    docs_store.migrate(_drafts_db())
    from ..docgen import destinations

    destinations.bind_legacy_deliveries(_drafts_db())

    _seed_prompt_texts()

    orphaned = research_store.mark_orphaned(_drafts_db())
    if orphaned:
        logger.warning(
            "marked %d research run(s) failed: orphaned by restart", orphaned
        )
    orphaned_docs = docs_store.mark_orphaned(_drafts_db())
    if orphaned_docs:
        logger.warning(
            "marked %d documentation run(s) failed: orphaned by restart",
            orphaned_docs,
        )

    # The .vec files are re-derivable from the substrate, so a backup may omit
    # them while keeping the *_vector_ids mappings in the DB. When a .vec is
    # missing (a fresh checkout, or a restore of such a backup) or marked dirty
    # after an interrupted write, rebuild the index by re-embedding, or search
    # could silently use vectors that diverge from the populated substrate.
    index_path = data_dir / "mycelium.vec"
    index_dirty = _dirty_marker_path(index_path).exists()
    if index_path.exists() and not index_dirty:
        index = vector.Index.load(index_path)
    else:
        if index_dirty:
            logger.warning(
                "rebuilding statement vector index: dirty marker indicates a "
                "crash before the index was persisted"
            )
        _write_dirty_marker(index_path)
        index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                index,
                store.all_statements_with_text(_db()),
                store.get_vector_id,
                store.next_vector_id,
                store.set_vector_id,
                label="statement",
            )
        index.save(index_path)
        _fsync_file(index_path)
        _clear_dirty_marker(index_path)

    name_index_path = data_dir / "mycelium-names.vec"
    name_index_dirty = _dirty_marker_path(name_index_path).exists()
    if name_index_path.exists() and not name_index_dirty:
        name_index = vector.Index.load(name_index_path)
        # A migration can drop name rows and their vector mappings while
        # the persisted index keeps the vectors (v6's case-variant merge
        # does). Stranded vectors resolve to nothing but still occupy
        # top-k slots in every name search — prune them on load.
        stranded = [
            vid
            for vid in name_index.ids()
            if store.get_name_id_by_vector_id(_db(), vid) is None
        ]
        if stranded:
            logger.info("pruning %d stranded name vector(s)", len(stranded))
            _write_dirty_marker(name_index_path)
            for vid in stranded:
                name_index.delete(vid)
            name_index.save(name_index_path)
            _fsync_file(name_index_path)
            _clear_dirty_marker(name_index_path)
    else:
        if name_index_dirty:
            logger.warning(
                "rebuilding name vector index: dirty marker indicates a crash "
                "before the index was persisted"
            )
        _write_dirty_marker(name_index_path)
        name_index = vector.Index.empty()
        with store.transaction(_db()):
            _rebuild_vector_index(
                name_index,
                store.list_all_names(_db()),
                store.get_name_vector_id,
                store.next_name_vector_id,
                store.set_name_vector_id,
                label="name",
            )
        name_index.save(name_index_path)
        _fsync_file(name_index_path)
        _clear_dirty_marker(name_index_path)

    runtime._ctx = AppContext(
        data_dir=data_dir,
        index=index,
        index_path=index_path,
        name_index=name_index,
        name_index_path=name_index_path,
        layout_baker=baker,
        partial_restore=partial_restore,
    )

    # Start the background mention worker on its own thread and connection
    # (transport-agnostic: both stdio and HTTP funnel through init). The flag is
    # the test suite's "background worker off" switch, so tests can drain the
    # queue synchronously without thread races.
    if os.environ.get("MYCELIUM_DISABLE_MENTION_WORKER") != "1":
        from .. import mention_worker  # local import: workers are optional

        mention_worker.start(data_dir)
    if os.environ.get("MYCELIUM_DISABLE_REVIEW_SWEEP") != "1":
        from .. import draft_review_runs

        draft_review_runs.start_sweeper()


class ReviewedApplicationReceipt(TypedDict):
    application_id: str
    applied: int
    skipped: int
    results: list[dict[str, JsonValue]]
    recovered: NotRequired[bool]


def _rejections(result: JsonValue) -> list[JsonValue]:
    if not isinstance(result, dict):
        return []
    if result.get("rejected") is True:
        return [result.get("violations")]
    items = result.get("results")
    return [
        {"index": index, "violations": item.get("violations")}
        for index, item in enumerate(items if isinstance(items, list) else [])
        if isinstance(item, dict) and item.get("rejected") is True
    ]


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
    `@<int>:<int>` (never prose, and never produced by `connect.draft`) would
    be substituted too.
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
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Resolve and replay one draft operation with contextual errors."""
    from .. import drafts_store

    kind = op["kind"]
    seq = op["seq"]
    if kind in drafts_store.NON_REPLAYING_OP_KINDS:
        return {"seq": seq, "kind": kind, "skipped": kind}
    wrapper = tools_by_name.get(kind)
    if wrapper is None:
        # The tool was removed since this op was queued — notably
        # `add_mentions` / `remove_mentions`, now that mentions are derived.
        # Such an op is obsolete; skip it rather than fail the whole draft.
        return {"seq": seq, "kind": kind, "skipped": "obsolete_tool"}

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
    rejected = isinstance(result, dict) and result.get("rejected") is True
    items = result.get("results") if isinstance(result, dict) else None
    if isinstance(items, list):
        rejected = rejected or any(
            isinstance(item, dict) and item.get("rejected") is True for item in items
        )
    if strict and rejected:
        raise RuntimeError(
            f"op seq={seq} ({kind}) was rejected during replay: "
            + _json.dumps(_rejections(result), default=str)
        )
    results_by_seq[seq] = result
    return {"seq": seq, "kind": kind, "result": result}


def apply_draft(
    draft_id: str,
    *,
    application_id: str | None = None,
    review_id: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Replay an `open` or `submitted` draft's ops against the substrate.

    Caller is responsible for having already verified the principal is
    a curator and the draft is in a state that allows approval. Iterates
    in seq order; each op invokes its matching MCP tool wrapper with the
    curator's principal already in the contextvar (so the role gate
    passes naturally). All-or-nothing: a single op raising halts replay
    and surfaces the error. The caller records approval after a successful replay.
    A non-replaying op kind such as `flag` is skipped with its own marker.

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
    tools_by_name = {w.__name__: w for w in TOOLS}
    results: list[dict[str, Any]] = []
    results_by_seq: dict[int, Any] = {}

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
                for op in ops:
                    results.append(
                        _replay_draft_op(
                            op, tools_by_name, results_by_seq, strict=strict
                        )
                    )
                if application_id is not None:
                    replay_result = {
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
) -> dict[str, JsonValue] | None:
    row = (
        _db()
        .execute(
            "SELECT result_json FROM reviewed_draft_applications WHERE application_id = ?",
            (application_id,),
        )
        .fetchone()
    )
    return None if row is None else _json.loads(row["result_json"])


@tool(role="writer", real_role=True)
def apply_reviewed_draft(draft_id: str, review_id: str) -> ReviewedApplicationReceipt:
    """Apply an accepted exact-version review with durable replay recovery."""
    from .. import drafts_store

    principal = _identified_principal()
    conn = _drafts_db()
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
                stored = _json.loads(existing["result_json"])
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

        if result is None:
            try:
                result = apply_draft(
                    draft_id,
                    application_id=application_id,
                    review_id=review_id,
                    strict=True,
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
                    by=principal.id,
                    application_id=application_id,
                )
        except BaseException as exc:
            with store.transaction(conn):
                drafts_store.note_application_failure(
                    conn, application_id, f"draft finalization failed: {exc}"
                )
            logger.warning(
                "reviewed draft application %s for %s awaits recovery",
                application_id,
                draft_id,
            )
            raise
    return {"application_id": application_id, **result}


publish(__all__)


def run() -> None:
    mcp.run(transport="stdio")
