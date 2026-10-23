"""Audience labels on statements and the queue the labelling worker drains.

A statement's label is the set of documentation audiences that may see it.
No label means unlabelled, which fails closed: only internal audiences see
it. Audience ids are owned by the prompts database (`mycelium.audiences`).

An AI grant that would newly show a statement to an audience held for
confirmation is stored in `pending`, outside `audiences`, so every reader
of the label treats it as not granted until a curator confirms it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import TypeAdapter
from typing_extensions import TypedDict

from .kernel import _now

Source = Literal["ai", "curator"]
Visibility = Literal["visible", "hidden"]
LabelState = Literal["unlabelled", "ai", "curator", "text_changed", "pending", "queued"]


class Sample(TypedDict):
    size: int
    precision: float


class Narrowed(TypedDict):
    """An edit's relabel took the statement away from audiences that saw it."""

    previous: list[str]
    lost: list[str]
    reason: str


class Decision(TypedDict, total=False):
    decision: Literal["confirmed", "rejected"]
    by: str | None
    at: str
    #: Set when the grant was accepted in bulk after a reviewed sample.
    sample: Sample


class Previous(TypedDict):
    """The AI label an edit dropped, kept on the queue row so the relabel
    can start from it."""

    text: str
    audiences: list[str]
    reason: str
    #: The curator confirmations of grants that were in force, and the text
    #: they were confirmed for.
    confirmed: dict[str, Decision]
    confirmed_text: str


class SpotCheck(TypedDict):
    """Confirmed external grants an edit's relabel kept in force."""

    audiences: list[str]
    #: The text the grants were confirmed for.
    old_text: str
    at: str


@dataclass(frozen=True)
class Graph:
    """Per live audience the audience ids whose grants it sees (itself and
    every audience it includes), and which audiences are internal."""

    sees: Mapping[str, frozenset[str]]
    internal: frozenset[str] = frozenset()

    def seeing(self, granted: Collection[str]) -> frozenset[str]:
        """The audiences a label granting `granted` is visible to."""
        wanted = set(granted)
        return frozenset(key for key, sees in self.sees.items() if sees & wanted)


#: Attempts before a failing statement waits for the next backfill.
MAX_ATTEMPTS = 5
_BACKOFF = timedelta(minutes=1)


def visibility_clause(
    sees: frozenset[str], internal: bool
) -> tuple[str, tuple[str, ...]]:
    """SQL over `statements s LEFT JOIN statement_audience_labels l`: whether
    `s` is visible to an audience that sees the grants of the audience ids
    `sees` (itself and every audience it includes)."""
    ids = tuple(sorted(sees))
    placeholders = ", ".join("?" for _ in ids)
    granted = (
        f"EXISTS (SELECT 1 FROM json_each(l.audiences) WHERE value IN ({placeholders}))"
    )
    if internal:
        return f"(l.statement_id IS NULL OR {granted})", ids
    return f"(l.statement_id IS NOT NULL AND {granted})", ids


def grants(label: Sequence[str] | None, sees: frozenset[str], internal: bool) -> bool:
    """`visibility_clause` for a label held outside the substrate (media):
    whether a label, None while unlabelled, lets an audience that sees the
    grants of `sees` see its item. Keep the two in step."""
    if label is None:
        return internal
    return bool(sees & set(label))


def visible_statement_ids(
    conn: sqlite3.Connection, sees: frozenset[str], internal: bool
) -> frozenset[str]:
    clause, params = visibility_clause(sees, internal)
    return frozenset(
        str(row["id"])
        for row in conn.execute(
            "SELECT s.id FROM statements s LEFT JOIN statement_audience_labels l "
            f"ON l.statement_id = s.id WHERE {clause}",
            params,
        )
    )


def visible_among(
    conn: sqlite3.Connection,
    sees: frozenset[str],
    internal: bool,
    statement_ids: Sequence[str],
) -> frozenset[str]:
    """Which of `statement_ids` the audience may see."""
    clause, params = visibility_clause(sees, internal)
    visible: set[str] = set()
    for offset in range(0, len(statement_ids), 500):
        chunk = list(statement_ids[offset : offset + 500])
        placeholders = ", ".join("?" for _ in chunk)
        visible.update(
            str(row["id"])
            for row in conn.execute(
                "SELECT s.id FROM statements s LEFT JOIN statement_audience_labels l "
                f"ON l.statement_id = s.id WHERE s.id IN ({placeholders}) AND {clause}",
                (*chunk, *params),
            )
        )
    return frozenset(visible)


