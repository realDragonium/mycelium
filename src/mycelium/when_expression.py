"""Expression trees for `when` conditions on statement-to-statement links.

A `WhenExpression` is a tree:

    WhenExpression =
        {"statement_id": str}                          # leaf
      | {"op": "and", "of": list[WhenExpression]}     # internal AND  (>=1 child)
      | {"op": "or",  "of": list[WhenExpression]}     # internal OR   (>=1 child)
      | {"op": "not", "of": list[WhenExpression]}     # internal NOT  (exactly 1 child)

`canonicalize` reduces a tree to its canonical form:
  - recursively canonicalizes children
  - flattens same-op nesting for AND/OR (AND(X, AND(Y, Z)) → AND(X, Y, Z));
    NOT does NOT flatten — NOT(NOT(X)) folds to X via double-negation
    elimination instead
  - dedupes structurally-equal children (AND/OR only)
  - sorts children by their canonical hash (commutativity; AND/OR only)
  - collapses single-child AND/OR (AND(X) → X); NOT is preserved

The result is unique up to semantic equivalence: any two trees with the
same boolean meaning over their leaves canonicalize to the same form.

`hash_canonical` returns a deterministic SHA-256 hex of the canonical
serialization. The sentinel `HASH_NONE` (literal string "NONE") stands
in for "no condition" — the substrate stores it in `links.when_hash`
when the link is unconditional, so SQLite's UNIQUE constraint can do
its job (NULLs are treated as distinct under UNIQUE).

`leaves` walks the tree and returns every `statement_id` referenced;
this is what the link_when_leaves index would store and what cascade
detection / dependency lookups query.

`substitute_leaves` returns a new tree with every leaf's `statement_id`
remapped through a function — used by batch upserts to swap `@N`
sibling references for real ids after sibling creation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

HASH_NONE = "NONE"


# ─── shape predicates ───────────────────────────────────────────────────────


def is_leaf(expr: dict[str, Any]) -> bool:
    return "statement_id" in expr


def is_internal(expr: dict[str, Any]) -> bool:
    return "op" in expr


# ─── validation ─────────────────────────────────────────────────────────────


def validate(expr: Any) -> None:
    """Raise ValueError if `expr` is not a structurally valid WhenExpression.

    Shape-only: does NOT verify statement_ids exist in the store, and does
    NOT reject `@N`-style batch references in leaves (those are valid
    intermediate states during batch resolution). Internal nodes with one
    child are tolerated here so canonicalize can collapse them; only
    empty `of` lists fail validation.
    """
    if not isinstance(expr, dict):
        raise ValueError(f"when expression must be a dict, got {type(expr).__name__}")
    if is_leaf(expr) and is_internal(expr):
        raise ValueError(
            "expression has both 'statement_id' and 'op' — must be one or the other"
        )
    if is_leaf(expr):
        if set(expr.keys()) != {"statement_id"}:
            raise ValueError(
                f"leaf must have only 'statement_id', got keys {sorted(expr.keys())}"
            )
        if not isinstance(expr["statement_id"], str) or not expr["statement_id"]:
            raise ValueError("leaf 'statement_id' must be a non-empty string")
        return
    if is_internal(expr):
        if set(expr.keys()) != {"op", "of"}:
            raise ValueError(
                f"internal node must have keys {{'op', 'of'}}, got {sorted(expr.keys())}"
            )
        if expr["op"] not in ("and", "or", "not"):
            raise ValueError(f"op must be 'and', 'or', or 'not', got {expr['op']!r}")
        if not isinstance(expr["of"], list):
            raise ValueError(f"'of' must be a list, got {type(expr['of']).__name__}")
        if not expr["of"]:
            raise ValueError("'of' must be non-empty")
        if expr["op"] == "not" and len(expr["of"]) != 1:
            raise ValueError(
                f"'not' must have exactly one child, got {len(expr['of'])}"
            )
        for child in expr["of"]:
            validate(child)
        return
    raise ValueError(
        f"expression must be a leaf {{'statement_id'}} or internal {{'op', 'of'}}, "
        f"got keys {sorted(expr.keys())}"
    )


# ─── canonicalization ───────────────────────────────────────────────────────


def _serialize(expr: dict[str, Any]) -> str:
    """Compact JSON with deterministic key order — feeds the hash."""
    return json.dumps(expr, sort_keys=True, separators=(",", ":"))


def _hash_node(expr: dict[str, Any]) -> str:
    return hashlib.sha256(_serialize(expr).encode("utf-8")).hexdigest()


def _canonicalize_inner(expr: dict[str, Any]) -> dict[str, Any]:
    """Recursive worker — assumes `expr` already passed `validate`."""
    if is_leaf(expr):
        return {"statement_id": expr["statement_id"]}

    op = expr["op"]

    # Recurse first so children are canonical before we look at structure.
    children = [_canonicalize_inner(c) for c in expr["of"]]

    if op == "not":
        # NOT has exactly one child (enforced by validate). Fold
        # NOT(NOT(X)) → X so double negation does not produce a
        # distinct hash from X.
        child = children[0]
        if is_internal(child) and child["op"] == "not":
            return child["of"][0]
        return {"op": "not", "of": [child]}

    # Associativity: pull up children that share our op. AND(X, AND(Y, Z))
    # becomes AND(X, Y, Z); same for OR.
    flattened: list[dict[str, Any]] = []
    for c in children:
        if is_internal(c) and c["op"] == op:
            flattened.extend(c["of"])
        else:
            flattened.append(c)

    # Idempotence: deduplicate by hash, preserving first occurrence.
    seen: dict[str, dict[str, Any]] = {}
    for c in flattened:
        h = _hash_node(c)
        if h not in seen:
            seen[h] = c
    deduped = list(seen.values())

    # Collapse single-child. After dedup it's possible to collapse even
    # when the input had multiple children that all reduced to the same
    # subtree (e.g. AND(X, X) → AND(X) → X).
    if len(deduped) == 1:
        return deduped[0]

    # Commutativity: sort children by their canonical hash so AND(X, Y)
    # and AND(Y, X) produce identical output.
    deduped.sort(key=_hash_node)

    return {"op": op, "of": deduped}


def canonicalize(expr: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical form of `expr`. Validates first.

    Idempotent: canonicalize(canonicalize(x)) == canonicalize(x).
    """
    validate(expr)
    return _canonicalize_inner(expr)


