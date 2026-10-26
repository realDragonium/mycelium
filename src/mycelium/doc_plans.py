"""Documentation plans and their items, in the drafts database beside the
documentation runs they start.

A plan is one planning call for one writing profile. Its items are what the
model proposed after this module's checks; each is proposed, approved (with
the run it started) or dismissed. A dismissal is also kept per profile under
the item's identity key, so a later plan proposing the same thing drops it.

A plan the server started by itself, under a profile's automatic planning
policy, is marked `automatic`. Its summary lists the statements no document
cited that it was asked to place, so automatic planning counts only those no
plan was offered.

A profile whose plan review is `ai` has an AI reviewer approve or dismiss
each proposed item with a reason; the plan's summary keeps each decision
under `reviews`, and an approved item stays proposed until its run can start.

Besides the plans the model makes, each profile may have one standing
`maintenance` plan holding the update items the maintenance worker proposes
for out-of-date documents. It is never the profile's latest plan.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from . import timestamps

SCHEMA = """
CREATE TABLE IF NOT EXISTS documentation_plans (
    id            TEXT PRIMARY KEY,
    guideline_set TEXT NOT NULL,
    audience_id   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    finished_at   TEXT,
    outcome       TEXT CHECK (outcome IN ('planned', 'failed')),
    error         TEXT,
    activity      TEXT,
    provider      TEXT,
    model         TEXT,
    summary       TEXT
);
CREATE INDEX IF NOT EXISTS documentation_plans_profile
    ON documentation_plans (guideline_set, created_at);
CREATE TABLE IF NOT EXISTS documentation_plan_items (
    id                TEXT PRIMARY KEY,
    plan_id           TEXT NOT NULL REFERENCES documentation_plans(id),
    position          INTEGER NOT NULL,
    key               TEXT NOT NULL,
    action            TEXT NOT NULL CHECK (action IN ('create', 'update')),
    title             TEXT NOT NULL,
    document_type     TEXT NOT NULL,
    anchor_entity_id  TEXT,
    document_id       TEXT,
    rationale         TEXT NOT NULL,
    priority          TEXT NOT NULL CHECK (priority IN ('high', 'medium', 'low')),
    statement_ids     TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'proposed'
                      CHECK (state IN ('proposed', 'approved', 'dismissed')),
    decided_at        TEXT,
    decided_by        TEXT,
    run_id            TEXT
);
CREATE INDEX IF NOT EXISTS documentation_plan_items_plan
    ON documentation_plan_items (plan_id, position);
