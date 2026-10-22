"""Planning an `upsert_statements` batch before any of it is written.

A batch may address its own members as `@N`, in links, incoming links and
condition trees. Planning resolves those references, runs the phrasing and
link-direction checks per member, and cascades a rejection to every member that
depends on a rejected one. `upsert_statements` then writes only what the plan
accepted. Planning reads the substrate but never writes it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .. import phrasing, store, when_expression
from .runtime import _db
from .specs import BatchStatementSpec
from .write_checks import _collect_flip_errors, _phrasing_gate, _resolve_when_tree


def _at_refs_in_when(when: dict[str, Any] | None) -> list[int]:
    """Return every `@N` index referenced anywhere in a when-tree.
    Used by the batch upsert's cascade detection."""
    if when is None:
        return []
    out: list[int] = []
    for leaf_id in when_expression.leaves(when):
        if isinstance(leaf_id, str) and leaf_id.startswith("@"):
            try:
                out.append(int(leaf_id[1:]))
            except ValueError:
                continue
    return out


def _batch_phrasing_pass(
    statements: list[BatchStatementSpec],
) -> tuple[list[list[phrasing.Violation]], set[int]]:
    """Phrasing check per batch item. Returns each item's violations plus the
    set of indexes directly rejected (tripped the catalog without bypass)."""
    item_violations: list[list[phrasing.Violation]] = []
    direct_rejected: set[int] = set()
    for i, spec in enumerate(statements):
        viols, reject = _phrasing_gate(
            spec["text"], spec["kind"], spec.get("allow_phrasing_violations", False)
        )
        item_violations.append(viols)
        if reject is not None:
            direct_rejected.add(i)
    return item_violations, direct_rejected


def _spec_at_refs(spec: BatchStatementSpec) -> list[int]:
    """Every `@N` index a batch item references via its links,
    incoming_links, or any `when` tree."""
    refs: list[int] = []
    for link in spec.get("links", []) or []:
        ref = link.get("to_id")
        if ref and ref.startswith("@"):
            try:
                refs.append(int(ref[1:]))
            except ValueError:
                pass
        refs.extend(_at_refs_in_when(link.get("when")))
    for il in spec.get("incoming_links", []) or []:
        ref = il.get("from_id")
        if ref and ref.startswith("@"):
            try:
                refs.append(int(ref[1:]))
            except ValueError:
                pass
        refs.extend(_at_refs_in_when(il.get("when")))
    return refs


def _close_cascade(
    statements: list[BatchStatementSpec],
    rejected: set[int],
    cascade_reasons: dict[int, list[int]],
) -> None:
    """Cascade rejection — transitive closure on @-refs. Any surviving item
    that references a rejected sibling via @N joins the rejected set.
    Iterates to a fixed point so a chain @0→@1→@2 of rejections cascades all
    the way. Mutates `rejected` and `cascade_reasons` in place."""
    changed = True
    while changed:
        changed = False
        for i, spec in enumerate(statements):
            if i in rejected:
                continue
            deps = sorted({r for r in _spec_at_refs(spec) if r in rejected})
            if deps:
                rejected.add(i)
                cascade_reasons[i] = deps
                changed = True


