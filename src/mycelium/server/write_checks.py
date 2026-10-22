"""Checks a statement write must pass before it lands.

Shared by the single-statement writes, the batch planner and `add_links`, so
every path rejects the same things: phrasing that trips the catalog without a
bypass, an edge whose statement kinds show it points the wrong way, and a
condition tree that is malformed or names a statement the caller's resolver
rejects. Each check returns its findings and leaves raise-or-accumulate to the
caller.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from .. import link_rules, phrasing, when_expression


def _statement_kind(
    statement_rows: dict[str, sqlite3.Row],
    statement_id: str,
    *,
    self_ref: tuple[str, str] | None = None,
) -> str:
    # `self_ref` is the (id, kind) of a statement being upserted in this same
    # request — it isn't in `statement_rows` yet, so resolve it directly.
    if self_ref is not None and statement_id == self_ref[0]:
        return self_ref[1]
    kind: str = statement_rows[statement_id]["kind"]
    return kind


def _format_flip_error(
    *,
    position: str,
    from_id: str,
    to_id: str,
    link_type: str,
    from_kind: str,
    to_kind: str,
) -> str | None:
    err = link_rules.flip_error(link_type, from_kind, to_kind)
    if err is None:
        return None
    return f"{position}: {from_id} ({from_kind}) -> {to_id} ({to_kind}): {err}"


def _collect_flip_errors(
    edges: list[tuple[str, str, str, str, str, str]],
) -> list[str]:
    """Format the flip-direction error for each edge and return the non-empty
    messages. Each edge is a positional tuple matching `_format_flip_error`'s
    parameters: (position, from_id, to_id, link_type, from_kind, to_kind).
    Callers keep their own raise-vs-accumulate handling; this is the shared
    fold behind the single-record, batch, and add_links link checks."""
    errors: list[str] = []
    for position, from_id, to_id, link_type, from_kind, to_kind in edges:
        err = _format_flip_error(
            position=position,
            from_id=from_id,
            to_id=to_id,
            link_type=link_type,
            from_kind=from_kind,
            to_kind=to_kind,
        )
        if err is not None:
            errors.append(err)
    return errors


def _phrasing_gate(
    text: str, kind: str, allow: bool
) -> tuple[list[phrasing.Violation], dict[str, Any] | None]:
    """Run the phrasing catalog check for `text` under `kind`. Returns
    `(violations, reject)` where `reject` is the
    `{"rejected": True, "violations": [...]}` response dict when the text trips
    the catalog without bypass, else None. Callers that get a non-None `reject`
    return it verbatim; otherwise they proceed and may surface `violations` as
    a `phrasing_violations` warning on success."""
    violations = phrasing.check(text, kind=kind)
    if violations and not allow:
        return violations, {"rejected": True, "violations": violations}
    return violations, None


def _resolve_when_tree(
    when: dict[str, Any] | None,
    resolve_id: Callable[[str, str], object],
    position: str,
) -> dict[str, Any] | None:
    """Walk a when-tree and resolve every leaf's `statement_id` via
    `resolve_id(ref, position)`. Returns a new tree (input unchanged).

    Used by both the single-record path (where `resolve_id` checks the
    id exists in the store) and the batch path (where `resolve_id`
    additionally accepts `@N` refs and returns int indexes).
    """
    if when is None:
        return None
    when_expression.validate(when)

    def _walk(expr: dict[str, Any], pos: str) -> dict[str, Any]:
        if "statement_id" in expr:
            return {"statement_id": resolve_id(expr["statement_id"], pos)}
        return {
            "op": expr["op"],
            "of": [_walk(c, f"{pos}.of[{i}]") for i, c in enumerate(expr["of"])],
        }

    return _walk(when, position)
