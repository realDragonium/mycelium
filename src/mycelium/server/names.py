"""Name operations: the aliases that let mentions resolve to an entity.

Every name carries its own vector in the name index and, when it has a
confident regular plural, a generated plural child. The helpers here keep both
in step with the name rows; the wrapping `_persisted_index_write` persists the
index once the operation's transaction commits.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator
from itertools import pairwise
from typing import Any, Literal, TypedDict

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


Via = Literal["fold", "same_words", "initials", "embedding"]
_LEXICAL_SCORES: dict[Via, float] = {"fold": 1.0, "same_words": 0.95, "initials": 0.9}


class DuplicateMatch(TypedDict):
    a_name: str
    b_name: str
    via: Via
    score: float


class DuplicateCandidate(TypedDict):
    a_entity_id: str
    b_entity_id: str
    score: float
    matches: list[DuplicateMatch]


class DuplicatePage(TypedDict):
    candidates: list[DuplicateCandidate]
    total: int


@tool
def find_entity_duplicates(
    threshold: float = 0.75,
    limit: int = 50,
    offset: int = 0,
) -> DuplicatePage:
    """Audit entity names for likely duplicate entities.

    Compares names that point at DIFFERENT entities (multiple aliases on
    one entity are fine). Names are split into words on spaces,
    punctuation, `_`, `-` and camelCase, so `only_admin_exports` and
    "Only Admin Exports" have the same words. Four passes:

    - `"fold"`: the names collapse to the same token sequence under the
      mention matcher's normalization (casefold + NFKC + dash/quote
      folding) — e.g. "answer type" vs "Answer-Type". Score 1.0.
    - `"same_words"`: the same words in another order or spelling style —
      e.g. "Only Admin Exports" vs "Admin Only Exports". Score 0.95.
    - `"initials"`: a one-word name spells the initials of a longer one —
      e.g. "SSO" vs "Single sign-on". Score 0.9.
    - `"embedding"`: the names' vectors on the name index have cosine
      similarity at or above `threshold`, unless the words show the names
      are related but distinct: one name's words contain the other's
      ("Login" vs "Login page"); one word takes another's place, as the
      only difference or right after a shared word ("invoice_template_v1"
      vs "invoice_template_v2", "Sign-in page" vs "Sign-up"); or each adds
      its own words to a shared stem of two or more words, or of words common to
      3% of names. A word that abbreviates the other ("admin" vs
      "administrator") does not count as a swap.

    Generated plurals take part only in the fold pass. The statement-level
    counterpart is `find_duplicates`; this covers the entity layer it skips.

    Returns `{candidates, total}`: one candidate per entity pair,
    `{a_entity_id, b_entity_id, score, matches}`, where `matches` lists each
    name pair that matched (`{a_name, b_name, via, score}`) and `score` is
    the strongest. Candidates with a word match rank above embedding-only
    ones, then by score. `total` counts every candidate; page with `offset`
    and `limit`. Pairs a curator dismissed as not duplicates in Names &
    aliases are left out. Resolve with `merge_entities` (same concept) or
    `move_name` / `delete_name` (an alias sits on the wrong entity).
    """
    names = store.list_all_names(_db())
    by_id = {r["id"]: r for r in names}
    seen_name_pairs: set[frozenset[str]] = set()
    candidates: dict[tuple[str, str], DuplicateCandidate] = {}
    for a_name_id, b_name_id, via, score in _name_matches(names, threshold):
        a, b = by_id[a_name_id], by_id[b_name_id]
        name_pair = frozenset((a_name_id, b_name_id))
        if a["entity_id"] == b["entity_id"] or name_pair in seen_name_pairs:
            continue
        seen_name_pairs.add(name_pair)
        if a["entity_id"] > b["entity_id"]:
            a, b = b, a
        candidate = candidates.setdefault(
            (a["entity_id"], b["entity_id"]),
            {
                "a_entity_id": a["entity_id"],
                "b_entity_id": b["entity_id"],
                "score": score,
                "matches": [],
            },
        )
        candidate["score"] = max(candidate["score"], score)
        candidate["matches"].append(
            {"a_name": a["text"], "b_name": b["text"], "via": via, "score": score}
        )

    dismissed = store.dismissed_entity_duplicates(_db())
    ranked = sorted(
        (c for key, c in candidates.items() if key not in dismissed),
        key=lambda c: (
            any(m["via"] != "embedding" for m in c["matches"]),
            c["score"],
        ),
        reverse=True,
    )
    return {"candidates": ranked[offset : offset + limit], "total": len(ranked)}


def _name_matches(
    names: list[sqlite3.Row], threshold: float
) -> Iterator[tuple[str, str, Via, float]]:
    """Every name pair any pass matches, strongest pass first."""
    by_id = {r["id"]: r for r in names}
    readings = {r["id"]: _readings(r["text"]) for r in names}
    words = {name_id: split for name_id, (split, _) in readings.items()}
    authored = [r["id"] for r in names if r["generated_from_name_id"] is None]

    for a_name_id, b_name_id in _pairs_within(_fold_collision_groups(names)):
        yield a_name_id, b_name_id, "fold", _LEXICAL_SCORES["fold"]

    by_words: dict[frozenset[str], list[str]] = {}
    for name_id in authored:
        for key in {frozenset(reading) for reading in readings[name_id]}:
            by_words.setdefault(key, []).append(name_id)
    for a_name_id, b_name_id in _pairs_within(by_words.values()):
        yield a_name_id, b_name_id, "same_words", _LEXICAL_SCORES["same_words"]

    by_initials: dict[str, list[str]] = {}
    for name_id in authored:
        if len(words[name_id]) > 1:
            initials = "".join(w[0] for w in words[name_id])
            by_initials.setdefault(initials, []).append(name_id)
    for name_id in authored:
        if len(words[name_id]) == 1:
            for other_name_id in by_initials.get(words[name_id][0], []):
                yield name_id, other_name_id, "initials", _LEXICAL_SCORES["initials"]

    family = _family_words([readings[name_id] for name_id in authored])
    for name_id in authored:
        for other_name_id, score in _name_embedding_neighbours(name_id, threshold):
            other = by_id.get(other_name_id)
            if other is None or other["generated_from_name_id"] is not None:
                continue
            if not any(
                _related_but_distinct(a, b, family)
                for a, b in zip(readings[name_id], readings[other_name_id], strict=True)
            ):
                yield name_id, other_name_id, "embedding", score


def _pairs_within(groups: Iterable[list[str]]) -> Iterator[tuple[str, str]]:
    for group in groups:
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                yield first, second


def _readings(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The words of a name with camelCase split, and with it kept whole:
    "GitHub_exports" reads as `("git", "hub", "export")` and
    `("github", "export")`, so it compares with both `gitHubExport` and
    `github_export`."""
    return _words(_CAMEL_BOUNDARY.sub(" ", text)), _words(text)