CREATE TABLE IF NOT EXISTS documentation_plan_dismissals (
    guideline_set TEXT NOT NULL,
    key           TEXT NOT NULL,
    title         TEXT NOT NULL,
    dismissed_at  TEXT NOT NULL,
    dismissed_by  TEXT,
    PRIMARY KEY (guideline_set, key)
);
"""

Action = Literal["create", "update"]
#: The provider of a plan an outside agent makes; a restart leaves it waiting.
AGENT = "agent"
Priority = Literal["high", "medium", "low"]


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(documentation_plans)")}
    if "kind" not in columns:
        conn.execute(
            "ALTER TABLE documentation_plans ADD COLUMN kind TEXT NOT NULL "
            "DEFAULT 'model' CHECK (kind IN ('model', 'maintenance'))"
        )
    if "automatic" not in columns:
        conn.execute(
            "ALTER TABLE documentation_plans ADD COLUMN automatic INTEGER NOT NULL "
            "DEFAULT 0"
        )


@dataclass(frozen=True)
class Item:
    key: str
    action: Action
    title: str
    document_type: str
    anchor_entity_id: str | None
    document_id: str | None
    rationale: str
    priority: Priority
    statement_ids: tuple[str, ...]


def create_plan(
    conn: sqlite3.Connection,
    *,
    guideline_set: str,
    audience_id: str,
    created_by: str | None,
    provider: str,
    model: str,
    automatic: bool = False,
) -> str:
    plan_id = "dpl_" + uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO documentation_plans (id, guideline_set, audience_id, created_at, "
        "created_by, activity, provider, model, automatic) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            plan_id,
            guideline_set,
            audience_id,
            timestamps.now(),
            created_by,
            "Queued",
            provider,
            model,
            int(automatic),
        ),
    )
    conn.commit()
    return plan_id


def record_activity(conn: sqlite3.Connection, plan_id: str, activity: str) -> None:
    conn.execute(
        "UPDATE documentation_plans SET activity = ? WHERE id = ?", (activity, plan_id)
    )
    conn.commit()


def finish_plan(
    conn: sqlite3.Connection,
    plan_id: str,
    *,
    items: Sequence[Item] = (),
    error: str | None = None,
    summary: dict[str, object] | None = None,
) -> None:
    with conn:
        for position, item in enumerate(items):
            conn.execute(
                "INSERT INTO documentation_plan_items (id, plan_id, position, key, "
                "action, title, document_type, anchor_entity_id, document_id, "
                "rationale, priority, statement_ids) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "dpi_" + uuid.uuid4().hex[:16],
                    plan_id,
                    position,
                    item.key,
                    item.action,
                    item.title,
                    item.document_type,
                    item.anchor_entity_id,
                    item.document_id,
                    item.rationale,
                    item.priority,
                    json.dumps(list(item.statement_ids)),
                ),
            )
        conn.execute(
            "UPDATE documentation_plans SET finished_at = ?, outcome = ?, error = ?, "
            "activity = NULL, summary = ? WHERE id = ?",
            (
                timestamps.now(),
                "failed" if error is not None else "planned",
                error,
                json.dumps(summary) if summary is not None else None,
                plan_id,
            ),
        )


def active_plan(conn: sqlite3.Connection, guideline_set: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM documentation_plans WHERE guideline_set = ? "
        "AND kind = 'model' AND finished_at IS NULL",
        (guideline_set,),
    ).fetchone()
    return row


def latest_plan(conn: sqlite3.Connection, guideline_set: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM documentation_plans WHERE guideline_set = ? "
        "AND kind = 'model' ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (guideline_set,),
    ).fetchone()
    return row


def latest_planned(conn: sqlite3.Connection, guideline_set: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM documentation_plans WHERE guideline_set = ? "
        "AND kind = 'model' AND outcome = 'planned' "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (guideline_set,),
    ).fetchone()
    return row


def offered(conn: sqlite3.Connection, guideline_set: str) -> set[str]:
    """The uncovered statements any finished plan of the profile was asked
    to place."""
    ids: set[str] = set()
    for row in conn.execute(
        "SELECT summary FROM documentation_plans WHERE guideline_set = ? "
        "AND kind = 'model' AND summary IS NOT NULL",
        (guideline_set,),
    ):
        ids.update(json.loads(row["summary"]).get("uncovered", []))
    return ids


@dataclass(frozen=True)
class StartFailure:
    """Why an item approved without a person could not start its run, and
    how often it failed to."""

    error: str
    attempts: int


def start_failures(plan: sqlite3.Row) -> dict[str, StartFailure]:
    summary = json.loads(plan["summary"]) if plan["summary"] else {}
    return {
        item_id: StartFailure(failure, 1)
        if isinstance(failure, str)
        else StartFailure(**failure)
        for item_id, failure in summary.get("not_started", {}).items()
    }


def record_start_failure(
    conn: sqlite3.Connection, plan_id: str, item_id: str, error: str
) -> None:
    """Note on a plan that one of its items could not start its run, so the
    sweep leaves it for a person, or retries it while the profile's recovery
    attempts last."""
    with conn:
        row = conn.execute(
            "SELECT summary FROM documentation_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        earlier = start_failures(row).get(item_id) if row is not None else None
        summary = json.loads(row["summary"]) if row and row["summary"] else {}
        summary.setdefault("not_started", {})[item_id] = asdict(
            StartFailure(error, 1 if earlier is None else earlier.attempts + 1)
        )
        conn.execute(
            "UPDATE documentation_plans SET summary = ? WHERE id = ?",
            (json.dumps(summary), plan_id),
        )


def failed_in_a_row(conn: sqlite3.Connection, guideline_set: str) -> int:
    """The profile's automatic plans that failed since its last plan that did
    not."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM documentation_plans WHERE guideline_set = ? "
            "AND kind = 'model' AND automatic = 1 AND outcome = 'failed' "
            "AND created_at > COALESCE((SELECT MAX(created_at) FROM "
            "documentation_plans WHERE guideline_set = ? AND kind = 'model' "
            "AND outcome = 'planned'), '')",
            (guideline_set, guideline_set),
        ).fetchone()[0]
    )


