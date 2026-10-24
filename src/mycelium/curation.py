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

from pydantic import BaseModel

from . import knowledge_health, timestamps
from .store.gaps import set_knowledge_gap_status

Kind = Literal["isolated", "unnamed", "rephrase", "gap", "question"]
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
_GAP_SETTLED = (
    "EXISTS (SELECT 1 FROM curation_attempts c WHERE c.item_id = g.id "
    "AND c.outcome <> 'skipped' AND c.text = g.text "
    "AND NOT EXISTS (SELECT 1 FROM statements st WHERE st.id = g.statement_id "
    "AND COALESCE(st.updated_at, st.created_at, '') > c.attempted_at))"
)
_GAP_CLAIMED = knowledge_health.CLAIMED.replace("s.id", "g.id")
_CHUNK = 200


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


def waiting_for_answer(drafts: sqlite3.Connection) -> list[str]:
    """Submitted drafts whose latest review asked a person and that have not
    changed since."""
    return [
        str(row[0])
        for row in drafts.execute(
            "SELECT id FROM drafts WHERE submitted_at IS NOT NULL "
            "AND decided_at IS NULL "
            "AND json_extract(review_assessment_json, '$.application') = 'needs_human' "
            "AND json_extract(review_assessment_json, '$.draft_revision') = revision "
            "ORDER BY id"
        )
    ]


def claim(
    conn: sqlite3.Connection,
    drafts: sqlite3.Connection,
    kind: Kind,
    *,
    limit: int,
    claimant: str,
    now: datetime,
) -> tuple[list[Candidate], list[str], str]:
    """Lease up to `limit` free items of `kind` to `claimant` and extend the
    lease on the items of that kind they already hold.

    Returns the new items, the ids renewed and when the lease ends. The caller
    owns the transaction."""
    stamp = timestamps.of(now)
    expires = timestamps.of(now + LEASE)
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
    chosen = _candidates(conn, drafts, kind, limit, stamp)
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
) -> list[Candidate]:
    """The first `limit` items of `kind`, in id order, that nobody holds, no
    attempt has settled, and no undecided draft already covers."""
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
            "ORDER BY g.id LIMIT :chunk"
        )
    params = _params(now, waiting_for_answer(drafts) if kind == "question" else ())
    chosen: list[sqlite3.Row] = []
    after = ""
    while len(chosen) < limit:
        rows = conn.execute(sql, {**params, "after": after, "chunk": _CHUNK}).fetchall()
        for row in rows:
            covered = row["id"] if kind in _STATEMENT_KINDS else row["draft_id"]
            if covered not in pending:
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

    A gap released as `proposed` is tied to the draft when it names none yet,
    so applying the draft resolves it. `resolved` resolves the gap and ties it
    to the draft that did; `not_applicable` dismisses it. Both are recorded
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
        table = "knowledge_gaps" if gap else "statements"
        conn.execute(
            "INSERT OR REPLACE INTO curation_attempts (item_id, text, neighbours, "
            "attempted_at, attempted_by, outcome, reason, draft_id) "
            f"SELECT id, text, ?, ?, ?, ?, ?, ? FROM {table} WHERE id = ?",
            (
                neighbours[item_id],
                stamp,
                claimant,
                outcome,
                reason,
                draft_id,
                item_id,
            ),
        )
        if gap and outcome in ("proposed", "resolved"):
            conn.execute(
                "UPDATE knowledge_gaps SET draft_id = ? "
                "WHERE id = ? AND draft_id IS NULL",
                (draft_id, item_id),
            )
        if outcome in ("resolved", "not_applicable"):
            set_knowledge_gap_status(
                conn,
                item_id,
                "resolve" if outcome == "resolved" else "dismiss",
                claimant,
            )
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
        else:
            listed = f"SELECT g.id FROM knowledge_gaps g WHERE {_GAP_WHERE[kind]}"
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
