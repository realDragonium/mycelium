"""The vocabulary tools: statement kinds, link types and their aliases, entity link types.

The installed glossary defines what a statement may be and how statements and
entities may connect. Writers read it to choose a kind or link type, and the
list tools also describe each link type's direction rule. Edits here change
which writes the substrate accepts, so they go through the same draft redirect
as any other write.
"""

from __future__ import annotations

from typing import Any

from .. import link_rules, store
from .registry import tool
from .runtime import _db


def _direction_entry(link_type: str) -> dict[str, list[str] | None] | None:
    direction = link_rules.LINK_DIRECTION.get(link_type)
    if direction is None:
        return None
    source_kinds, target_kinds = direction
    return {
        "source_kinds": None if source_kinds is None else sorted(source_kinds),
        "target_kinds": None if target_kinds is None else sorted(target_kinds),
    }


@tool
def list_link_types() -> list[dict[str, Any]]:
    """List the statement→statement link types known to the substrate.

    Returns `[{link_type, description, usage_count, direction?}]` sorted
    alphabetically. `description` comes from the
    `statement_link_type_glossary` table (DB-backed, editable via the
    website or `upsert_link_type`); empty string for any type that's
    in the database but has no glossary entry. `usage_count` is the
    number of statement_links rows currently carrying this type — 0
    means the type is defined but not yet used anywhere.

    Reach for this whenever a `get_statements` or `search_statements`
    response shows a `link_type` you're not sure about. Vocabulary is
    open — new types may appear in `in_use` results without a glossary
    entry. Reuse before inventing.

    ─── `when` expressions on edges ──────────────────────────────────
    A link may carry a `when` field that conditions whether the edge
    fires. The grammar is a small tree:

      leaf      = {"statement_id": "stm_…"}
      internal  = {"op": "and", "of": [<expr>, <expr>, …]}    # >=1 child
                | {"op": "or",  "of": [<expr>, <expr>, …]}    # >=1 child
                | {"op": "not", "of": [<expr>]}               # exactly 1 child

    A leaf is satisfied when the referenced statement (a `state`-kind
    statement, by convention) currently holds. `and`/`or` combine
    children boolean-fashion; `not` inverts its single child — the edge
    fires when that child does NOT hold. Absence of a `when` field means
    the edge is unconditional — it fires whenever the source fires.

    Example — a rejection trigger that only fires when both a template
    is configured AND the outgoing edge conditions failed:

      {"op": "and", "of": [
        {"statement_id": "stm_template_configured"},
        {"statement_id": "stm_edge_conditions_failed"}
      ]}

    Example — a sharing guard that fires only when the result has NOT
    already been shared:

      {"op": "not", "of": [{"statement_id": "stm_result_already_shared"}]}

    To follow what a `when` leaf refers to, call `get_statements([id])` on
    the leaf's `statement_id` — same pattern as chasing a link target.
    """
    counts = store.count_statement_links_by_type(_db())
    glossary = {
        r["link_type"]: r["description"]
        for r in store.list_statement_link_type_glossary(_db())
    }
    all_types = sorted(set(counts) | set(glossary))
    rows: list[dict[str, Any]] = []
    for t in all_types:
        row: dict[str, Any] = {
            "link_type": t,
            "type": t,
            "description": glossary.get(t, ""),
            "usage_count": counts.get(t, 0),
            "in_use": "true" if counts.get(t, 0) else "false",
        }
        direction = _direction_entry(t)
        if direction is not None:
            row["direction"] = direction
        rows.append(row)
    return rows