@dataclass(frozen=True)
class Review:
    """An AI reviewer's decision on a proposed item."""

    #: None when the review failed and the item waits for a person.
    decision: Literal["approve", "dismiss"] | None
    reason: str
    #: The agent that reviewed it; None for the server's model.
    reviewer: str | None
    at: str
    #: How often a review of the item failed, while it waits.
    failures: int = 0


def record_reviews(conn: sqlite3.Connection, reviews: Mapping[str, Review]) -> None:
    """Keep each item's review in its plan's summary."""
    with conn:
        for item_id, review in reviews.items():
            row = conn.execute(
                "SELECT p.id, p.summary FROM documentation_plan_items i "
                "JOIN documentation_plans p ON p.id = i.plan_id WHERE i.id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                continue
            summary = json.loads(row["summary"]) if row["summary"] else {}
            summary.setdefault("reviews", {})[item_id] = asdict(review)
            conn.execute(
                "UPDATE documentation_plans SET summary = ? WHERE id = ?",
                (json.dumps(summary), row["id"]),
            )


def reviews(plan: sqlite3.Row) -> dict[str, Review]:
    summary = json.loads(plan["summary"]) if plan["summary"] else {}
    return {
        item_id: Review(**review)
        for item_id, review in summary.get("reviews", {}).items()
    }


def get_plan(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM documentation_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    return row


def current_plans(conn: sqlite3.Connection, guideline_set: str) -> list[sqlite3.Row]:
    """The plans whose items the profile's plan shows: its latest finished
    model plan and its maintenance plan."""
    return list(
        conn.execute(
            "SELECT * FROM documentation_plans WHERE guideline_set = ? AND ("
            "kind = 'maintenance' OR id = (SELECT id FROM documentation_plans "
            "WHERE guideline_set = ? AND kind = 'model' AND outcome = 'planned' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1)) ORDER BY kind DESC",
            (guideline_set, guideline_set),
        )
    )


def plans(conn: sqlite3.Connection, guideline_set: str) -> list[sqlite3.Row]:
    """All of a profile's plans, newest model plan first."""
    return list(
        conn.execute(
            "SELECT * FROM documentation_plans WHERE guideline_set = ? "
            "ORDER BY kind, created_at DESC, rowid DESC",
            (guideline_set,),
        )
    )


def maintenance_plan(conn: sqlite3.Connection, guideline_set: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM documentation_plans WHERE guideline_set = ? "
        "AND kind = 'maintenance'",
        (guideline_set,),
    ).fetchone()
    return None if row is None else str(row["id"])


def propose_update(
    conn: sqlite3.Connection, guideline_set: str, audience_id: str, item: Item
) -> None:
    """Add an item to the profile's maintenance plan, creating the plan the
    first time. Does not commit."""
    plan_id = maintenance_plan(conn, guideline_set)
    if plan_id is None:
        plan_id = "dpl_" + uuid.uuid4().hex[:16]
        now = timestamps.now()
        conn.execute(
            "INSERT INTO documentation_plans (id, guideline_set, audience_id, "
            "created_at, finished_at, outcome, kind) "
            "VALUES (?, ?, ?, ?, ?, 'planned', 'maintenance')",
            (plan_id, guideline_set, audience_id, now, now),
        )
    position = conn.execute(
        "SELECT COALESCE(MAX(position) + 1, 0) FROM documentation_plan_items "
        "WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO documentation_plan_items (id, plan_id, position, key, action, "
        "title, document_type, anchor_entity_id, document_id, rationale, priority, "
        "statement_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "dpi_" + uuid.uuid4().hex[:16],
            plan_id,
            position,
            item.key,
            item.action,
            item.title,
            item.document_type,
            item.anchor_entity_id,
            item.document_id,
            item.rationale,
            item.priority,
            json.dumps(list(item.statement_ids)),
        ),
    )


def items(conn: sqlite3.Connection, plan_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM documentation_plan_items WHERE plan_id = ? ORDER BY position",
            (plan_id,),
        )
    )