def hash_canonical(expr: dict[str, Any] | None) -> str:
    """Deterministic SHA-256 hex of the canonical tree.

    Returns `HASH_NONE` (the literal string "NONE") when `expr` is None,
    so unconditional links get a non-NULL hash and SQLite's UNIQUE
    constraint behaves correctly across multiple unconditional links
    between the same endpoints.
    """
    if expr is None:
        return HASH_NONE
    return _hash_node(canonicalize(expr))


# ─── leaf walking ───────────────────────────────────────────────────────────


def _walk_leaves(expr: dict[str, Any], visit: Callable[[str], None]) -> None:
    if is_leaf(expr):
        visit(expr["statement_id"])
        return
    for c in expr["of"]:
        _walk_leaves(c, visit)


def leaves(expr: dict[str, Any] | None) -> set[str]:
    """Every `statement_id` referenced anywhere in `expr`. Empty set for
    None or for trees with no leaves (which validate rejects)."""
    if expr is None:
        return set()
    out: set[str] = set()
    _walk_leaves(expr, out.add)
    return out


def substitute_leaves(
    expr: dict[str, Any], mapping: Callable[[str], str]
) -> dict[str, Any]:
    """Return a new tree with every leaf's `statement_id` remapped via
    `mapping(old) -> new`. Used by batch upserts to resolve `@N` sibling
    refs after the siblings get real ids assigned. Internal nodes are
    rebuilt fresh, so the result is structurally independent of the
    input — safe to canonicalize without aliasing concerns.
    """
    if is_leaf(expr):
        return {"statement_id": mapping(expr["statement_id"])}
    return {"op": expr["op"], "of": [substitute_leaves(c, mapping) for c in expr["of"]]}