@tool
def list_statement_kinds() -> list[dict[str, Any]]:
    """List the statement `kind` values known to the substrate.

    Returns `[{kind, description, when_to_use, usage_count}]` sorted
    alphabetically. `description` and `when_to_use` come from the
    `statement_kind_glossary` table (DB-backed, editable via the
    website or `upsert_statement_kind`); empty strings for kinds
    present on statements but missing from the glossary. `usage_count`
    is the number of statements currently carrying that kind — 0
    means the kind is defined but not yet used.

    Use this when you need to know what shape of claim to write —
    each `kind` enforces a different phrasing catalog at the
    substrate boundary (event / state / capability / rule / property
    for descriptive content; procedure / action / check / cause for
    prescriptive how-to and diagnostic content). Vocabulary is open
    — new kinds run the event phrasing catalog as a baseline.
    """
    glossary_rows = store.list_statement_kind_glossary(_db())
    glossary = {
        r["kind"]: (r["description"], r["when_to_use"] or "") for r in glossary_rows
    }
    counts = store.count_statements_by_kind_all(_db())
    all_kinds = sorted(set(counts) | set(glossary))
    return [
        {
            "kind": k,
            "description": glossary.get(k, ("", ""))[0],
            "when_to_use": glossary.get(k, ("", ""))[1],
            "usage_count": counts.get(k, 0),
        }
        for k in all_kinds
    ]


@tool
def list_entity_link_types() -> list[dict[str, Any]]:
    """List entity→entity link types known to the substrate.

    Returns `[{link_type, description, usage_count}]` sorted
    alphabetically. `description` comes from the
    `entity_link_type_glossary` table (DB-backed, editable via the
    website or `upsert_entity_link_type`). `usage_count` is the number
    of entity_links rows currently carrying this type.
    """
    counts = store.count_entity_links_by_type(_db())
    glossary = {
        r["link_type"]: r["description"]
        for r in store.list_entity_link_type_glossary(_db())
    }
    all_types = sorted(set(counts) | set(glossary))
    return [
        {
            "link_type": t,
            "type": t,
            "description": glossary.get(t, ""),
            "usage_count": counts.get(t, 0),
            "in_use": "true" if counts.get(t, 0) else "false",
        }
        for t in all_types
    ]