def unanchored_creates(
    conn: sqlite3.Connection, guideline_set: str
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT i.* FROM documentation_plan_items i "
            "JOIN documentation_plans p ON p.id = i.plan_id "
            "WHERE p.guideline_set = ? AND i.action = 'create' "
            "AND i.anchor_entity_id IS NULL",
            (guideline_set,),
        )
    )


def get_item(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT i.*, p.guideline_set FROM documentation_plan_items i "
        "JOIN documentation_plans p ON p.id = i.plan_id WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    return row


def claim(
    conn: sqlite3.Connection, item_id: str, decided_by: str | None
) -> sqlite3.Row:
    """Mark a proposed item approved, so two approvals cannot both start a
    run for it. Raises when it is not proposed."""
    with conn:
        changed = conn.execute(
            "UPDATE documentation_plan_items SET state = 'approved', decided_at = ?, "
            "decided_by = ? WHERE id = ? AND state = 'proposed'",
            (timestamps.now(), decided_by, item_id),
        ).rowcount
    row = get_item(conn, item_id)
    if row is None:
        raise LookupError("plan item not found")
    if not changed:
        raise ValueError(f"This item was already {row['state']}.")
    return row


def release(conn: sqlite3.Connection, item_id: str) -> None:
    """Undo a claim whose run could not start."""
    with conn:
        conn.execute(
            "UPDATE documentation_plan_items SET state = 'proposed', decided_at = NULL, "
            "decided_by = NULL WHERE id = ? AND run_id IS NULL",
            (item_id,),
        )


def record_run(conn: sqlite3.Connection, item_id: str, run_id: str) -> None:
    with conn:
        conn.execute(
            "UPDATE documentation_plan_items SET run_id = ? WHERE id = ?",
            (run_id, item_id),
        )


def dismiss(
    conn: sqlite3.Connection,
    guideline_set: str,
    key: str,
    title: str,
    dismissed_by: str | None,
    *,
    item_id: str | None = None,
) -> None:
    now = timestamps.now()
    with conn:
        if item_id is not None:
            changed = conn.execute(
                "UPDATE documentation_plan_items SET state = 'dismissed', "
                "decided_at = ?, decided_by = ? WHERE id = ? AND state = 'proposed'",
                (now, dismissed_by, item_id),
            ).rowcount
            if not changed:
                raise ValueError("Only a proposed item can be dismissed.")
        conn.execute(
            "INSERT OR IGNORE INTO documentation_plan_dismissals VALUES (?, ?, ?, ?, ?)",
            (guideline_set, key, title, now, dismissed_by),
        )


def undismiss(conn: sqlite3.Connection, guideline_set: str, key: str) -> bool:
    """Forget a dismissal, so the profile is offered the proposal again."""
    with conn:
        return bool(
            conn.execute(
                "DELETE FROM documentation_plan_dismissals "
                "WHERE guideline_set = ? AND key = ?",
                (guideline_set, key),
            ).rowcount
        )


def dismissed(conn: sqlite3.Connection, guideline_set: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM documentation_plan_dismissals WHERE guideline_set = ? "
            "ORDER BY dismissed_at",
            (guideline_set,),
        )
    )


def mark_orphaned(conn: sqlite3.Connection) -> int:
    """At startup no planning thread exists, so every unfinished plan failed,
    except those an outside agent is making."""
    with conn:
        return conn.execute(
            "UPDATE documentation_plans SET finished_at = ?, outcome = 'failed', "
            "error = 'orphaned by restart', activity = NULL "
            "WHERE finished_at IS NULL AND provider IS NOT 'agent'",
            (timestamps.now(),),
        ).rowcount
