"""Statement authoring: creating, editing, merging and deleting statements.

A write that sets text embeds it, runs the shared write checks, derives the
statement's mentions on the spot and reports near-duplicates as a warning that
never blocks the write. Every write runs inside one `_persisted_index_write`,
so the vector index and the substrate commit together or a startup rebuild
reconciles them.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import media, phrasing, store
from .batch_planning import (
    _assemble_batch_results,
    _materialize_batch_edges,
    _plan_batch,
)
from .indexes import _persisted_index_write, _set_statement_vector, _try_embed
from .registry import draftable_tool
from .runtime import _db, _idx
from .search import _near_duplicates
from .specs import BatchStatementSpec, IncomingLinkSpec, LinkSpec
from .write_checks import (
    _collect_flip_errors,
    _phrasing_gate,
    _resolve_when_tree,
    _statement_kind,
)


def _derive_statement_mentions(statement_id: str, text: str) -> None:
    """Synchronously derive and store one statement's mentions from its
    text (auto-links + suspect review rows). Called on the hot path
    whenever a statement's text is created or changed, so its mentions are
    always consistent with its text the moment the write returns."""
    store.derive_mentions(_db(), statement_id, text, store.build_name_index(_db()))


def _validate_statement_refs(
    id: str | None,
    links: list[LinkSpec],
    incoming_links: list[IncomingLinkSpec],
) -> dict[str, sqlite3.Row]:
    """Validate every referenced statement id BEFORE mutating, so a typo can't
    half-apply. Outgoing `links` targets, `incoming_links` sources, and
    every `statement_id` leaf inside any `when` tree are all checked here.
    Returns the fetched rows keyed by id for downstream kind lookups."""
    statement_rows: dict[str, sqlite3.Row] = {}

    def _check_existing(ref: str, position: str) -> str:
        row = store.get_statement(_db(), ref)
        if row is None:
            raise ValueError(f"{position}: statement {ref!r} does not exist")
        statement_rows[ref] = row
        return ref

    if id is not None:
        _check_existing(id, "id")
    for i, spec in enumerate(links):
        _check_existing(spec["to_id"], f"links[{i}].to_id")
        if "when" in spec:
            _resolve_when_tree(spec["when"], _check_existing, f"links[{i}].when")
    for i, il in enumerate(incoming_links):
        _check_existing(il["from_id"], f"incoming_links[{i}].from_id")
        if "when" in il:
            _resolve_when_tree(il["when"], _check_existing, f"incoming_links[{i}].when")
    return statement_rows


@draftable_tool
def upsert_statement(
    kind: str,
    text: str,
    links: list[LinkSpec],
    id: str | None = None,
    incoming_links: list[IncomingLinkSpec] = [],
    allow_phrasing_violations: bool = False,
) -> dict[str, Any]:
    """Create a new statement or update an existing one.

    `kind` discriminates by the shape of claim the text makes. Required
    on every call. The seeded kinds are `event`, `state`, `capability`,
    `rule`, `property`, `procedure`, `action`, `check` and `cause`;
    `list_statement_kinds` describes each. The vocabulary is open: an
    unlisted kind is accepted. Phrasing rules dispatch by kind: `event`,
    `state`, `capability` and `rule` have catalogs of their own, and every
    other kind runs the `event` catalog. Links are checked only where a
    link type fixes the kinds at its ends (`list_link_types` shows each
    direction rule); otherwise kind-edge compatibility is trusted to the
    writer.

    Without `id`: always creates a brand-new statement with a fresh
    statement_id. There is NO text-based dedup — calling twice with the
    same text creates two statements. To update an existing statement, you
    must pass its `id` (capture it from a previous call's return value
    or from a `search_statements` hit).

    With `id`: replaces the statement at that id wholesale — re-embeds the
    new `text` and overwrites outgoing `links` with the exact list you pass
    (they are NOT appended). To add a single outgoing link, pass the full
    updated list, not just the addition. Raises if `id` does not exist.

    Mentions (which entities this statement refers to) are NOT passed in —
    they are derived automatically from the text and kept up to date. The
    statement simply mentions whatever named entities its words contain.

    `links` are the OUTGOING typed edges from this statement to existing
    targets — `{to_id, link_type}`. `incoming_links` are the
    INCOMING typed edges from existing sources to this statement —
    `{from_id, link_type}` — useful when wiring a new child
    statement under existing parents in one call instead of two. Both
    sides validate that referenced statement ids exist before any mutation.

    Asymmetric semantics: `links` is wholesale-replaced on update because
    it's the outgoing set this statement owns. `incoming_links` is
    idempotent-insert only (never deletes) because incoming edges live on
    OTHER statements and shouldn't be removed by an update to this one.

    `text` is checked against the phrasing catalog (compound, rule-shaped,
    property-shaped, hedge) before any mutation. By default, any match
    rejects the call: returns `{"rejected": True, "violations": [...]}`
    without writing. Pass `allow_phrasing_violations=True` to proceed
    anyway — the success response then carries the same violations under
    a `phrasing_violations` key as a warning.

    If embedding is unavailable, the write succeeds with `embedding_pending: true`.
    """

    violations, reject = _phrasing_gate(text, kind, allow_phrasing_violations)
    if reject is not None:
        return reject

    statement_rows = _validate_statement_refs(id, links, incoming_links)

    flip_edges: list[tuple[str, str, str, str, str, str]] = []
    for i, spec in enumerate(links):
        to_id = spec["to_id"]
        to_kind = _statement_kind(
            statement_rows, to_id, self_ref=(id, kind) if id is not None else None
        )
        flip_edges.append(
            (
                f"links[{i}]",
                id or "<new statement>",
                to_id,
                spec["link_type"],
                kind,
                to_kind,
            )
        )
    for i, il in enumerate(incoming_links):
        from_id = il["from_id"]
        from_kind = _statement_kind(
            statement_rows, from_id, self_ref=(id, kind) if id is not None else None
        )
        flip_edges.append(
            (
                f"incoming_links[{i}]",
                from_id,
                id or "<new statement>",
                il["link_type"],
                from_kind,
                kind,
            )
        )
    flip_errors = _collect_flip_errors(flip_edges)
    if flip_errors:
        raise ValueError("flipped link direction:\n" + "\n".join(flip_errors))

    vec = _try_embed(text)
    link_pairs = [
        (item["to_id"], item["link_type"], item.get("when")) for item in links
    ]

    with _persisted_index_write(statements=True):
        if id is not None:
            store.update_statement(_db(), id, kind, text)
            _set_statement_vector(id, vec)
            store.replace_links(_db(), id, link_pairs)
            statement_id = id
        else:
            statement_id = store.create_statement(_db(), kind, text)
            _set_statement_vector(statement_id, vec)
            store.replace_links(_db(), statement_id, link_pairs)

        # Mentions are derived from the text, not asserted by the caller.
        _derive_statement_mentions(statement_id, text)

        if incoming_links:
            edges = [
                (il["from_id"], statement_id, il["link_type"], il.get("when"))
                for il in incoming_links
            ]
            store.insert_links(_db(), edges)

    response: dict[str, Any] = {
        "statement_id": statement_id,
        "near_duplicates": (
            _near_duplicates(vec, exclude_id=statement_id) if vec is not None else []
        ),
    }
    if vec is None:
        response["embedding_pending"] = True
    if violations:
        response["phrasing_violations"] = violations
    return response


@draftable_tool
def upsert_statements(
    statements: list[BatchStatementSpec],
) -> dict[str, Any]:
    """Insert several statements in one call, with cross-references between
    siblings resolved server-side.

    For "I'm writing N atomic facts that are all part of one umbrella"
    or "umbrella + children + the contains edges between them", this is
    the right primitive — collapses what would be N+1+N tool calls into
    one and validates the cross-references atomically before mutating.

    Each item is the same shape as a single-record `upsert_statement`
    call, with one addition: any `to_statement_id` or `from_id`
    can be the literal string `"@N"` (N is a 0-based integer) to refer
    to the Nth statement in the same batch. Otherwise it must be an
    existing statement id. References are validated up front; an unknown
    id or out-of-range index raises before any write.

    Mentions are derived from each item's text automatically (see
    `upsert_statement`); there is no mentions field to pass.

    Phrasing validation runs per item before any mutation. Items whose
    text trips the phrasing catalog are rejected unless that item carries
    `allow_phrasing_violations: True`. Cascade rule: an item whose
    `links`, `incoming_links`, or any `when` tree references an `@N`
    that points to a rejected item is itself rejected (reason
    `"depends_on_rejected"`) — this avoids creating half-broken edges
    while keeping clean items in the batch passing.

    Returns:
        ```
        {
          "results": [
            {"statement_id": "stm_..."},                                # clean
            {"rejected": True, "violations": [...]},                   # phrasing-rejected
            {"statement_id": "stm_...", "phrasing_violations": [...]},  # bypassed
            {"rejected": True, "reason": "depends_on_rejected",
             "depends_on": [<int indexes>]}                            # cascaded
          ],
          "near_duplicates": {"stm_...": [...], ...},
          "embedding_pending": ["stm_...", ...]  # omitted when empty
        }
        ```

    Writes whose embedding is unavailable remain pending for background retry.
    """

    n = len(statements)
    if n == 0:
        return {"results": [], "near_duplicates": {}}

    # Phase 0: decide who survives (phrasing → cascade → flip) with no writes.
    plan = _plan_batch(statements)

    # Phase 1: try to embed surviving items before opening the write transaction.
    vecs: dict[int, list[float] | None] = {}
    for i, spec in enumerate(statements):
        if i not in plan.rejected:
            vecs[i] = _try_embed(spec["text"])

    # Phase 2: create surviving statements with their derived mentions, no
    # links yet. The name index is stable across the batch (statements
    # don't create names), so build it once.
    name_index = store.build_name_index(_db())
    statement_ids: dict[int, str] = {}
    with _persisted_index_write(
        statements=any(vec is not None for vec in vecs.values())
    ):
        for i, spec in enumerate(statements):
            if i in plan.rejected:
                continue
            bid = store.create_statement(_db(), spec["kind"], spec["text"])
            _set_statement_vector(bid, vecs[i])
            store.derive_mentions(_db(), bid, spec["text"], name_index)
            statement_ids[i] = bid

        # Phase 3: insert edges between surviving items. Cascade guarantees no
        # @-ref endpoint is in `plan.rejected`, so every edge has a real id at
        # both ends — but the when-trees still carry "@N" leaves that need
        # final substitution to real ids.
        edges = _materialize_batch_edges(
            n,
            plan.rejected,
            plan.resolved_outgoing,
            plan.resolved_incoming,
            statement_ids,
        )
        if edges:
            store.insert_links(_db(), edges)

    # Near-duplicate warnings per newly-inserted statement.
    near_dups: dict[str, list[dict[str, Any]]] = {}
    for i, bid in statement_ids.items():
        vec = vecs[i]
        if vec is None:
            continue
        hits = _near_duplicates(vec, exclude_id=bid)
        if hits:
            near_dups[bid] = hits

    results = _assemble_batch_results(
        n,
        plan.item_errors,
        plan.item_violations,
        plan.direct_rejected,
        plan.rejected,
        plan.cascade_reasons,
        statement_ids,
    )

    response: dict[str, Any] = {"results": results, "near_duplicates": near_dups}
    pending = [bid for i, bid in statement_ids.items() if vecs[i] is None]
    if pending:
        response["embedding_pending"] = pending
    return response


@draftable_tool
def replace_text(
    id: str, text: str, allow_phrasing_violations: bool = False
) -> dict[str, Any]:
    """Update a statement's text without touching its mentions or links.

    Re-embeds the new text and replaces the vector at the same numeric
    label in hnswlib. Faster and safer than `upsert_statement(id=…)` when
    you only want to fix wording or extend the description: avoids the
    risk of dropping existing mentions or outgoing links by forgetting
    to enumerate them in the wholesale-replace path.

    Raises ValueError if `id` does not exist.

    `text` is checked against the phrasing catalog before mutating; on
    rejection returns `{"rejected": True, "violations": [...]}` and the
    statement is unchanged. `allow_phrasing_violations=True` proceeds
    anyway and surfaces the violations as a `phrasing_violations`
    warning on the success response.

    If embedding is unavailable, the write succeeds with `embedding_pending: true`.
    """
    row = store.get_statement(_db(), id)
    if row is None:
        raise ValueError(f"statement {id!r} does not exist")

    violations, reject = _phrasing_gate(text, row["kind"], allow_phrasing_violations)
    if reject is not None:
        return reject

    vec = _try_embed(text)
    with _persisted_index_write(statements=True):
        store.update_statement_text(_db(), id, text)
        _set_statement_vector(id, vec)
        # Text changed → re-derive mentions.
        _derive_statement_mentions(id, text)
    response: dict[str, Any] = {"statement_id": id}
    if vec is None:
        response["embedding_pending"] = True
    if violations:
        response["phrasing_violations"] = violations
    return response


@draftable_tool
def patch_statement(
    id: str,
    kind: str | None = None,
    text: str | None = None,
    allow_phrasing_violations: bool = False,
) -> dict[str, Any]:
    """Partial update of an existing statement.

    Unlike `upsert_statement(id=…)` which replaces the whole record (and
    silently drops fields you forget to pass), `patch_statement` only
    modifies the fields you explicitly provide. Omit a field to leave
    it untouched.

    Patchable fields:
      - `kind` — re-classify without re-embedding.
      - `text` — replace the text and re-embed; phrasing-checked under
        the *effective* kind (the new kind if you also pass `kind`,
        otherwise the existing one). Mentions are re-derived from the new
        text automatically.

    Out of scope by design:
      - Mentions are derived from text, never set directly.
      - Outgoing links and incoming links live on a separate join table
        and are NEVER touched by this tool. Use `add_links` /
        `remove_links` for surgical link edits, or `upsert_statement`
        if you really want to replace the whole edge set.

    Embedding cost: we re-embed only when `text` is provided. Patching
    `kind` alone does not call the embedder and does not update the vector
    index or mentions — it's a single SQL update.

    Phrasing validation behaves identically to `replace_text`: returns
    `{"rejected": True, "violations": [...]}` without writing on
    rejection; `allow_phrasing_violations=True` proceeds and surfaces
    the violations as a `phrasing_violations` warning on success.

    If embedding is unavailable, a text patch succeeds with `embedding_pending: true`.

    Raises ValueError if `id` does not exist.
    """
    row = store.get_statement(_db(), id)
    if row is None:
        raise ValueError(f"statement {id!r} does not exist")

    if kind is None and text is None:
        return {"statement_id": id, "no_change": True}

    effective_kind = kind if kind is not None else row["kind"]

    # Phrasing check + embedding only when text is being patched. The
    # check runs under the *effective* kind so a same-call kind+text
    # patch sees the new kind's catalog, not the old one.
    violations: list[phrasing.Violation] = []
    vec = None
    if text is not None:
        violations, reject = _phrasing_gate(
            text, effective_kind, allow_phrasing_violations
        )
        if reject is not None:
            return reject
        vec = _try_embed(text)

    # Mutate field-by-field so omitted fields stay untouched.
    with _persisted_index_write(statements=text is not None):
        if text is not None and kind is not None:
            store.update_statement(_db(), id, kind, text)
        elif text is not None:
            store.update_statement_text(_db(), id, text)
        elif kind is not None:
            store.update_statement_kind(_db(), id, kind)

        if text is not None:
            _set_statement_vector(id, vec)
        # Re-derive mentions only when the text changed (kind-only patches
        # don't affect what entities the text mentions).
        if text is not None:
            _derive_statement_mentions(id, text)

    response: dict[str, Any] = {"statement_id": id}
    if violations:
        response["phrasing_violations"] = violations
    if text is not None and vec is None:
        response["embedding_pending"] = True
    elif vec is not None:
        response["near_duplicates"] = _near_duplicates(vec, exclude_id=id)
    return response


@draftable_tool
def merge_statements(from_id: str, into_id: str) -> dict[str, Any]:
    """Merge one Statement into another and delete the source.

    Use case: you discover two statements are saying the same fact under
    different wordings (or via parallel drafts) and want a single
    canonical record. After the merge, every link or mention that
    pointed at the source now points at the target instead, and the
    source is gone.

    Specifically:
    - `mentions` are derived from text, so the target keeps its own
      (its text is unchanged) and the source's are discarded with the
      source — `mentions_moved` is always 0.
    - Outgoing `links` (the source's own outgoing edges) are unioned
      onto the target, deduped on `(to_statement_id, link_type)`.
      Self-loops created by the merge — e.g. an edge `from → into`
      that would become `into → into` — are silently dropped.
    - Incoming links (other statements that pointed at `from`) are
      rewritten to point at `into`, with the same dedup and self-loop
      drop logic.
    - The source's vector is marked deleted in hnswlib so it stops
      surfacing in `search_statements`.
    - The source's record and vector_id mapping are deleted.

    The target's `text` is unchanged. If the surviving wording should
    be synthesised across both, call `upsert_statement(id=into, text=…)`
    afterwards.

    Use `merge_statements` when the source's meaning lives on through the
    target — duplicate facts under different wording, parallel drafts,
    "this was wrong, replaced by X." For statements that should simply
    cease to exist (feature removed, fact obsolete, no replacement), use
    `delete_statement(id)` instead.

    Returns counts: `{into_id, mentions_moved,
    outgoing_links_moved, incoming_links_moved}`. The "moved" counts
    reflect rows actually inserted onto the target — duplicates and
    self-loops are excluded.

    No-op when `from_id == into_id`. Raises
    ValueError if either id does not exist.
    """

    if from_id == into_id:
        return {
            "into_id": into_id,
            "mentions_moved": 0,
            "outgoing_links_moved": 0,
            "incoming_links_moved": 0,
        }

    if store.get_statement(_db(), from_id) is None:
        raise ValueError(f"statement {from_id!r} does not exist")
    if store.get_statement(_db(), into_id) is None:
        raise ValueError(f"statement {into_id!r} does not exist")

    # Mentions are derived from text: the target keeps its own (text
    # unchanged) and the source's derived rows are cleared so the source
    # can be deleted under FK enforcement. Nothing is moved.
    mentions_moved = 0
    with _persisted_index_write(statements=True):
        store.clear_derived_for_statement(_db(), from_id)
        outgoing_moved = store.merge_outgoing_links_into(_db(), from_id, into_id)
        incoming_moved = store.merge_incoming_links_into(_db(), from_id, into_id)
        # Any remaining links that referenced the source as a `when` condition
        # need their reference rewritten to the target before deleting the
        # source, otherwise FK enforcement blocks the delete.
        store.rewrite_when_references(_db(), from_id, into_id)

        vector_id = store.get_vector_id(_db(), from_id)
        if vector_id is not None:
            _idx().delete(vector_id)
        store.delete_statement(_db(), from_id, merged_into=into_id)
        # Media lives in its own database and commits first, as anchors do
        # in `merge_entities`: a failed substrate commit leaves the media on
        # the surviving statement.
        media.target_merged("statement", from_id, into_id)
    return {
        "into_id": into_id,
        "mentions_moved": mentions_moved,
        "outgoing_links_moved": outgoing_moved,
        "incoming_links_moved": incoming_moved,
    }


@draftable_tool
def delete_statement(id: str) -> dict[str, Any]:
    """Permanently delete a statement with no replacement.

    Use case: the fact no longer applies — feature removed from the
    product, claim obsolete, statement was authored against a flow that
    has since been deleted — and there is no other statement the meaning
    should flow into. For "this is a duplicate of X" or "this was
    wrong, replaced by Y", use `merge_statements` instead so the
    relationships survive on the target.

    Cascade statement. The substrate cleans up dependent rows so
    deletion can't leave dangling references:

    - `mentions` of this statement are removed.
    - Incoming links (other statements → this) are removed — they no
      longer have a target and aren't meaningful in isolation.
    - Outgoing links (this → other statements) are removed.
    - Any edge anywhere in the graph whose `when` tree referenced this
      statement as a leaf is removed — the conditional relationship
      can't hold once one of its leaves is gone. If you intend the
      condition to live on under a different identity, `merge_statements`
      first to rewrite the references onto the target, then delete (or
      just merge — that already removes the source).
    - The vector slot is marked deleted in hnswlib; subsequent inserts
      reuse it.
    - The statement record and its `vector_id` mapping are dropped.

    Returns `{deleted: True, mentions_removed,
    incoming_links_removed, outgoing_links_removed,
    when_references_removed}` — counts of cascaded rows so the caller
    can sanity-check the blast radius.

    Permanent. Raises ValueError on unknown id.
    """

    if store.get_statement(_db(), id) is None:
        raise ValueError(f"statement {id!r} does not exist")

    # Order matters under FK enforcement: drop everything that points AT this
    # statement before dropping the statement itself. This removes outgoing
    # and incoming statement links and links whose conditions reference it.
    with _persisted_index_write(statements=True):
        (
            outgoing_removed,
            incoming_removed,
            when_removed,
        ) = store.delete_links_touching_statement(_db(), id)
        mentions_removed = store.clear_derived_for_statement(_db(), id)

        vector_id = store.get_vector_id(_db(), id)
        if vector_id is not None:
            _idx().delete(vector_id)
        store.delete_statement(_db(), id)
        media.target_deleted("statement", id)
    return {
        "deleted": True,
        "mentions_removed": mentions_removed,
        "incoming_links_removed": incoming_removed,
        "outgoing_links_removed": outgoing_removed,
        "when_references_removed": when_removed,
    }
