"""Entity operations: the long-lived referents that names point at.

Entities are read through their names — `search_entities` searches the name
index, `get_entity` returns an entity with its names and entity links — so
creating or deleting one also creates or drops name vectors. Entity links are a
separate, structural vocabulary from statement links, and the entity layout is
rebaked whenever they change.
"""

from __future__ import annotations

from typing import Any, TypedDict

from .. import docs_store, embed, store
from .indexes import _persisted_index_write
from .names import _create_name_with_plural, _drop_name_from_index
from .registry import draft_listing_tool, draftable_tool, tool
from .runtime import _baker, _db, _drafts_db, _name_idx
from .specs import EntityEdgeSpec, ResultLimit, _check_limit


@draftable_tool
def upsert_entity(name: str, description: str) -> dict[str, str]:
    """Create or update an entity by name.

    If a name with this text already exists — the match is
    case-insensitive, so "AIVY" resolves to an existing "Aivy" — updates
    that entity's description and returns its id. Otherwise creates a
    new entity AND a name pointing at it.
    """
    existing = store.get_name_by_text(_db(), name)
    with _persisted_index_write(names=existing is None):
        if existing is not None:
            store.update_entity_description(_db(), existing["entity_id"], description)
            return {"entity_id": existing["entity_id"]}
        entity_id = store.create_entity(_db(), description)
        _create_name_with_plural(name, entity_id)
    _baker().schedule_rebake()
    return {"entity_id": entity_id}


class EntityMerge(TypedDict):
    into_entity_id: str
    names_moved: int
    documents_unanchored: int


class EntityDeletion(TypedDict):
    deleted: bool
    names_removed: int
    mentions_removed: int
    outgoing_entity_links_removed: int
    incoming_entity_links_removed: int
    documents_unanchored: int


@draftable_tool
def merge_entities(from_entity_id: str, into_entity_id: str) -> EntityMerge:
    """Move every name from `from_entity_id` to `into_entity_id` and delete
    the source entity. Statements that mentioned the moved names continue
    to point at the same names (now under the new entity). Generated
    documents anchored to the source become anchored to the target; where
    the target already anchors a document of the same guideline set and
    type, the source's document keeps its body but loses its anchor;
    `documents_unanchored` counts those. A documentation run still in flight
    for the source writes under the anchor its document would now have."""
    if from_entity_id == into_entity_id:
        return {
            "into_entity_id": into_entity_id,
            "names_moved": 0,
            "documents_unanchored": 0,
        }
    if store.get_entity_by_id(_db(), from_entity_id) is None:
        raise ValueError(f"entity {from_entity_id!r} does not exist")
    if store.get_entity_by_id(_db(), into_entity_id) is None:
        raise ValueError(f"entity {into_entity_id!r} does not exist")
    # Names move from source to target, so the entity-grouping of every
    # statement mentioning them changes — recompute those statements.
    with store.transaction(_db()):
        moved_name_ids = [
            r["id"] for r in store.get_names_by_entity(_db(), from_entity_id)
        ]
        moved = store.reassign_names(_db(), from_entity_id, into_entity_id)
        # Rewrite any entity_links referencing the source — outgoing rows
        # become outgoing on the target, incoming rows become incoming on
        # the target, and self-loops the merge would create are dropped.
        # Required before deleting the source: FK enforcement otherwise
        # blocks the delete.
        store.rewrite_entity_link_endpoints(_db(), from_entity_id, into_entity_id)
        store.delete_entity(_db(), from_entity_id)
        affected: list[str] = []
        for nid in moved_name_ids:
            affected.extend(store.statements_mentioning_name(_db(), nid))
        store.enqueue_recompute_statements(_db(), affected)
        # Anchors live in the drafts DB, so this commits first: a failed
        # substrate commit then leaves anchors on the surviving target, never
        # on a deleted source.
        with store.transaction(_drafts_db()):
            unanchored = docs_store.move_anchors(
                _drafts_db(), from_entity_id, into_entity_id
            )
    return {
        "into_entity_id": into_entity_id,
        "names_moved": moved,
        "documents_unanchored": unanchored,
    }