def _resolve_batch_refs(
    statements: list[BatchStatementSpec],
    rejected: set[int],
) -> tuple[
    list[list[tuple[int | str, str, dict[str, Any] | None]]],
    list[list[tuple[int | str, str, dict[str, Any] | None]]],
    dict[str, sqlite3.Row],
]:
    """Validate every cross-reference for SURVIVING items only. Rejected
    items aren't created, so their refs don't need checking.

    Each resolved entry is (endpoint_ref, link_type, when_raw_tree).
    `endpoint_ref` is int (sibling index) or str (existing id).
    `when_raw_tree` is None or a tree whose leaves carry statement_ids
    that are still in raw form ("@N" or existing ids); siblings get
    remapped to real ids in Phase 5 once they're created. Also returns the
    fetched rows of existing statements for downstream kind lookups."""
    n = len(statements)
    statement_rows: dict[str, sqlite3.Row] = {}

    def _resolve_ref(ref: str, position: str) -> int | str:
        if ref.startswith("@"):
            try:
                idx = int(ref[1:])
            except ValueError:
                raise ValueError(f"{position}: malformed batch ref {ref!r}")
            if not (0 <= idx < n):
                raise ValueError(
                    f"{position}: batch index @{idx} out of range [0, {n})"
                )
            return idx
        row = store.get_statement(_db(), ref)
        if row is None:
            raise ValueError(f"{position}: statement {ref!r} does not exist")
        statement_rows[ref] = row
        return ref

    resolved_outgoing: list[list[tuple[int | str, str, dict[str, Any] | None]]] = [
        [] for _ in range(n)
    ]
    resolved_incoming: list[list[tuple[int | str, str, dict[str, Any] | None]]] = [
        [] for _ in range(n)
    ]
    for i, spec in enumerate(statements):
        if i in rejected:
            continue
        for j, link in enumerate(spec.get("links", []) or []):
            target = _resolve_ref(link["to_id"], f"statements[{i}].links[{j}]")
            when_raw = link.get("when")
            if when_raw is not None:
                # Validate shape + every leaf @N is in range / every existing id exists.
                _resolve_when_tree(
                    when_raw, _resolve_ref, f"statements[{i}].links[{j}].when"
                )
            resolved_outgoing[i].append((target, link["link_type"], when_raw))
        for j, il in enumerate(spec.get("incoming_links", []) or []):
            source = _resolve_ref(il["from_id"], f"statements[{i}].incoming_links[{j}]")
            when_raw = il.get("when")
            if when_raw is not None:
                _resolve_when_tree(
                    when_raw, _resolve_ref, f"statements[{i}].incoming_links[{j}].when"
                )
            resolved_incoming[i].append((source, il["link_type"], when_raw))
    return resolved_outgoing, resolved_incoming, statement_rows


def _collect_batch_flip_errors(
    statements: list[BatchStatementSpec],
    rejected: set[int],
    resolved_outgoing: list[list[tuple[int | str, str, dict[str, Any] | None]]],
    resolved_incoming: list[list[tuple[int | str, str, dict[str, Any] | None]]],
    statement_rows: dict[str, sqlite3.Row],
    item_errors: list[list[str]],
) -> None:
    """Flip-direction check per surviving batch item. Appends each item's
    error messages to `item_errors[i]` (per-item accumulation — batch items
    reject individually rather than failing the whole call)."""

    def _ref_kind(ref: int | str) -> str:
        if isinstance(ref, int):
            return statements[ref]["kind"]
        kind: str = statement_rows[ref]["kind"]
        return kind

    def _ref_label(ref: int | str) -> str:
        return f"@{ref}" if isinstance(ref, int) else ref

    for i, spec in enumerate(statements):
        if i in rejected:
            continue
        flip_edges: list[tuple[str, str, str, str, str, str]] = []
        for j, (target, link_type, _when) in enumerate(resolved_outgoing[i]):
            flip_edges.append(
                (
                    f"statements[{i}].links[{j}]",
                    f"@{i}",
                    _ref_label(target),
                    link_type,
                    spec["kind"],
                    _ref_kind(target),
                )
            )
        for j, (source, link_type, _when) in enumerate(resolved_incoming[i]):
            flip_edges.append(
                (
                    f"statements[{i}].incoming_links[{j}]",
                    _ref_label(source),
                    f"@{i}",
                    link_type,
                    _ref_kind(source),
                    spec["kind"],
                )
            )
        item_errors[i].extend(_collect_flip_errors(flip_edges))


def _materialize_batch_edges(
    n: int,
    rejected: set[int],
    resolved_outgoing: list[list[tuple[int | str, str, dict[str, Any] | None]]],
    resolved_incoming: list[list[tuple[int | str, str, dict[str, Any] | None]]],
    statement_ids: dict[int, str],
) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """Materialize the edges between surviving items. Cascade guarantees no
    @-ref endpoint is in `rejected`, so every edge has a real id at both
    ends — but the when-trees still carry "@N" leaves that need final
    substitution to real ids."""

    def _resolve_endpoint(ref: int | str) -> str:
        return statement_ids[ref] if isinstance(ref, int) else ref

    def _materialize_when(when: dict[str, Any] | None) -> dict[str, Any] | None:
        if when is None:
            return None
        return when_expression.substitute_leaves(
            when,
            lambda leaf: statement_ids[int(leaf[1:])] if leaf.startswith("@") else leaf,
        )

    edges: list[tuple[str, str, str, dict[str, Any] | None]] = []
    for i in range(n):
        if i in rejected:
            continue
        for target, link_type, when in resolved_outgoing[i]:
            edges.append(
                (
                    statement_ids[i],
                    _resolve_endpoint(target),
                    link_type,
                    _materialize_when(when),
                )
            )
        for source, link_type, when in resolved_incoming[i]:
            edges.append(
                (
                    _resolve_endpoint(source),
                    statement_ids[i],
                    link_type,
                    _materialize_when(when),
                )
            )
    return edges


