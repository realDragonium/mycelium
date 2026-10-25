"""The curation work queue: knowledge-health items handed to outside agents.

An agent working in the product's code can tell whether two statements really
relate; the server cannot. So the agent claims a batch of items, checks each
one in the code, proposes what it found through a draft, and releases the
items with the outcome. A claim leases an item for `LEASE`, renewed by the
holder's next claim; an expired claim frees it. A release is remembered in
`curation_attempts`, the memory the connect pass shares, so an item is not
offered again until it or the statements around it change.

A question the draft reviewer asked a person is an item too: an agent with
a curator's role answers it with evidence, and the draft is reviewed again.
An agent with that role may also close the gaps it settled, as a person
would.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, get_args

from pydantic import BaseModel, TypeAdapter

from . import (
    automation_stops,
    draft_review_store,
    knowledge_health,
    store,
    timestamps,
)
from .store.gaps import set_knowledge_gap_status

Kind = Literal[
    "isolated",
    "unnamed",
    "rephrase",
    "gap",
    "question",
    "duplicate",
    "undescribed",
    "unused",
]
Outcome = Literal[
    "proposed", "no_link", "skipped", "answered", "resolved", "not_applicable"
]
KINDS: tuple[Kind, ...] = get_args(Kind)
#: The outcomes each kind may be released with.
OUTCOMES: dict[Kind, frozenset[Outcome]] = {
    "isolated": frozenset({"proposed", "no_link", "skipped"}),
    "unnamed": frozenset({"proposed", "no_link", "skipped"}),
    "rephrase": frozenset(
        {"proposed", "no_link", "skipped", "resolved", "not_applicable"}
    ),
    "gap": frozenset({"proposed", "no_link", "skipped", "resolved", "not_applicable"}),
    "question": frozenset({"answered", "skipped"}),
    "duplicate": frozenset({"proposed", "not_applicable", "skipped"}),
    "undescribed": frozenset({"proposed", "no_link", "skipped"}),
    "unused": frozenset({"proposed", "no_link", "skipped"}),
}
LEASE = timedelta(minutes=30)
MAX_BATCH = 20

_STATEMENT_KINDS: dict[Kind, knowledge_health.StatementFilter] = {
    "isolated": "isolated",
    "unnamed": "unmentioned",
}
_OPEN_GAP = "g.resolved_at IS NULL AND g.dismissed_at IS NULL"
_REPHRASE_GAP = (
    "(g.statement_id IS NOT NULL AND substr(g.text, 1, :prefix_len) = :prefix)"
)
#: The newest open gap about a draft whose reviewer waits for a person's
#: answer (`:waiting`, a JSON list of draft ids): the one asking the
#: questions that hold it.
_QUESTION_GAP = (
    "g.draft_id IN (SELECT value FROM json_each(:waiting)) AND g.id = "
    "(SELECT h.id FROM knowledge_gaps h WHERE h.draft_id = g.draft_id "
    "AND h.resolved_at IS NULL AND h.dismissed_at IS NULL "
    "ORDER BY h.created_at DESC, h.id DESC LIMIT 1)"
)
_GAP_WHERE: dict[Kind, str] = {
    "rephrase": f"{_OPEN_GAP} AND {_REPHRASE_GAP}",
    "gap": f"{_OPEN_GAP} AND NOT {_REPHRASE_GAP}",
    "question": f"{_OPEN_GAP} AND {_QUESTION_GAP}",
}
#: An attempt still holds for gap `g`: not skipped, the gap's text unchanged
#: and the statement it is about not written since.
# Listed gaps are open, so a gap an agent resolved or dismissed is open again
# only because a person reopened it; that look no longer settles it.
_GAP_SETTLED = (
    "EXISTS (SELECT 1 FROM curation_attempts c WHERE c.item_id = g.id "
    "AND c.outcome NOT IN ('skipped', 'resolved', 'not_applicable') "
    "AND c.text = g.text "
    "AND NOT EXISTS (SELECT 1 FROM statements st WHERE st.id = g.statement_id "
    "AND COALESCE(st.updated_at, st.created_at, '') > c.attempted_at))"
)
_GAP_CLAIMED = knowledge_health.CLAIMED.replace("s.id", "g.id")
_CHUNK = 200
_answers = TypeAdapter(list[draft_review_store.Answer])
_CONCEPT_KINDS: dict[Kind, knowledge_health.EntityFilter] = {
    "undescribed": "undescribed",
    "unused": "unused",
}


class Concept(BaseModel):
    id: str
    name: str


class Subject(BaseModel):
    """The statement an item is about."""

    id: str
    kind: str
    text: str
    #: The concepts its text names.
    concepts: list[Concept]


@dataclass(frozen=True)
class Candidate:
    #: A statement id, or a knowledge gap id.
    id: str
    #: The statement's text, or the gap's.
    text: str
    statement: Subject | None


@dataclass(frozen=True)
class DuplicateCandidate:
    """An index-backed duplicate pair handed to the queue by the server."""

    id: str
    text: str


class Holder(BaseModel):
    claimed_by: str
    items: int
    expires_at: str


class Summary(BaseModel):
    kind: Kind
    #: Who holds items of this kind, and how many.
    claims: list[Holder]
    #: Items still on the list that someone has looked at.
    attempted: int
    #: How many of those ended each way; `looked` is the connect pass.
    outcomes: dict[str, int]


def _params(now: str, waiting: Sequence[str] = ()) -> dict[str, object]:
    prefix = knowledge_health.REPHRASE_GAP_PREFIX
    return {
        "now": now,
        "prefix": prefix,
        "prefix_len": len(prefix),
        "waiting": json.dumps(list(waiting)),
    }


def waiting_for_answer(
    drafts: sqlite3.Connection, answer_retries: int | None = None
) -> list[str]:
    """Submitted drafts whose latest review asked a person and that have not
    changed since. With `answer_retries`, not those whose reviewer already
    asked again more often after automatic answers: a person answers them."""
    return [
        str(row["id"])
        for row in drafts.execute(
            "SELECT id, json_extract(review_assessment_json, '$.answers') AS answers "
            "FROM drafts WHERE submitted_at IS NOT NULL "
            "AND decided_at IS NULL "
            "AND json_extract(review_assessment_json, '$.application') = 'needs_human' "
            "AND json_extract(review_assessment_json, '$.draft_revision') = revision "
            "ORDER BY id"
        )
        if answer_retries is None
        or draft_review_store.automatic_answers(
            _answers.validate_json(row["answers"] or "[]")
        )
        <= answer_retries
    ]


def claim(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    kind: Kind,
    *,
    limit: int,
    claimant: str,
    now: datetime,
    pairs: Sequence[DuplicateCandidate] = (),
    exclude_skipped_by: str | None = None,
    draft_gaps_only: bool = False,
    follow_up_retries: int | None = None,
    answer_retries: int | None = None,
) -> tuple[list[Candidate], list[str], str]:
    """Lease up to `limit` free items of `kind` to `claimant` and extend the
    lease on the items of that kind they already hold.

    Returns the new items, the ids renewed and when the lease ends. The caller
    owns the transaction."""
    stamp = timestamps.of(now)
    expires = timestamps.of(now + LEASE)
    if follow_up_retries is not None:
        conn.execute(
            "DELETE FROM automation_stops WHERE kind = 'gap_follow_up' "
            "AND NOT EXISTS (SELECT 1 FROM knowledge_gaps g WHERE g.id = item_id "
            f"AND g.text = inputs AND {_OPEN_GAP})"
        )
    conn.execute("DELETE FROM curation_claims WHERE expires_at <= ?", (stamp,))
    renewed = [
        str(r[0])
        for r in conn.execute(
            "SELECT item_id FROM curation_claims WHERE claimed_by = ? AND kind = ? "
            "ORDER BY item_id",
            (claimant, kind),
        )
    ]
    conn.execute(
        "UPDATE curation_claims SET expires_at = ? WHERE claimed_by = ? AND kind = ?",
        (expires, claimant, kind),
    )
    chosen = _candidates(
        conn,
        drafts,
        kind,
        limit,
        stamp,
        pairs=pairs,
        exclude_skipped_by=exclude_skipped_by,
        draft_gaps_only=draft_gaps_only,
        follow_up_retries=follow_up_retries,
        answer_retries=answer_retries,
        at=now,
    )
    if follow_up_retries is not None and kind in ("rephrase", "gap"):
        automation_stops.clear(
            conn,
            "gap_follow_up",
            [
                item.id
                for item in chosen
                if automation_stops.retried(conn, "gap_follow_up", item.id, item.text)
            ],
        )
    conn.executemany(
        "INSERT INTO curation_claims "
        "(item_id, kind, neighbours, claimed_by, claimed_at, expires_at) "
        "VALUES (?, ?, '[]', ?, ?, ?)",
        [(c.id, kind, claimant, stamp, expires) for c in chosen],
    )
    return chosen, renewed, expires


def _candidates(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    kind: Kind,
    limit: int,
    now: str,
    *,
    pairs: Sequence[DuplicateCandidate],
    exclude_skipped_by: str | None,
    draft_gaps_only: bool,
    follow_up_retries: int | None,
    answer_retries: int | None,
    at: datetime,
) -> list[Candidate]:
    """The first `limit` items of `kind`, in id order, that nobody holds, no
    attempt has settled, and no undecided draft already covers."""
    if kind == "duplicate":
        return _duplicate_candidates(
            conn,
            drafts,
            pairs,
            limit=limit,
            now=now,
            exclude_skipped_by=exclude_skipped_by,
        )
    if kind in _CONCEPT_KINDS:
        return _concept_candidates(
            conn,
            drafts,
            kind,
            limit=limit,
            now=now,
            exclude_skipped_by=exclude_skipped_by,
        )
    if kind in _STATEMENT_KINDS:
        pending = knowledge_health.pending_statement_ids(drafts)
        where = (
            knowledge_health.STATEMENT_WHERE[_STATEMENT_KINDS[kind]]
            + f" AND NOT {knowledge_health.SETTLED} AND NOT {knowledge_health.CLAIMED}"
        )
        sql = (
            f"SELECT s.id, s.id AS statement_id, s.text FROM statements s "
            f"WHERE s.id > :after AND {where} ORDER BY s.id LIMIT :chunk"
        )
    elif kind == "question":
        pending = set()
        sql = (
            "SELECT g.id, g.statement_id, g.text, NULL AS draft_id "
            "FROM knowledge_gaps g "
            f"WHERE g.id > :after AND {_GAP_WHERE[kind]} "
            f"AND NOT {_GAP_SETTLED} AND NOT {_GAP_CLAIMED} "
            "ORDER BY g.id LIMIT :chunk"
        )
    else:
        pending = {
            str(r[0])
            for r in drafts.execute("SELECT id FROM drafts WHERE decided_at IS NULL")
        }
        sql = (
            "SELECT g.id, g.statement_id, g.text, g.draft_id FROM knowledge_gaps g "
            f"WHERE g.id > :after AND {_GAP_WHERE[kind]} "
            f"AND NOT {_GAP_SETTLED} AND NOT {_GAP_CLAIMED} "
            + ("AND g.draft_id IS NOT NULL " if draft_gaps_only else "")
            + "ORDER BY g.id LIMIT :chunk"
        )
    params = _params(
        now, waiting_for_answer(drafts, answer_retries) if kind == "question" else ()
    )
    chosen: list[sqlite3.Row] = []
    stopped = (
        automation_stops.stopped(conn, "gap_follow_up")
        if follow_up_retries is not None and kind in ("rephrase", "gap")
        else {}
    )
    after = ""
    while len(chosen) < limit:
        rows = conn.execute(sql, {**params, "after": after, "chunk": _CHUNK}).fetchall()
        for row in rows:
            item_id = str(row["id"])
            text = str(row["text"])
            if stopped.get(item_id) == text:
                continue
            if (
                follow_up_retries is not None
                and kind in ("rephrase", "gap")
                and row["draft_id"] is not None
            ):
                hops = _follow_up_hops(conn, str(row["draft_id"]))
                if hops > follow_up_retries and not automation_stops.retried(
                    conn, "gap_follow_up", item_id, text
                ):
                    automation_stops.stop(
                        conn,
                        "gap_follow_up",
                        item_id,
                        text,
                        f"{hops} curation proposals in a row were rejected; "
                        "a person decides this gap.",
                        failures=hops,
                        now=at,
                    )
                    stopped[item_id] = text
                    continue
            covered = row["id"] if kind in _STATEMENT_KINDS else row["draft_id"]
            if covered not in pending and not _skipped_by(
                conn, str(row["id"]), str(row["text"]), exclude_skipped_by
            ):
                chosen.append(row)
        if len(rows) < _CHUNK:
            break
        after = str(rows[-1]["id"])
    chosen = chosen[:limit]
    subjects = _subjects(conn, [str(r["statement_id"]) for r in chosen])
    return [
        Candidate(
            id=str(r["id"]),
            text=str(r["text"]),
            statement=subjects.get(str(r["statement_id"])),
        )
        for r in chosen
    ]


def _follow_up_hops(conn: sqlite3.Connection, draft_id: str) -> int:
    hops = 0
    seen: set[str] = set()
    current = draft_id
    while current not in seen:
        seen.add(current)
        attempt = conn.execute(
            "SELECT item_id FROM curation_attempts "
            "WHERE draft_id = ? AND outcome = 'proposed' "
            "ORDER BY attempted_at DESC LIMIT 1",
            (current,),
        ).fetchone()
        if attempt is None:
            break
        hops += 1
        gap = conn.execute(
            "SELECT draft_id FROM knowledge_gaps WHERE id = ?",
            (str(attempt["item_id"]),),
        ).fetchone()
        if gap is None or gap["draft_id"] is None:
            break
        current = str(gap["draft_id"])
    return hops


def _pending_payloads(drafts: sqlite3.Connection) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for row in drafts.execute(
        "SELECT o.payload_json FROM drafts d JOIN draft_ops o ON o.draft_id = d.id "
        "WHERE d.decided_at IS NULL"
    ):
        value = json.loads(str(row[0]))
        if isinstance(value, dict):
            payloads.append({str(key): item for key, item in value.items()})
    return payloads


def _strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_strings(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(*(_strings(item) for item in value.values()), set())
    return set()


def _pending_refs(drafts: sqlite3.Connection) -> tuple[set[str], set[str]]:
    refs: set[str] = set()
    names: set[str] = set()
    for payload in _pending_payloads(drafts):
        refs.update(_strings(payload))
        name = payload.get("name")
        if isinstance(name, str):
            names.add(name.casefold())
    return refs, names


def _skipped_by(
    conn: sqlite3.Connection,
    item_id: str,
    text: str,
    claimant: str | None,
) -> bool:
    if claimant is None:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM curation_attempts WHERE item_id = ? AND text = ? "
            "AND outcome = 'skipped' AND attempted_by = ?",
            (item_id, text, claimant),
        ).fetchone()
        is not None
    )


def _settled(conn: sqlite3.Connection, item_id: str, text: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM curation_attempts WHERE item_id = ? AND text = ? "
            "AND outcome <> 'skipped'",
            (item_id, text),
        ).fetchone()
        is not None
    )


def _duplicate_candidates(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    pairs: Sequence[DuplicateCandidate],
    *,
    limit: int,
    now: str,
    exclude_skipped_by: str | None,
) -> list[Candidate]:
    if limit == 0:
        return []
    refs, _ = _pending_refs(drafts)
    chosen: list[Candidate] = []
    for pair in sorted(pairs, key=lambda item: item.id):
        ids = pair.id.split("~")
        if len(ids) != 2 or any(item in refs for item in ids):
            continue
        if _settled(conn, pair.id, pair.text) or _skipped_by(
            conn, pair.id, pair.text, exclude_skipped_by
        ):
            continue
        claimed = conn.execute(
            "SELECT 1 FROM curation_claims WHERE item_id = ? AND expires_at > ?",
            (pair.id, now),
        ).fetchone()
        if claimed is None:
            chosen.append(Candidate(pair.id, pair.text, None))
        if len(chosen) == limit:
            break
    return chosen


def available_duplicate_candidates(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    pairs: Sequence[DuplicateCandidate],
    *,
    limit: int,
    now: datetime,
    exclude_skipped_by: str | None = None,
) -> list[DuplicateCandidate]:
    """Select duplicate pairs the queue could currently claim."""
    available = _duplicate_candidates(
        conn,
        drafts,
        pairs,
        limit=limit,
        now=timestamps.of(now),
        exclude_skipped_by=exclude_skipped_by,
    )
    by_id = {pair.id: pair for pair in pairs}
    return [by_id[item.id] for item in available]


def concept_text(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute(
        "SELECT description FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()
    if row is None:
        return None
    names = [
        str(item[0])
        for item in conn.execute(
            "SELECT text FROM names WHERE entity_id = ? ORDER BY text COLLATE NOCASE, text",
            (entity_id,),
        )
    ]
    return json.dumps(
        {"names": names, "description": str(row[0] or "")},
        ensure_ascii=False,
        sort_keys=True,
    )


def _concept_candidates(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    kind: Kind,
    *,
    limit: int,
    now: str,
    exclude_skipped_by: str | None,
) -> list[Candidate]:
    if limit == 0:
        return []
    refs, pending_names = _pending_refs(drafts)
    where = knowledge_health.ENTITY_WHERE[_CONCEPT_KINDS[kind]]
    rows = conn.execute(f"SELECT e.id FROM entities e WHERE {where} ORDER BY e.id")
    chosen: list[Candidate] = []
    for row in rows:
        entity_id = str(row[0])
        text = concept_text(conn, entity_id)
        if text is None or entity_id in refs:
            continue
        names = {
            str(name[0]).casefold()
            for name in conn.execute(
                "SELECT text FROM names WHERE entity_id = ?", (entity_id,)
            )
        }
        if names & pending_names:
            continue
        attempt = conn.execute(
            "SELECT attempted_at, outcome, text, attempted_by FROM curation_attempts "
            "WHERE item_id = ?",
            (entity_id,),
        ).fetchone()
        if attempt is not None and str(attempt[2]) == text:
            if str(attempt[1]) != "skipped":
                if kind != "undescribed" or not _concept_statement_changed(
                    conn, entity_id, str(attempt[0])
                ):
                    continue
            elif (
                exclude_skipped_by is not None and str(attempt[3]) == exclude_skipped_by
            ):
                if kind != "undescribed" or not _concept_statement_changed(
                    conn, entity_id, str(attempt[0])
                ):
                    continue
        claimed = conn.execute(
            "SELECT 1 FROM curation_claims WHERE item_id = ? AND expires_at > ?",
            (entity_id, now),
        ).fetchone()
        if claimed is None:
            chosen.append(Candidate(entity_id, text, None))
        if len(chosen) == limit:
            break
    return chosen


def _concept_statement_changed(
    conn: sqlite3.Connection, entity_id: str, attempted_at: str
) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM names n JOIN statement_mentions m ON m.name_id = n.id "
            "JOIN statements s ON s.id = m.statement_id WHERE n.entity_id = ? "
            "AND COALESCE(s.updated_at, s.created_at, '') > ? LIMIT 1",
            (entity_id, attempted_at),
        ).fetchone()
        is not None
    )


def item_text(conn: sqlite3.Connection, kind: Kind, item_id: str) -> str | None:
    """The stable attempt-memory text for one current item."""
    if kind == "duplicate":
        ids = item_id.split("~")
        if len(ids) != 2:
            return None
        statements = conn.execute(
            "SELECT id, text FROM statements WHERE id IN (?, ?) ORDER BY id", ids
        ).fetchall()
        if len(statements) == 2:
            return json.dumps(
                {str(row["id"]): str(row["text"]) for row in statements},
                ensure_ascii=False,
                sort_keys=True,
            )
        concepts = {
            entity_id: [
                str(row[0])
                for row in conn.execute(
                    "SELECT text FROM names WHERE entity_id = ? "
                    "ORDER BY text COLLATE NOCASE, text",
                    (entity_id,),
                )
            ]
            for entity_id in ids
        }
        if all(names for names in concepts.values()):
            return json.dumps(
                concepts,
                ensure_ascii=False,
                sort_keys=True,
            )
        return None
    if kind in _CONCEPT_KINDS:
        return concept_text(conn, item_id)
    table = "knowledge_gaps" if kind in _GAP_WHERE else "statements"
    row = conn.execute(f"SELECT text FROM {table} WHERE id = ?", (item_id,)).fetchone()
    return None if row is None else str(row[0])


def _subjects(conn: sqlite3.Connection, ids: Sequence[str]) -> dict[str, Subject]:
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    concepts: dict[str, dict[str, str]] = {}
    for row in conn.execute(
        f"SELECT m.statement_id, n.entity_id, n.text FROM statement_mentions m "
        f"JOIN names n ON n.id = m.name_id WHERE m.statement_id IN ({marks}) "
        "ORDER BY n.text",
        list(ids),
    ):
        concepts.setdefault(str(row[0]), {}).setdefault(str(row[1]), str(row[2]))
    return {
        str(row["id"]): Subject(
            id=str(row["id"]),
            kind=str(row["kind"]),
            text=str(row["text"]),
            concepts=[
                Concept(id=entity_id, name=name)
                for entity_id, name in concepts.get(str(row["id"]), {}).items()
            ],
        )
        for row in conn.execute(
            f"SELECT id, kind, text FROM statements WHERE id IN ({marks})", list(ids)
        )
    }


def offered(conn: sqlite3.Connection, item_id: str, neighbours: Sequence[str]) -> None:
    """Record the statements a claim offered as `item_id`'s neighbours: what
    its release will be remembered as having weighed."""
    conn.execute(
        "UPDATE curation_claims SET neighbours = ? WHERE item_id = ?",
        (json.dumps(sorted(set(neighbours))), item_id),
    )


def release(
    conn: sqlite3.Connection,
    item_ids: Sequence[str],
    outcome: Outcome,
    *,
    claimant: str,
    now: datetime,
    reason: str | None = None,
    draft_id: str | None = None,
) -> list[str]:
    """Remember what `claimant` made of the items they hold and free them.

    A gap released as `proposed` is tied to the proposing draft, so applying it
    resolves the gap. `resolved` resolves the gap and ties it to the draft that
    did; `not_applicable` dismisses it. Both are recorded
    as the claimant's, as a person's status change is. Returns the ids
    released; raises ValueError naming any id the claimant does not hold or
    an outcome its kind does not take. The caller owns the transaction."""
    unique = list(dict.fromkeys(item_ids))
    held = held_kinds(conn, unique, claimant, outcome)
    marks = ", ".join("?" for _ in unique)
    stamp = timestamps.of(now)
    neighbours = {
        str(r[0]): str(r[1])
        for r in conn.execute(
            f"SELECT item_id, neighbours FROM curation_claims WHERE item_id IN ({marks})",
            unique,
        )
    }
    for item_id, kind in held.items():
        gap = kind in _GAP_WHERE
        text = item_text(conn, kind, item_id)
        if text is None:
            raise ValueError(f"curation item '{item_id}' no longer exists")
        conn.execute(
            "INSERT OR REPLACE INTO curation_attempts (item_id, text, neighbours, "
            "attempted_at, attempted_by, outcome, reason, draft_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                text,
                neighbours[item_id],
                stamp,
                claimant,
                outcome,
                reason,
                draft_id,
            ),
        )
        if gap and outcome in ("proposed", "resolved"):
            conn.execute(
                "UPDATE knowledge_gaps SET draft_id = ? WHERE id = ?",
                (draft_id, item_id),
            )
        if outcome in ("resolved", "not_applicable"):
            if gap:
                set_knowledge_gap_status(
                    conn,
                    item_id,
                    "resolve" if outcome == "resolved" else "dismiss",
                    claimant,
                )
            elif kind == "duplicate" and outcome == "not_applicable":
                pair = item_id.split("~")
                if len(pair) == 2 and all(
                    conn.execute(
                        "SELECT 1 FROM entities WHERE id = ?", (entity_id,)
                    ).fetchone()
                    is not None
                    for entity_id in pair
                ):
                    actor = store.get_actor()
                    try:
                        store.set_actor(claimant)
                        store.dismiss_entity_duplicate(conn, pair[0], pair[1])
                    finally:
                        store.set_actor(actor)
    conn.execute(f"DELETE FROM curation_claims WHERE item_id IN ({marks})", unique)
    return unique


def held_kinds(
    conn: sqlite3.Connection,
    item_ids: Sequence[str],
    claimant: str,
    outcome: Outcome | None = None,
) -> dict[str, Kind]:
    """The kind of each item `claimant` holds; raises ValueError naming any
    they do not hold, or that `outcome` cannot release."""
    unique = list(dict.fromkeys(item_ids))
    marks = ", ".join("?" for _ in unique)
    held: dict[str, Kind] = {
        str(r[0]): r[1]
        for r in conn.execute(
            f"SELECT item_id, kind FROM curation_claims "
            f"WHERE claimed_by = ? AND item_id IN ({marks})",
            [claimant, *unique],
        )
    }
    missing = [i for i in unique if i not in held]
    if missing:
        raise ValueError(f"not held by you: {', '.join(missing)}")
    if outcome is not None:
        wrong = sorted(
            {kind for kind in held.values() if outcome not in OUTCOMES[kind]}
        )
        if wrong:
            raise ValueError(
                f"{', '.join(wrong)} items cannot be released as {outcome}"
            )
    return held


def free(conn: sqlite3.Connection, kind: Kind, claimed_by: str) -> int:
    """Drop `claimed_by`'s claims on `kind` without recording an attempt, for an
    admin freeing work an agent abandoned. Returns how many were dropped."""
    return conn.execute(
        "DELETE FROM curation_claims WHERE kind = ? AND claimed_by = ?",
        (kind, claimed_by),
    ).rowcount


def abandon(conn: sqlite3.Connection, item_id: str, claimed_by: str) -> bool:
    """Drop one stale claim without recording an attempt."""
    return (
        conn.execute(
            "DELETE FROM curation_claims WHERE item_id = ? AND claimed_by = ?",
            (item_id, claimed_by),
        ).rowcount
        == 1
    )


def summaries(
    conn: sqlite3.Connection, drafts: sqlite3.Connection, now: datetime
) -> list[Summary]:
    """Per kind: who holds items, and what became of the items still listed."""
    stamp = timestamps.of(now)
    waiting = waiting_for_answer(drafts)
    holders: dict[str, list[Holder]] = {}
    for row in conn.execute(
        "SELECT kind, claimed_by, COUNT(*), MAX(expires_at) FROM curation_claims "
        "WHERE expires_at > ? GROUP BY kind, claimed_by ORDER BY claimed_by",
        (stamp,),
    ):
        holders.setdefault(str(row[0]), []).append(
            Holder(claimed_by=str(row[1]), items=int(row[2]), expires_at=str(row[3]))
        )
    out: list[Summary] = []
    for kind in KINDS:
        if kind in _STATEMENT_KINDS:
            where = knowledge_health.STATEMENT_WHERE[_STATEMENT_KINDS[kind]]
            listed = f"SELECT s.id FROM statements s WHERE {where}"
        elif kind in _GAP_WHERE:
            listed = f"SELECT g.id FROM knowledge_gaps g WHERE {_GAP_WHERE[kind]}"
        elif kind in _CONCEPT_KINDS:
            where = knowledge_health.ENTITY_WHERE[_CONCEPT_KINDS[kind]]
            listed = f"SELECT e.id FROM entities e WHERE {where}"
        else:
            listed = (
                "SELECT item_id FROM curation_attempts WHERE instr(item_id, '~') > 0 "
                "UNION SELECT item_id FROM curation_claims WHERE kind = 'duplicate'"
            )
        outcomes = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                f"SELECT c.outcome, COUNT(*) FROM curation_attempts c "
                f"WHERE c.item_id IN ({listed}) GROUP BY c.outcome",
                _params(stamp, waiting),
            )
        }
        out.append(
            Summary(
                kind=kind,
                claims=holders.get(kind, []),
                attempted=sum(outcomes.values()),
                outcomes=outcomes,
            )
        )
    return out