def awaiting_label(
    conn: sqlite3.Connection, statement_ids: Sequence[str], audience_id: str
) -> frozenset[str]:
    """Which of `statement_ids` are queued with attempts left, so a label is
    still coming, or wait for a curator to confirm a grant to the audience."""
    awaiting: set[str] = set()
    for offset in range(0, len(statement_ids), 500):
        chunk = list(statement_ids[offset : offset + 500])
        placeholders = ", ".join("?" for _ in chunk)
        awaiting.update(
            str(row["statement_id"])
            for row in conn.execute(
                "SELECT statement_id FROM audience_label_queue "
                f"WHERE statement_id IN ({placeholders}) AND attempts < ? "
                "UNION SELECT statement_id FROM statement_audience_labels l "
                f"WHERE statement_id IN ({placeholders}) AND EXISTS "
                "(SELECT 1 FROM json_each(l.pending) WHERE value = ?)",
                (*chunk, MAX_ATTEMPTS, *chunk, audience_id),
            )
        )
    return frozenset(awaiting)


def get_label(conn: sqlite3.Connection, statement_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM statement_audience_labels WHERE statement_id = ?",
        (statement_id,),
    ).fetchone()
    return row


def label_audiences(row: sqlite3.Row) -> list[str]:
    value = json.loads(row["audiences"])
    return [str(item) for item in value] if isinstance(value, list) else []


def label_pending(row: sqlite3.Row) -> list[str]:
    value = json.loads(row["pending"] or "[]")
    return [str(item) for item in value] if isinstance(value, list) else []


_NARROWED: TypeAdapter[Narrowed | None] = TypeAdapter(Narrowed | None)
_PREVIOUS: TypeAdapter[Previous | None] = TypeAdapter(Previous | None)
_SPOT_CHECK: TypeAdapter[SpotCheck | None] = TypeAdapter(SpotCheck | None)


def label_narrowed(row: sqlite3.Row) -> Narrowed | None:
    return _NARROWED.validate_json(row["narrowed"] or "null")


def label_spot_check(row: sqlite3.Row) -> SpotCheck | None:
    return _SPOT_CHECK.validate_json(row["kept_on_edit"] or "null")


def queued_previous(row: sqlite3.Row) -> Previous | None:
    return _PREVIOUS.validate_json(row["previous"] or "null")


def label_decisions(row: sqlite3.Row) -> dict[str, Decision]:
    value = json.loads(row["decisions"] or "{}")
    return value if isinstance(value, dict) else {}


def _json_list(values: Sequence[str] | set[str]) -> str | None:
    return json.dumps(sorted(set(values))) if values else None


def _json_object(values: dict[str, Decision]) -> str | None:
    return json.dumps(values, sort_keys=True) if values else None


def set_label(
    conn: sqlite3.Connection,
    statement_id: str,
    audiences: Sequence[str],
    *,
    source: Source,
    reason: str,
    model: str | None = None,
    cost_usd: float | None = None,
    labelled_by: str | None = None,
    pending: Sequence[str] = (),
    decisions: dict[str, Decision] | None = None,
    narrowed: Narrowed | None = None,
    spot_check: SpotCheck | None = None,
) -> None:
    """Replace the statement's label. The caller decides whether an AI label
    may replace what is there; see `apply_ai_label`."""
    conn.execute(
        "INSERT INTO statement_audience_labels "
        "(statement_id, audiences, source, reason, model, cost_usd, labelled_at, "
        "labelled_by, pending, decisions, narrowed, kept_on_edit) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(statement_id) DO UPDATE SET "
        "audiences = excluded.audiences, source = excluded.source, "
        "reason = excluded.reason, model = excluded.model, "
        "cost_usd = excluded.cost_usd, labelled_at = excluded.labelled_at, "
        "labelled_by = excluded.labelled_by, text_changed_at = NULL, "
        "pending = excluded.pending, decisions = excluded.decisions, "
        "narrowed = excluded.narrowed, kept_on_edit = excluded.kept_on_edit",
        (
            statement_id,
            json.dumps(sorted(set(audiences))),
            source,
            reason,
            model,
            cost_usd,
            _now(),
            labelled_by,
            _json_list(set(pending)),
            _json_object(decisions or {}),
            json.dumps(narrowed) if narrowed is not None else None,
            json.dumps(spot_check) if spot_check is not None else None,
        ),
    )
    conn.execute(
        "DELETE FROM audience_label_queue WHERE statement_id = ?", (statement_id,)
    )


