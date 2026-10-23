"""Name operations: the aliases that let mentions resolve to an entity.

Every name carries its own vector in the name index and, when it has a
confident regular plural, a generated plural child. The helpers here keep both
in step with the name rows; the wrapping `_persisted_index_write` persists the
index once the operation's transaction commits.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

from pydantic import JsonValue

from .. import embed, mentions, plurals, store
from .indexes import _persisted_index_write
from .registry import draftable_tool, tool
from .runtime import _db, _name_idx


def _index_name(name_id: str, text: str) -> None:
    """Embed `text` and register its in-memory vector under `name_id`.

    The wrapping `_persisted_index_write` persists the index.
    """
    vid = store.next_name_vector_id(_db())
    vec = embed.embed(text)
    _name_idx().add(vid, vec)
    store.set_name_vector_id(_db(), name_id, vid)


def _reindex_name(name_id: str, new_text: str) -> None:
    """Replace an indexed name's in-memory vector.

    The wrapping `_persisted_index_write` persists the index.
    """
    vid = store.get_name_vector_id(_db(), name_id)
    vec = embed.embed(new_text)
    if vid is None:
        # Name exists in SQL but never got an index entry (e.g. created
        # before this feature existed and backfill missed it). Add fresh.
        vid = store.next_name_vector_id(_db())
        _name_idx().add(vid, vec)
        store.set_name_vector_id(_db(), name_id, vid)
    else:
        _name_idx().replace(vid, vec)


def _drop_name_from_index(name_id: str) -> None:
    """Remove a name's in-memory vector. Idempotent.

    The wrapping `_persisted_index_write` persists the index.
    """
    vid = store.get_name_vector_id(_db(), name_id)
    if vid is not None:
        _name_idx().delete(vid)
        store.delete_name_vector_mapping(_db(), name_id)


def _create_name_with_plural(text: str, entity_id: str) -> str:
    """Create a name, vector-index it, enqueue a recompute scan so existing
    statements containing it pick up the mention, and — per the auto-plural
    decision — also create its regular plural as a generated child (unless
    there's no confident plural or the text is already taken). Returns the
    primary name_id."""
    name_id = store.create_name(_db(), text, entity_id)
    _index_name(name_id, text)
    store.enqueue_recompute_scan(_db(), text)
    _generate_plural(name_id, text, entity_id)
    return name_id


def _generate_plural(source_name_id: str, text: str, entity_id: str) -> None:
    """Auto-create the regular plural of `text` as a generated child of
    `source_name_id`. No-op when there is no confident regular plural, or
    when the plural text is already taken (global UNIQUE — never steal
    another entity's name)."""
    plural = plurals.regular_plural(text)
    if plural is None or store.get_name_by_text(_db(), plural) is not None:
        return
    child_id = store.create_name(
        _db(), plural, entity_id, generated_from_name_id=source_name_id
    )
    _index_name(child_id, plural)
    store.enqueue_recompute_scan(_db(), plural)


def _delete_name_cascade(name_id: str) -> tuple[int, list[str]]:
    """Delete a name and any generated plurals it spawned: clear their
    mention / pending rows, drop their vectors, delete
    the rows. Children are deleted before the parent (the
    `generated_from_name_id` self-reference is RESTRICT). Returns
    `(mentions_removed, affected_statement_ids)` — the statements that
    mentioned a removed name must be recomputed, since the removed name may
    have been the representative for an entity another of whose names still
    matches."""
    children = store.get_generated_children(_db(), name_id)
    ids = [c["id"] for c in children] + [name_id]
    affected: list[str] = []
    mentions_removed = 0
    for nid in ids:
        affected.extend(store.statements_mentioning_name(_db(), nid))
        mentions_removed += store.delete_name_mentions(_db(), nid)
        _drop_name_from_index(nid)
        store.delete_name(_db(), nid)
    return mentions_removed, affected


def _regenerate_plurals(source_name_id: str, new_text: str) -> list[str]:
    """Regenerate stale plurals, preserving identities across casing corrections."""
    affected: list[str] = []
    plural = plurals.regular_plural(new_text)
    for child in store.get_generated_children(_db(), source_name_id):
        affected.extend(store.statements_mentioning_name(_db(), child["id"]))
        if plural is not None and child["text"].casefold() == plural.casefold():
            store.rename_name(_db(), child["id"], plural)
            _reindex_name(child["id"], plural)
            continue
        store.delete_name_mentions(_db(), child["id"])
        _drop_name_from_index(child["id"])
        store.delete_name(_db(), child["id"])
    src = store.get_name_by_id(_db(), source_name_id)
    if src is not None:
        _generate_plural(source_name_id, new_text, src["entity_id"])
    return affected


@tool
def get_mention_candidates(
    entity_id: str, after: int = 0, limit: int = 50
) -> dict[str, JsonValue]:
    """Find text matches across a concept's aliases, including ambiguous ones.

    Matches are labeled derived, approved, or possible. Possible matches are
    discovery evidence, never asserted relationships or graph edges. Follow
    next_after while has_more is true, even if a bounded scan returns no hits.
    Statement edits may change results between pages. Nothing is written.
    """
    from ..mention_candidates import find_candidates

    return find_candidates(_db(), entity_id, after=after, limit=limit).model_dump(
        mode="json"
    )


@draftable_tool
def upsert_name(text: str, entity_id: str) -> dict[str, str]:
    """Attach an alias `text` to an existing entity.

    Name texts are case-insensitive: "AIVY" and "Aivy" are the same
    name. Idempotent if the name (in any casing) already points at
    `entity_id`. Fails if `entity_id` is unknown, or if the text is
    already taken by a different entity (use `move_name` or
    `merge_entities` to resolve those cases).
    """
    if store.get_entity_by_id(_db(), entity_id) is None:
        raise ValueError(f"entity {entity_id!r} does not exist")
    existing = store.get_name_by_text(_db(), text)
    if existing is not None:
        if existing["entity_id"] == entity_id:
            return {"name_id": existing["id"]}
        raise ValueError(
            f"name {text!r} already belongs to entity {existing['entity_id']!r}; "
            "use move_name or merge_entities"
        )
    with _persisted_index_write(names=True):
        name_id = _create_name_with_plural(text, entity_id)
    return {"name_id": name_id}


@draftable_tool
def move_name(name_id: str, to_entity_id: str) -> dict[str, str]:
    """Reassign a single name to a different entity.

    The name's `text` is unchanged — only its `entity_id` binding moves.
    Because `statement_mentions` are keyed on `name_id` (not `entity_id`),
    every statement that mentioned this name continues to point at it,
    and now reports the new `entity_id` in its hydrated mentions.

    Combine with `upsert_entity` to split a name out into its own
    entity: create a fresh target entity first, then move the name onto
    it. The target's name must not case-fold to the name being moved —
    `upsert_entity` resolves names case-insensitively, so "Reviewer"
    would find the existing "reviewer" instead of creating a new entity;
    pick a distinct label (e.g. "Reviewer (actor)"). Names left behind
    on the source entity are untouched.

    Raises ValueError if `name_id` or `to_entity_id` does not exist.
    """
    if store.get_name_by_id(_db(), name_id) is None:
        raise ValueError(f"name {name_id!r} does not exist")
    if store.get_entity_by_id(_db(), to_entity_id) is None:
        raise ValueError(f"entity {to_entity_id!r} does not exist")
    # The name's entity binding changes, so the entity-grouping of every
    # statement mentioning it (or its generated plurals) may change —
    # recompute them. Generated children follow the name onto the new
    # entity so the plural stays attached to the same concept.
    with store.transaction(_db()):
        children = store.get_generated_children(_db(), name_id)
        affected = list(store.statements_mentioning_name(_db(), name_id))
        row = store.get_name_by_id(_db(), name_id)
        if row is not None and row["entity_id"] != to_entity_id:
            store.invalidate_name_decisions(
                _db(), name_id, "name_moved_to_different_concept"
            )
        store.set_name_entity(_db(), name_id, to_entity_id)
        for child in children:
            affected.extend(store.statements_mentioning_name(_db(), child["id"]))
            if child["entity_id"] != to_entity_id:
                store.invalidate_name_decisions(
                    _db(), child["id"], "name_moved_to_different_concept"
                )
            store.set_name_entity(_db(), child["id"], to_entity_id)
        store.enqueue_recompute_statements(_db(), affected)
    return {"name_id": name_id, "entity_id": to_entity_id}


@draftable_tool
def rename_name(name_id: str, new_text: str) -> dict[str, str]:
    """Correct a name's spelling while keeping its id and concept binding.

    The old spelling stops matching. Statement text stays unchanged, and
    discovery is recomputed for both the old and new spellings. Historical
    occurrence approvals are invalidated when the spelling changes meaning.

    To adopt a new preferred display name while preserving old references,
    add the new alias and select it in Names & aliases instead.
    """
    # Statements mentioning this name may now match differently (their text
    # still contains the OLD label, which is no longer a name) — recompute
    # them. Regenerate the name's plural from the new text. Scan for the new
    # text so statements containing it pick up the mention.
    with _persisted_index_write(names=True):
        affected = list(store.statements_mentioning_name(_db(), name_id))
        old = store.get_name_by_id(_db(), name_id)
        if old is not None and old["text"].casefold() != new_text.casefold():
            store.invalidate_name_decisions(
                _db(), name_id, "name_spelling_corrected", clear_all_mentions=True
            )
            for child in store.get_generated_children(_db(), name_id):
                affected.extend(store.statements_mentioning_name(_db(), child["id"]))
                store.invalidate_name_decisions(
                    _db(),
                    child["id"],
                    "source_name_spelling_corrected",
                    clear_all_mentions=True,
                )
        store.rename_name(_db(), name_id, new_text)
        _reindex_name(name_id, new_text)
        affected.extend(_regenerate_plurals(name_id, new_text))
        store.enqueue_recompute_statements(_db(), affected)
        store.enqueue_recompute_scan(_db(), new_text)
    return {"name_id": name_id, "text": new_text}


@draftable_tool
def delete_name(name_id: str) -> dict[str, Any]:
    """Delete a single name (alias) from its entity.

    Cascade: every `statement_mentions` row that referenced this name is
    removed — those mentions disappear (the statements themselves stay,
    but lose this particular alias-mention). The owning entity is
    unaffected and may end up with zero remaining names; that's allowed.

    Use case: an alias was wrong (typo, slang the team stopped using,
    accidentally attached) and should not survive. To move a name onto a
    different entity instead, use `move_name`. To collapse two entities
    into one, use `merge_entities`.

    Returns `{deleted, mentions_removed}`.
    Raises ValueError on unknown id.
    """
    if store.get_name_by_id(_db(), name_id) is None:
        raise ValueError(f"name {name_id!r} does not exist")
    # Cascade through the name and any generated plurals, then recompute the
    # statements that mentioned them — a removed name may have been the
    # representative for an entity another of whose names still matches.
    with _persisted_index_write(names=True):
        mentions_removed, affected = _delete_name_cascade(name_id)
        store.enqueue_recompute_statements(_db(), affected)
    return {
        "deleted": True,
        "mentions_removed": mentions_removed,
    }


@tool
def find_entity_duplicates(
    threshold: float = 0.9,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Audit entity names for likely duplicate entities.

    Two passes over every name in the substrate, both reporting only
    pairs whose names point at DIFFERENT entities (multiple aliases on
    one entity are fine):

    - `"fold"`: the names collapse to the same token sequence under the
      mention matcher's normalization (casefold + NFKC + dash/quote
      folding) — e.g. "answer type" vs "Answer-Type". Near-certain
      duplicates, reported with score 1.0.
    - `"embedding"`: the names' vectors on the name index have cosine
      similarity at or above `threshold` — catches variants the fold
      can't, like "Checklist" vs "Check List Item" or conceptual twins.

    The statement-level counterpart is `find_duplicates`; this covers
    the entity layer it skips.

    Each pair: `{a_entity_id, a_name, b_entity_id, b_name, score, via}`,
    sorted by score descending, capped at `limit`. Resolve with
    `merge_entities` (same concept) or `move_name` / `delete_name` (an
    alias sits on the wrong entity).
    """
    names = store.list_all_names(_db())
    by_id = {r["id"]: r for r in names}
    seen_pairs: set[tuple[str, str]] = set()
    pairs: list[dict[str, Any]] = []

    def _add(a_name_id: str, b_name_id: str, score: float, via: str) -> None:
        a, b = by_id[a_name_id], by_id[b_name_id]
        if a["entity_id"] == b["entity_id"]:
            return
        key = (
            (a_name_id, b_name_id) if a_name_id < b_name_id else (b_name_id, a_name_id)
        )
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        pairs.append(
            {
                "a_entity_id": a["entity_id"],
                "a_name": a["text"],
                "b_entity_id": b["entity_id"],
                "b_name": b["text"],
                "score": score,
                "via": via,
            }
        )

    for group in _fold_collision_groups(names):
        for i, a_name_id in enumerate(group):
            for b_name_id in group[i + 1 :]:
                _add(a_name_id, b_name_id, 1.0, "fold")

    for row in names:
        for other_name_id, score in _name_embedding_neighbours(row["id"], threshold):
            if other_name_id in by_id:
                _add(row["id"], other_name_id, score, "embedding")

    pairs.sort(key=lambda p: p["score"], reverse=True)
    return pairs[:limit]


def _fold_collision_groups(names: list[sqlite3.Row]) -> list[list[str]]:
    """Groups of name_ids whose texts collapse to the same token sequence
    under the mention matcher's fold."""
    folds: dict[tuple[str, ...], list[str]] = {}
    for row in names:
        toks = mentions.name_tokens(row["text"])
        if toks:
            folds.setdefault(toks, []).append(row["id"])
    return [group for group in folds.values() if len(group) > 1]


def _name_embedding_neighbours(
    name_id: str, threshold: float
) -> Iterator[tuple[str, float]]:
    """Yield `(other_name_id, score)` for names whose vectors sit at or
    above `threshold` cosine similarity to `name_id`'s."""
    vid = store.get_name_vector_id(_db(), name_id)
    if vid is None:
        return
    vec = _name_idx().get_vector(vid)
    if vec is None:
        # Slot is stranded — SQLite mapping points at an id the
        # hnsw file doesn't have. Skip rather than crash the audit.
        return
    # Same k tradeoff as find_duplicates: wide enough to cover any
    # realistic cluster of variants at MVP scale.
    for other_vid, distance in _name_idx().search(vec, k=10):
        if other_vid == vid:
            continue
        score = 1.0 - distance
        if score < threshold:
            continue
        other_name_id = store.get_name_id_by_vector_id(_db(), other_vid)
        if other_name_id is not None:
            yield other_name_id, score