@tool
def upsert_statement_kind(
    kind: str, description: str, when_to_use: str | None = None
) -> dict[str, str]:
    """Create or update a statement-kind glossary entry.

    The `kind` value is the primary key — pass the same `kind` to
    update an existing entry's `description` / `when_to_use`. Pass a
    new `kind` to add a new entry. Authoring this entry does NOT
    register the kind for phrasing validation — phrasing rules live in
    `phrasing.py` and apply by name; an entry here is documentation,
    not enforcement.

    Returns `{kind}` on success.
    """
    if not kind or not kind.strip():
        raise ValueError("kind cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    with store.transaction(_db()):
        store.upsert_statement_kind_glossary(_db(), kind, description, when_to_use)
    return {"kind": kind}


@tool
def delete_statement_kind(kind: str) -> dict[str, str]:
    """Remove a statement-kind glossary entry.

    Does not affect any statement records that currently carry this
    kind — they remain valid in the substrate; only the glossary
    documentation goes away. Idempotent: deleting a missing entry is
    a no-op.

    Returns `{kind}`.
    """
    with store.transaction(_db()):
        store.delete_statement_kind_glossary(_db(), kind)
    return {"kind": kind}


@tool
def upsert_link_type(link_type: str, description: str) -> dict[str, str]:
    """Create or update a statement→statement link-type glossary entry.

    The `link_type` value is the primary key. Authoring this entry
    does NOT register the type for any validation; it is documentation
    that surfaces via `list_link_types`.

    Returns `{link_type}`.
    """
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    with store.transaction(_db()):
        store.upsert_statement_link_type_glossary(_db(), link_type, description)
    return {"link_type": link_type}


@tool
def delete_link_type(link_type: str) -> dict[str, str]:
    """Remove a statement→statement link-type glossary entry.

    Does not affect any link rows that currently carry this type —
    they remain valid in the substrate; only the documentation goes
    away. Idempotent.

    Returns `{link_type}`.
    """
    with store.transaction(_db()):
        store.delete_statement_link_type_glossary(_db(), link_type)
    return {"link_type": link_type}


#: Provenance values a caller may assert. `seed` is the migration's own tag and
#: is not assertable; a curator re-asserting an auto alias overwrites it, which
#: is how a reviewed alias stops being an automatic one.
ALIAS_PROVENANCE = ("curator", "auto", "auto:low-confidence")


@tool
def upsert_link_type_alias(
    link_type: str,
    alias: str,
    provenance: str = "curator",
    score: float | None = None,
    direction: str = "forward",
) -> dict[str, Any]:
    """Create or update an alternative phrasing for a canonical link type.

    The alias is vocabulary only: links still store the canonical
    `link_type`. The same alias may be registered under more than one type.

    `direction` says how the phrasing reads the edge: `forward` runs it left
    to right off the alias ("A contains B"), `reverse` names the relation
    from the far side ("A is part of B" puts B on the edge's source side).

    The alias set records where a phrasing came from: `curator` for a
    hand-authored one, or `auto`/`auto:low-confidence` with the deciding cosine
    for one an automatic resolver proposed; a later curator write overwrites
    both fields.

    Returns
    `{link_type, alias, provenance, score, direction, created}` with the
    normalized alias and whether this call created it.
    """
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not alias or not alias.strip():
        raise ValueError("alias cannot be empty")
    if provenance not in ALIAS_PROVENANCE:
        raise ValueError(
            f"provenance must be one of {', '.join(ALIAS_PROVENANCE)}: {provenance!r}"
        )
    if score is not None and not -1.0 <= float(score) <= 1.0:
        raise ValueError(f"score must be a cosine in [-1, 1]: {score!r}")
    # An automatic absorption with no score is invisible to the audit sweep the
    # provenance tag exists for.
    if provenance != "curator" and score is None:
        raise ValueError(f"provenance {provenance!r} requires a score")
    normalized = store.normalize_alias(alias)
    with store.transaction(_db()):
        created = store.upsert_link_type_alias(
            _db(),
            link_type,
            normalized,
            provenance=provenance,
            score=score,
            direction=direction,
        )
    return {
        "link_type": link_type,
        "alias": normalized,
        "provenance": provenance,
        "score": score,
        "direction": direction,
        "created": created,
    }


@tool
def delete_link_type_alias(link_type: str, alias: str) -> dict[str, Any]:
    """Delete one alternative phrasing from a canonical link type.

    Reach for this to retire vocabulary without changing links already stored
    under the canonical type. Idempotent. Returns `{link_type, alias, deleted}`
    with the normalized alias.
    """
    normalized = store.normalize_alias(alias)
    with store.transaction(_db()):
        deleted = store.delete_link_type_alias(_db(), link_type, normalized)
    return {"link_type": link_type, "alias": normalized, "deleted": deleted}


@tool
def list_link_type_aliases(
    link_type: str | None = None,
) -> list[dict[str, Any]]:
    """List link-type phrasings, optionally for one canonical link type.

    Reach for this to inspect accepted vocabulary. Returns
    `[{link_type, alias, provenance, score, direction}]`;
    hand-authored and seeded aliases have `score: null`.
    """
    return [
        {
            "link_type": row["link_type"],
            "alias": row["alias"],
            "provenance": row["provenance"],
            "score": row["score"],
            "direction": row["direction"],
        }
        for row in store.list_link_type_aliases(_db(), link_type)
    ]


@tool
def upsert_entity_link_type(link_type: str, description: str) -> dict[str, str]:
    """Create or update an entity→entity link-type glossary entry.

    The `link_type` value is the primary key. Entity link types live
    in a separate namespace from statement link types.

    Returns `{link_type}`.
    """
    if not link_type or not link_type.strip():
        raise ValueError("link_type cannot be empty")
    if not description or not description.strip():
        raise ValueError("description cannot be empty")
    with store.transaction(_db()):
        store.upsert_entity_link_type_glossary(_db(), link_type, description)
    return {"link_type": link_type}


@tool
def delete_entity_link_type(link_type: str) -> dict[str, str]:
    """Remove an entity→entity link-type glossary entry.

    Does not affect any entity_links rows that currently carry this
    type. Idempotent.

    Returns `{link_type}`.
    """
    with store.transaction(_db()):
        store.delete_entity_link_type_glossary(_db(), link_type)
    return {"link_type": link_type}