def apply_ai_label(
    conn: sqlite3.Connection,
    statement_id: str,
    audiences: Sequence[str],
    *,
    reason: str,
    model: str,
    cost_usd: float | None,
    hold: Collection[str] = (),
    graph: Graph | None = None,
    narrowed: Narrowed | None = None,
    carried: Mapping[str, Decision] | None = None,
    confirmed_text: str = "",
) -> bool:
    """Store an AI label unless a curator has decided. False when skipped.

    A grant to an audience in `hold` that the statement is not already
    visible to waits in `pending` for a curator. Meanwhile the internal
    audiences that would see it through their includes, and any audience
    that already saw the statement, are granted it directly, so a waiting
    grant never hides the statement from them. Curator decisions on grants
    that stay in force are kept.

    `carried` are curator confirmations from before an edit whose grants
    the relabel keeps: they stay in force and confirmed, and the label is
    marked for a spot check against `confirmed_text`."""
    current = get_label(conn, statement_id)
    if current is not None and current["source"] == "curator":
        conn.execute(
            "DELETE FROM audience_label_queue WHERE statement_id = ?", (statement_id,)
        )
        return False
    carried = {key: value for key, value in (carried or {}).items() if key in audiences}
    visible = set(label_audiences(current)) if current is not None else set()
    visible |= carried.keys()
    granted = set(audiences)
    graph = graph or Graph({key: frozenset((key,)) for key in granted | visible})

    def sees(key: str) -> frozenset[str]:
        return graph.sees.get(key, frozenset((key,)))

    waiting = {item for item in granted & set(hold) if not sees(item) & visible}
    kept = granted - waiting
    kept |= _cover(
        graph,
        waiting,
        kept,
        lambda key: key in graph.internal or bool(sees(key) & visible),
    )
    decided = {**(label_decisions(current) if current is not None else {}), **carried}
    set_label(
        conn,
        statement_id,
        sorted(kept),
        source="ai",
        reason=reason,
        model=model,
        cost_usd=cost_usd,
        pending=sorted(waiting),
        decisions={key: value for key, value in decided.items() if key in kept},
        narrowed=narrowed,
        spot_check=(
            {"audiences": sorted(carried), "old_text": confirmed_text, "at": _now()}
            if carried
            else None
        ),
    )
    return True


def _cover(
    graph: Graph,
    hidden: Collection[str],
    kept: Collection[str],
    eligible: Callable[[str], bool],
) -> set[str]:
    """The narrowest eligible audiences that would see a grant to `hidden`
    through their includes and do not already see `kept`, so that granting
    them directly keeps the statement in their view."""

    def sees(key: str) -> frozenset[str]:
        return graph.sees.get(key, frozenset((key,)))

    candidates = {
        key
        for key in graph.sees
        if key not in hidden
        and not sees(key) & set(kept)
        and sees(key) & set(hidden)
        and eligible(key)
    }
    return {
        key
        for key in candidates
        if not any(other in sees(key) for other in candidates - {key})
    }