@draftable_tool
def delete_entity(id: str) -> EntityDeletion:
    """Permanently delete an entity along with all its names.

    Use case: the entity no longer exists in the product (component
    removed, concept retired) and there's no successor to merge into.
    For "this entity is the same as that one", use `merge_entities`
    instead so statements migrate.

    Cascade statement:
    - Every `name` attached to this entity is deleted.
    - `statement_mentions` referencing any of those names are removed.
    - `entity_links` from or to this entity are removed.
    - Generated documents anchored to it lose the anchor but keep their
      body and history; a documentation run still in flight for it writes
      unanchored.
    - The entity record is dropped.

    Returns counts of cascaded rows so the caller can sanity-check the
    blast radius. Permanent. Raises ValueError on unknown id.
    """
    if store.get_entity_by_id(_db(), id) is None:
        raise ValueError(f"entity {id!r} does not exist")

    with _persisted_index_write(names=True):
        name_rows = store.get_names_by_entity(_db(), id)
        name_ids = [r["id"] for r in name_rows]
        affected: list[str] = []
        mentions_removed = 0
        for nid in name_ids:
            # Statements that mentioned this entity may now match a name they
            # were shadowing (e.g. "data" surfacing once "data science" is gone).
            affected.extend(store.statements_mentioning_name(_db(), nid))
            mentions_removed += store.delete_name_mentions(_db(), nid)
            _drop_name_from_index(nid)
        # Break generated-plural self-references within this entity before the
        # bulk delete (generated_from_name_id REFERENCES names(id)).
        store.delete_names_clearing_generated_refs(_db(), name_ids)
        outgoing_entity_links_removed, incoming_entity_links_removed = (
            store.delete_entity_links_touching(_db(), id)
        )
        store.delete_entity(_db(), id)
        store.enqueue_recompute_statements(_db(), affected)
        # Committed before the substrate, as in merge_entities: a failed
        # substrate commit leaves a live entity without anchors, never a
        # deleted one still holding them.
        with store.transaction(_drafts_db()):
            unanchored = docs_store.clear_anchors(_drafts_db(), id)
    _baker().schedule_rebake()
    return {
        "deleted": True,
        "names_removed": len(name_ids),
        "mentions_removed": mentions_removed,
        "outgoing_entity_links_removed": outgoing_entity_links_removed,
        "incoming_entity_links_removed": incoming_entity_links_removed,
        "documents_unanchored": unanchored,
    }


@tool
def get_entity(id: str) -> dict[str, Any]:
    """Fetch one entity by its id, hydrated with names and entity links.

    Returns `{id, description, names, links, incoming_links}`:

    - `names` is `[{id, text}]`, preferred name first, then alphabetical aliases.
    - `links` / `incoming_links` are the entity↔entity edges
      (`[{to_entity_id|from_entity_id, link_type}]`). Separate
      vocabulary from statement links; see `list_entity_link_types`.

    Use `search_statements` with the `mentions` filter to find
    statements that mention this entity by name.

    Also returns `missing` — always present, empty when the entity resolved,
    and `[id]` when no entity carries that id. In that case it is the only
    key besides `id`: there is no entity to describe, and returning empty
    `names`/`links` would read as "exists but is bare".
    """
    row = store.get_entity_by_id(_db(), id)
    if row is None:
        return {"id": id, "missing": [id]}
    outgoing = store.get_entity_links_outgoing(_db(), id)
    incoming = store.get_entity_links_incoming(_db(), id)
    return {
        "id": row["id"],
        "missing": [],
        "description": row["description"] or "",
        "preferred_name_id": row["preferred_name_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "names": [
            {"id": n["id"], "text": n["text"]}
            for n in store.get_names_by_entity(_db(), id)
        ],
        "links": [{"to_entity_id": to_id, "link_type": lt} for (to_id, lt) in outgoing],
        "incoming_links": [
            {"from_entity_id": from_id, "link_type": lt} for (from_id, lt) in incoming
        ],
    }