def _words(text: str) -> tuple[str, ...]:
    """Lower-case singular words, split on spaces, punctuation and `_`."""
    found = _WORD.findall(unicodedata.normalize("NFKC", text).casefold())
    return tuple(
        w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        for w in found
    )


def _family_words(
    names: list[tuple[tuple[str, ...], tuple[str, ...]]],
) -> frozenset[str]:
    """Words so common they mark a family of names, not a concept: the
    `notify_` of a hundred notification identifiers."""
    counts = Counter(word for split, whole in names for word in {*split, *whole})
    floor = max(10, 0.03 * len(names))
    return frozenset(word for word, count in counts.items() if count >= floor)


_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+")


def _related_but_distinct(
    a: tuple[str, ...], b: tuple[str, ...], family: frozenset[str]
) -> bool:
    """Whether the words mark two similar-looking names as different concepts.

    Names in one family embed closer to each other than many true
    duplicates do ("Sign-in page" vs "Sign-up" at 0.80, "Login page" vs
    "Sign-in page" at 0.83), so the embedding pass cannot tell them apart.
    A name extending the other is a narrower concept. Names are siblings
    when one distinguishing word takes the place of another: as their only
    difference ("Monthly plan" vs "Annual plan"), or right after a word
    they share ("Sign-in page" vs "Sign-up", "export_batch_i_size" vs
    "export_batch_ii_size"), unless one word abbreviates the other
    ("admin" vs "administrator"). So are names that each add their own words to a stem
    of two or more words ("login_rate_window_report" vs
    "login_rate_burst_cap_report") or of family words only
    ("notify_invoice_paid" vs "notify_export_ready")."""
    shared = set(a) & set(b)
    only_a, only_b = set(a) - shared, set(b) - shared
    if not only_a or not only_b:
        return bool(only_a or only_b)
    if len(only_a) == 1 and len(only_b) == 1:
        return not _abbreviates(*only_a, *only_b)
    after_a = {
        (word, next_word) for word, next_word in pairwise(a) if next_word in only_a
    }
    after_b = {
        (word, next_word) for word, next_word in pairwise(b) if next_word in only_b
    }
    if any(
        word_a == word_b and not _abbreviates(next_a, next_b)
        for word_a, next_a in after_a
        for word_b, next_b in after_b
    ):
        return True
    return len(shared) >= 2 or (bool(shared) and shared <= family)


def _abbreviates(word_a: str, word_b: str) -> bool:
    short, long = sorted((word_a, word_b), key=len)
    return len(short) >= 3 and long.startswith(short)


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
    # Families of sibling identifiers ("invoice_template_v1", "_v2", ...)
    # fill the nearest slots and are dropped later; look past them.
    for other_vid, distance in _name_idx().search(vec, k=30):
        if other_vid == vid:
            continue
        score = 1.0 - distance
        if score < threshold:
            continue
        other_name_id = store.get_name_id_by_vector_id(_db(), other_vid)
        if other_name_id is not None:
            yield other_name_id, score