def decide_pending(
    conn: sqlite3.Connection,
    statement_id: str,
    audience_id: str,
    *,
    confirm: bool,
    by: str | None,
    reason: str = "",
    sample: Sample | None = None,
    graph: Graph | None = None,
) -> bool:
    """A curator confirms or rejects one pending grant. A confirmation makes
    it a grant and drops the internal grants that now see the statement
    through it (`graph`'s includes); a rejection makes the label a curator decision without it,
    so the AI does not grant it again. False when nothing was pending."""
    current = get_label(conn, statement_id)
    if current is None or audience_id not in label_pending(current):
        return False
    decision: Decision = {
        "decision": "confirmed" if confirm else "rejected",
        "by": by,
        "at": _now(),
    }
    if sample is not None:
        decision["sample"] = sample
    decisions = {**label_decisions(current), audience_id: decision}
    pending = [item for item in label_pending(current) if item != audience_id]
    granted = label_audiences(current)
    if confirm:
        redundant = {
            key
            for key in granted
            if graph is not None
            and key in graph.internal
            and audience_id in graph.sees.get(key, ())
        }
        conn.execute(
            "UPDATE statement_audience_labels SET audiences = ?, pending = ?, "
            "decisions = ? WHERE statement_id = ?",
            (
                json.dumps(sorted({*granted, audience_id} - redundant)),
                _json_list(pending),
                _json_object(decisions),
                statement_id,
            ),
        )
    else:
        conn.execute(
            "UPDATE statement_audience_labels SET source = 'curator', reason = ?, "
            "labelled_at = ?, labelled_by = ?, text_changed_at = NULL, pending = ?, "
            "decisions = ? WHERE statement_id = ?",
            (
                reason or "A curator rejected the AI's grant.",
                decision["at"],
                by,
                _json_list(pending),
                _json_object(decisions),
                statement_id,
            ),
        )
    return True


def confirm_spot_check(
    conn: sqlite3.Connection, statement_id: str, *, by: str | None
) -> bool:
    """A curator confirms the grants an edit kept for the new text. False
    when nothing waits for a spot check."""
    current = get_label(conn, statement_id)
    checking = label_spot_check(current) if current is not None else None
    if current is None or checking is None:
        return False
    decision: Decision = {"decision": "confirmed", "by": by, "at": _now()}
    decisions = {
        **label_decisions(current),
        **{key: decision for key in checking["audiences"]},
    }
    conn.execute(
        "UPDATE statement_audience_labels SET kept_on_edit = NULL, decisions = ? "
        "WHERE statement_id = ?",
        (_json_object(decisions), statement_id),
    )
    return True


def narrow_spot_check(
    conn: sqlite3.Connection,
    statement_id: str,
    *,
    by: str | None,
    reason: str,
    graph: Graph,
) -> bool:
    """A curator withdraws the grants an edit kept. The label becomes theirs,
    so the AI does not grant them again, and still grants the internal
    audiences that saw the statement through them. False when nothing waits
    for a spot check."""
    current = get_label(conn, statement_id)
    checking = label_spot_check(current) if current is not None else None
    if current is None or checking is None:
        return False
    withdrawn = set(checking["audiences"])
    kept = set(label_audiences(current)) - withdrawn
    kept |= _cover(graph, withdrawn, kept, lambda key: key in graph.internal)
    set_label(
        conn,
        statement_id,
        sorted(kept),
        source="curator",
        reason=reason,
        labelled_by=by,
        pending=label_pending(current),
        decisions={
            key: value for key, value in label_decisions(current).items() if key in kept
        },
    )
    return True