def _assemble_batch_results(
    n: int,
    item_errors: list[list[str]],
    item_violations: list[list[phrasing.Violation]],
    direct_rejected: set[int],
    rejected: set[int],
    cascade_reasons: dict[int, list[int]],
    statement_ids: dict[int, str],
) -> list[dict[str, Any]]:
    """Build per-item results, preserving rejection precedence: flip errors
    beat direct (phrasing) rejection, which beats cascade rejection."""
    results: list[dict[str, Any]] = []
    for i in range(n):
        if item_errors[i]:
            results.append({"rejected": True, "errors": item_errors[i]})
        elif i in direct_rejected:
            results.append({"rejected": True, "violations": item_violations[i]})
        elif i in rejected:
            results.append(
                {
                    "rejected": True,
                    "reason": "depends_on_rejected",
                    "depends_on": cascade_reasons[i],
                }
            )
        else:
            entry: dict[str, Any] = {"statement_id": statement_ids[i]}
            if item_violations[i]:
                entry["phrasing_violations"] = item_violations[i]
            results.append(entry)
    return results


@dataclass
class _BatchPlan:
    """The read-only plan for a batch upsert: which items survive, why the
    rest were rejected, and the resolved-but-unwritten edges for survivors.

    Computed by `_plan_batch` before any embedding or write, so the whole
    rejection decision (phrasing → cascade → flip → cascade) is a pure
    function of the input plus read-only substrate lookups — testable
    without Ollama or a write transaction."""

    item_violations: list[list[phrasing.Violation]]
    item_errors: list[list[str]]
    direct_rejected: set[int]
    rejected: set[int]
    cascade_reasons: dict[int, list[int]]
    resolved_outgoing: list[list[tuple[int | str, str, dict[str, Any] | None]]]
    resolved_incoming: list[list[tuple[int | str, str, dict[str, Any] | None]]]


def _plan_batch(statements: list[BatchStatementSpec]) -> _BatchPlan:
    """Decide the fate of every item in a batch upsert without mutating
    anything: run the phrasing gate, cascade @-ref rejections to a fixed
    point, validate/resolve each survivor's cross-references, then reject
    items whose links flip a directional rule (cascading once more).

    Reads existing statements to validate non-sibling refs, but performs no
    writes — the caller embeds and persists the survivors."""
    n = len(statements)

    # Phrasing check per item; items that trip the catalog without bypass
    # are directly rejected.
    item_violations, direct_rejected = _batch_phrasing_pass(statements)
    item_errors: list[list[str]] = [[] for _ in range(n)]

    # Cascade rejection — transitive closure on @-refs.
    rejected: set[int] = set(direct_rejected)
    cascade_reasons: dict[int, list[int]] = {}
    _close_cascade(statements, rejected, cascade_reasons)

    # Validate every cross-reference for SURVIVING items only. Rejected
    # items aren't created, so their refs don't need checking.
    resolved_outgoing, resolved_incoming, statement_rows = _resolve_batch_refs(
        statements, rejected
    )

    _collect_batch_flip_errors(
        statements,
        rejected,
        resolved_outgoing,
        resolved_incoming,
        statement_rows,
        item_errors,
    )

    # A flip error rejects that item, which can cascade to its @-ref dependents.
    flip_rejected = {i for i, errors in enumerate(item_errors) if errors}
    if flip_rejected:
        direct_rejected.update(flip_rejected)
        rejected.update(flip_rejected)
        _close_cascade(statements, rejected, cascade_reasons)

    return _BatchPlan(
        item_violations=item_violations,
        item_errors=item_errors,
        direct_rejected=direct_rejected,
        rejected=rejected,
        cascade_reasons=cascade_reasons,
        resolved_outgoing=resolved_outgoing,
        resolved_incoming=resolved_incoming,
    )