@draft_listing_tool
def list_entities(
    prefix: str = "",
    limit: ResultLimit = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Page through entities, sorted by their alphabetically-first name.

    Optional `prefix` does a case-insensitive prefix match against EVERY
    name attached to an entity — aliases included, so `prefix="Aivy"`
    finds the entity even when "Aivy" is an alias and the primary name
    is something else. Pass empty string for no filter. Returns
    `{total, entities: [{id, name, description}]}` where `total` counts
    the entities matching the filter, so a caller can drive pagination.

    `name` is the entity's alphabetically-first attached name, or the
    entity_id as a fallback if it has no names. To enumerate all aliases
    of one entity, use `get_entity(id)`. For conceptual (non-literal)
    lookup, use `search_entities`. `limit` is at most 100.
    """
    _check_limit(limit)
    rows = store.list_entities(_db(), prefix=prefix or None, limit=limit, offset=offset)
    return {
        "total": store.count_entities(_db(), prefix=prefix or None),
        "entities": [
            {
                "id": r["id"],
                "name": r["primary_name"] or r["id"],
                "description": r["description"] or "",
            }
            for r in rows
        ],
    }


@tool
def search_entities(
    query: str,
    k: int = 10,
    min_score: float = 0.3,
) -> dict[str, Any]:
    """Semantic search over entity names and aliases.

    Embeds `query` and searches the name vector index (the same index
    that powers `search_statements`' name_boost), so conceptual queries
    work — "assessment part" can find an entity named "Test" — where
    `list_entities(prefix=…)` only matches literal prefixes.

    Names scoring at or above `min_score` are resolved to their
    entities; each entity is reported once, under its best-scoring
    name. Returns `{entities: [{id, name, matched_name, score,
    description}]}` sorted by score descending, capped at `k`. `name`
    is the entity's preferred name, with an alphabetical fallback (as in
    `list_entities`); `matched_name` is the alias that actually
    matched. Follow up with `get_entity(id)` for all aliases.
    """
    if not query:
        raise ValueError("query must be a non-empty string")
    vec = embed.embed(query)
    # Over-fetch: several aliases of one entity can occupy top slots,
    # and dedup-to-entity may otherwise leave fewer than k results.
    best: dict[str, tuple[float, str]] = {}
    for vid, distance in _name_idx().search(vec, k=max(k * 3, 20)):
        score = 1.0 - distance
        if score < min_score:
            continue
        nid = store.get_name_id_by_vector_id(_db(), vid)
        if nid is None:
            continue
        name_row = store.get_name_by_id(_db(), nid)
        if name_row is None:
            continue
        eid = name_row["entity_id"]
        if eid not in best or score > best[eid][0]:
            best[eid] = (score, name_row["text"])
    ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)[:k]
    entities: list[dict[str, Any]] = []
    for eid, (score, matched_name) in ranked:
        entity = store.get_entity_by_id(_db(), eid)
        if entity is None:
            continue
        names = store.get_names_by_entity(_db(), eid)
        entities.append(
            {
                "id": eid,
                "name": names[0]["text"] if names else eid,
                "matched_name": matched_name,
                "score": score,
                "description": entity["description"] or "",
            }
        )
    return {"entities": entities}


@draftable_tool
def add_entity_links(links: list[EntityEdgeSpec]) -> dict[str, int]:
    """Bulk-insert directed entity→entity edges.

    Use case: structural relationships between long-lived entities — a
    parent corporation `contains` its subsidiaries, a product is a
    `kind-of` something more abstract, two providers `replace` each
    other, etc. These are distinct from statement→statement links
    (`add_links`), which connect atomic facts; entity_links connect
    the hubs that statements mention.

    Each link is `{from_entity_id, to_entity_id, link_type}`. The
    `link_type` vocabulary is open — any string is valid; reuse what
    `list_entity_link_types()` already shows in use before inventing.

    Self-loops (`from == to`) are rejected. Pre-existing edges (matched
    on the triple) are silently skipped via INSERT OR IGNORE, so the
    returned `inserted` count can be less than `len(links)`.

    Validates every referenced entity id exists before any mutation;
    if any reference is unknown the call raises ValueError and inserts
    nothing.
    """
    if not links:
        return {"inserted": 0}
    needed: set[str] = set()
    for link in links:
        if link["from_entity_id"] == link["to_entity_id"]:
            raise ValueError(
                f"self-loop entity link: {link['from_entity_id']!r} → itself"
            )
        needed.add(link["from_entity_id"])
        needed.add(link["to_entity_id"])
    for eid in needed:
        if store.get_entity_by_id(_db(), eid) is None:
            raise ValueError(f"entity {eid!r} does not exist")
    edges = [
        (link["from_entity_id"], link["to_entity_id"], link["link_type"])
        for link in links
    ]
    with store.transaction(_db()):
        inserted = store.insert_entity_links(_db(), edges)
    if inserted:
        _baker().schedule_rebake()
    return {"inserted": inserted}


@draftable_tool
def remove_entity_links(links: list[EntityEdgeSpec]) -> dict[str, int]:
    """Bulk-delete directed entity→entity edges.

    Each link is `{from_entity_id, to_entity_id, link_type}` and must
    match an existing edge exactly. Missing edges are a no-op (idempotent
    — calling twice with the same input is fine). Returns the count of
    rows actually deleted. Does not validate that referenced entities
    exist; deleting an edge that references a non-existent entity simply
    removes nothing.
    """
    if not links:
        return {"removed": 0}
    edges = [
        (link["from_entity_id"], link["to_entity_id"], link["link_type"])
        for link in links
    ]
    with store.transaction(_db()):
        removed = store.delete_entity_links(_db(), edges)
    if removed:
        _baker().schedule_rebake()
    return {"removed": removed}