def spot_checks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Statements whose confirmed external grants an edit kept, newest first."""
    return conn.execute(
        "SELECT s.id, s.kind, s.text, l.kept_on_edit FROM statement_audience_labels l "
        "JOIN statements s ON s.id = l.statement_id WHERE l.kept_on_edit IS NOT NULL "
        "ORDER BY json_extract(l.kept_on_edit, '$.at') DESC, s.id"
    ).fetchall()


def clear_label(conn: sqlite3.Connection, statement_id: str) -> None:
    """Drop the label and queue the statement to be labelled again."""
    conn.execute(
        "DELETE FROM statement_audience_labels WHERE statement_id = ?",
        (statement_id,),
    )
    enqueue(conn, [statement_id])


def confirm_label(
    conn: sqlite3.Connection, statement_id: str, *, labelled_by: str | None
) -> bool:
    """A curator re-decides their label unchanged after a text change. False
    when the statement has no curator label."""
    cursor = conn.execute(
        "UPDATE statement_audience_labels SET text_changed_at = NULL, "
        "labelled_at = ?, labelled_by = ? WHERE statement_id = ? AND source = 'curator'",
        (_now(), labelled_by, statement_id),
    )
    return cursor.rowcount > 0


def text_changed(conn: sqlite3.Connection, statement_id: str, old_text: str) -> None:
    """A statement's text changed: its AI label no longer describes it, and
    a curator label is kept but marked for the curator to look at again. The
    dropped AI label and the text it judged wait on the queue row, so the
    relabel starts from them."""
    current = get_label(conn, statement_id)
    previous: Previous | None = None
    if current is not None and current["source"] == "ai":
        granted = label_audiences(current)
        checking = label_spot_check(current)
        previous = {
            "text": old_text,
            "audiences": sorted({*granted, *label_pending(current)}),
            "reason": str(current["reason"]),
            "confirmed": {
                key: value
                for key, value in label_decisions(current).items()
                if key in granted and value.get("decision") == "confirmed"
            },
            "confirmed_text": checking["old_text"] if checking else old_text,
        }
    conn.execute(
        "DELETE FROM statement_audience_labels WHERE statement_id = ? AND source = 'ai'",
        (statement_id,),
    )
    conn.execute(
        "UPDATE statement_audience_labels SET text_changed_at = ? "
        "WHERE statement_id = ? AND text_changed_at IS NULL",
        (_now(), statement_id),
    )
    # A pending grant judged the old text; nobody may confirm it for the new.
    conn.execute(
        "UPDATE statement_audience_labels SET pending = NULL WHERE statement_id = ?",
        (statement_id,),
    )
    if get_label(conn, statement_id) is None:
        enqueue(conn, [statement_id], previous=previous)


def enqueue(
    conn: sqlite3.Connection,
    statement_ids: Sequence[str],
    *,
    previous: Previous | None = None,
) -> None:
    """Queue statements for labelling, re-arming any that exhausted retries.
    A queued row keeps the first previous label: later edits before the
    relabel still compare against the label that was in force."""
    now = _now()
    value = json.dumps(previous) if previous is not None else None
    conn.executemany(
        "INSERT INTO audience_label_queue (statement_id, enqueued_at, previous) "
        "VALUES (?, ?, ?) ON CONFLICT(statement_id) DO UPDATE SET attempts = 0, "
        "next_attempt_at = NULL, last_error = NULL, "
        "previous = COALESCE(audience_label_queue.previous, excluded.previous)",
        [(statement_id, now, value) for statement_id in statement_ids],
    )


def enqueue_backfill(conn: sqlite3.Connection, *, relabel_ai: bool) -> int:
    """Queue every unlabelled statement, and AI-labelled ones when
    `relabel_ai`. Curator labels are never queued. Returns how many."""
    condition = (
        "l.statement_id IS NULL OR l.source = 'ai'"
        if relabel_ai
        else "l.statement_id IS NULL"
    )
    ids = [
        str(row["id"])
        for row in conn.execute(
            "SELECT s.id FROM statements s LEFT JOIN statement_audience_labels l "
            f"ON l.statement_id = s.id WHERE {condition} ORDER BY s.id"
        )
    ]
    enqueue(conn, ids)
    return len(ids)


def due_batch(
    conn: sqlite3.Connection, limit: int, now: datetime | None = None
) -> list[sqlite3.Row]:
    """Queued statements ready for an attempt, oldest first, with their text."""
    at = (now or datetime.now(UTC)).isoformat()
    return list(
        conn.execute(
            "SELECT s.id, s.kind, s.text, q.previous FROM audience_label_queue q "
            "JOIN statements s ON s.id = q.statement_id "
            "WHERE q.attempts < ? AND (q.next_attempt_at IS NULL OR q.next_attempt_at <= ?) "
            "ORDER BY q.enqueued_at, q.statement_id LIMIT ?",
            (MAX_ATTEMPTS, at, limit),
        )
    )


def record_failure(
    conn: sqlite3.Connection,
    statement_ids: Sequence[str],
    error: str,
    now: datetime | None = None,
) -> None:
    at = now or datetime.now(UTC)
    for statement_id in statement_ids:
        row = conn.execute(
            "SELECT attempts FROM audience_label_queue WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()
        if row is None:
            continue
        attempts = int(row["attempts"]) + 1
        conn.execute(
            "UPDATE audience_label_queue SET attempts = ?, next_attempt_at = ?, "
            "last_error = ? WHERE statement_id = ?",
            (
                attempts,
                (at + _BACKOFF * (1 << (attempts - 1))).isoformat(),
                error[:500],
                statement_id,
            ),
        )


def queue_started_at(conn: sqlite3.Connection) -> str | None:
    """When the oldest statement still waiting for the worker was queued."""
    row = conn.execute(
        "SELECT MIN(enqueued_at) AS at FROM audience_label_queue WHERE attempts < ?",
        (MAX_ATTEMPTS,),
    ).fetchone()
    return None if row["at"] is None else str(row["at"])


def queue_counts(conn: sqlite3.Connection) -> tuple[int, int, str | None]:
    """(waiting, failed, last error)."""
    row = conn.execute(
        "SELECT SUM(attempts < ?) AS waiting, SUM(attempts >= ?) AS failed "
        "FROM audience_label_queue",
        (MAX_ATTEMPTS, MAX_ATTEMPTS),
    ).fetchone()
    error = conn.execute(
        "SELECT last_error FROM audience_label_queue WHERE last_error IS NOT NULL "
        "ORDER BY next_attempt_at DESC LIMIT 1"
    ).fetchone()
    return (
        int(row["waiting"] or 0),
        int(row["failed"] or 0),
        str(error["last_error"]) if error is not None else None,
    )


def is_queued(conn: sqlite3.Connection, statement_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM audience_label_queue WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()
        is not None
    )


def list_labelled_statements(
    conn: sqlite3.Connection,
    *,
    sees: frozenset[str] | None = None,
    internal: bool = False,
    visibility: Visibility | None = None,
    state: LabelState | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[sqlite3.Row], int]:
    """A page of statements filtered by label state and by visibility to an
    audience: `sees` is the audience and every audience it includes."""
    conditions: list[str] = []
    params: list[str | int] = []
    if visibility is not None:
        if sees is None:
            raise ValueError("Choose a live audience to filter by visibility.")
        clause, values = visibility_clause(sees, internal)
        conditions.append(clause if visibility == "visible" else f"NOT {clause}")
        params.extend(values)
    if state == "unlabelled":
        conditions.append("l.statement_id IS NULL")
    elif state in ("ai", "curator"):
        conditions.append("l.source = ?")
        params.append(state)
    elif state == "text_changed":
        conditions.append("l.text_changed_at IS NOT NULL")
    elif state == "pending":
        conditions.append("l.pending IS NOT NULL")
    elif state == "queued":
        conditions.append("q.statement_id IS NOT NULL")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    base = (
        "FROM statements s LEFT JOIN statement_audience_labels l "
        "ON l.statement_id = s.id LEFT JOIN audience_label_queue q "
        f"ON q.statement_id = s.id {where}"
    )
    total = int(conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT s.id, s.kind, s.text, q.statement_id AS queued {base} "
        "ORDER BY s.created_at DESC, s.id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return rows, total


def label_counts(conn: sqlite3.Connection) -> tuple[int, int, int, float]:
    """(total statements, AI labels, curator labels, label cost)."""
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM statements) AS total, "
        "(SELECT COUNT(*) FROM statement_audience_labels WHERE source = 'ai') AS ai, "
        "(SELECT COUNT(*) FROM statement_audience_labels WHERE source = 'curator') AS curator, "
        "(SELECT COALESCE(SUM(cost_usd), 0) FROM statement_audience_labels) AS cost"
    ).fetchone()
    return int(row["total"]), int(row["ai"]), int(row["curator"]), float(row["cost"])


def backfill_counts(conn: sqlite3.Connection, started_at: str) -> tuple[int, float]:
    """AI labels and their cost since the backfill started."""
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS cost "
        "FROM statement_audience_labels WHERE source = 'ai' AND labelled_at >= ?",
        (started_at,),
    ).fetchone()
    return int(row["n"]), float(row["cost"])
