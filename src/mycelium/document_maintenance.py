"""Keeping generated documents up to date by themselves.

Each writing profile has a maintenance policy (`documentation_profiles`):
`manual` leaves an out-of-date document for someone to notice, `propose`
adds an update item to the profile's plan, and `auto-revise` starts the
revision itself and then publishes it the way a person would.

A periodic sweep, on the pattern of the draft-review sweeper, decides from
what the database holds, so a restart neither forgets nor repeats a
decision. One row per out-of-date revision records the changes last seen,
when they were first seen (the quiet period counts from there, so a burst of
edits resets it and causes one revision), and what was done about it. That
row is claimed before a run starts, so the same revision is acted on once;
a failed automatic revision waits for a person or for the next revision.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from . import (
    doc_plans,
    doc_runs,
    docs_store,
    document_freshness,
    documentation_planning,
    documentation_profiles,
    drafts_store,
    model_settings,
    product_settings,
    request_timing,
    store,
    timestamps,
    workers,
)
from .docgen import publication
from .documentation_planning import ExistingDocument, stale_key

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS document_maintenance (
    document_id   TEXT NOT NULL,
    revision      INTEGER NOT NULL,
    guideline_set TEXT NOT NULL,
    changes       TEXT NOT NULL,
    changed_at    TEXT NOT NULL,
    action        TEXT CHECK (action IN ('propose', 'auto-revise')),
    acted_at      TEXT,
    run_id        TEXT,
    error         TEXT,
    delivery      TEXT CHECK (delivery IN ('none', 'publishing', 'published', 'failed')),
    PRIMARY KEY (document_id, revision)
);
CREATE INDEX IF NOT EXISTS document_maintenance_acted
    ON document_maintenance (guideline_set, acted_at);
"""

Action = Literal["propose", "auto-revise"]


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def mark_interrupted(conn: sqlite3.Connection) -> None:
    """At startup nothing is starting or publishing, so a claim left without
    its outcome was cut off by the restart. It is reported, not repeated."""
    with conn:
        conn.execute(
            "UPDATE document_maintenance SET error = 'interrupted by restart "
            "before its run started' WHERE action = 'auto-revise' "
            "AND run_id IS NULL AND error IS NULL"
        )
        conn.execute(
            "UPDATE document_maintenance SET delivery = 'failed', error = "
            "'interrupted by restart while publishing; publish it from the "
            "document' WHERE delivery = 'publishing'"
        )


# --- the sweep -----------------------------------------------------------------


@request_timing.tracked("background maintenance sweep")
def sweep(now: datetime | None = None) -> list[str]:
    """Act on every out-of-date document of a profile that is not maintained
    by hand, and publish finished automatic revisions. Returns the ids of
    the runs it started."""
    from . import server

    now = now or datetime.now(UTC)
    drafts = drafts_store.connection()
    _publish_finished(drafts)
    limits = product_settings.get(product_settings.DocumentationMaintenanceSettings)
    max_active = product_settings.get(
        product_settings.ConcurrencySettings
    ).documentation_runs
    snapshot = documentation_profiles.capture()
    # Without credentials a revision would only fail, so the document waits
    # unclaimed and is revised once they are configured.
    can_revise = model_settings.credentials_error("docgen") is None
    started: list[str] = []
    for profile in snapshot.profiles:
        audience = snapshot.audience(profile.name)
        if profile.maintenance == "manual" or audience is None:
            continue
        dismissed = {
            str(row["key"]) for row in doc_plans.dismissed(drafts, profile.name)
        }
        templates = {template.name for template in profile.templates}
        for document in documentation_planning.profile_documents(
            drafts, server._db, profile.name
        ):
            if (
                document.freshness.status != "out_of_date"
                or stale_key(document) in dismissed
                or _awaiting_labels(document)
            ):
                continue
            row = _observe(drafts, profile.name, document, now)
            if row["action"] is not None:
                continue
            if profile.maintenance == "propose":
                _propose(drafts, profile.name, audience.id, document, now)
                continue
            if (
                not can_revise
                or now - datetime.fromisoformat(row["changed_at"])
                < timedelta(minutes=limits.quiet_minutes)
                or _revisions_today(drafts, profile.name, now)
                >= limits.revisions_per_day
                or docs_store.count_active(drafts) >= max_active
            ):
                continue
            run_id = _revise(drafts, profile.name, document, templates, now)
            if run_id is not None:
                started.append(run_id)
    return started


def _awaiting_labels(document: ExistingDocument) -> bool:
    """An edit drops a statement's AI label until it is labelled again, so
    until then the edit looks like the statement was hidden from the
    audience. Acting on that would remove the fact instead of updating it."""

    hidden = [
        change.statement_id
        for change in document.freshness.changes
        if change.change == "no_longer_visible"
    ]
    return bool(hidden) and bool(
        store.audience_labels.awaiting_label(store.substrate_connection(), hidden)
    )


def _observe(
    conn: sqlite3.Connection,
    guideline_set: str,
    document: ExistingDocument,
    now: datetime,
) -> sqlite3.Row:
    """Record the document's changes; new changes restart the quiet period
    until something was done about the revision."""
    changes = json.dumps(
        [asdict(change) for change in document.freshness.changes]
        + [asdict(change) for change in document.freshness.media_changes]
    )
    stamp = timestamps.of(now)
    with conn:
        conn.execute(
            "INSERT INTO document_maintenance (document_id, revision, guideline_set, "
            "changes, changed_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (document_id, revision) DO UPDATE SET "
            "changes = excluded.changes, changed_at = excluded.changed_at "
            "WHERE action IS NULL AND changes != excluded.changes",
            (document.id, document.revision, guideline_set, changes, stamp),
        )
    row: sqlite3.Row = conn.execute(
        "SELECT * FROM document_maintenance WHERE document_id = ? AND revision = ?",
        (document.id, document.revision),
    ).fetchone()
    return row


def _claim(
    conn: sqlite3.Connection, document: ExistingDocument, action: Action, now: datetime
) -> bool:
    changed = conn.execute(
        "UPDATE document_maintenance SET action = ?, acted_at = ? "
        "WHERE document_id = ? AND revision = ? AND action IS NULL",
        (action, timestamps.of(now), document.id, document.revision),
    ).rowcount
    return bool(changed)


def _propose(
    conn: sqlite3.Connection,
    guideline_set: str,
    audience_id: str,
    document: ExistingDocument,
    now: datetime,
) -> None:
    with conn:
        if not _claim(conn, document, "propose", now):
            return
        doc_plans.propose_update(
            conn,
            guideline_set,
            audience_id,
            doc_plans.Item(
                key=stale_key(document),
                action="update",
                title=document.title,
                document_type=document.document_type,
                anchor_entity_id=document.anchor_entity_id,
                document_id=document.id,
                rationale=document_freshness.revision_brief(
                    document.freshness.changes, document.freshness.media_changes
                ),
                priority="high",
                statement_ids=tuple(
                    change.statement_id for change in document.freshness.changes
                ),
            ),
        )


def _revisions_today(
    conn: sqlite3.Connection, guideline_set: str, now: datetime
) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM document_maintenance WHERE guideline_set = ? "
            "AND action = 'auto-revise' AND acted_at > ?",
            (guideline_set, timestamps.of(now - timedelta(days=1))),
        ).fetchone()[0]
    )


def _revise(
    conn: sqlite3.Connection,
    guideline_set: str,
    document: ExistingDocument,
    templates: set[str],
    now: datetime,
) -> str | None:
    with conn:
        if not _claim(conn, document, "auto-revise", now):
            return None
    try:
        if document.document_type not in templates:
            raise ValueError(
                f"The profile no longer has the '{document.document_type}' template."
            )
        run_id = doc_runs.start_run(
            prompt=document_freshness.revision_brief(
                document.freshness.changes, document.freshness.media_changes
            ),
            guideline_set=guideline_set,
            document_type=document.document_type,
            created_by=None,
            conn=conn,
            target_document_id=document.id,
            expected_revision=document.revision,
        )
    except Exception as exc:
        logger.warning("could not revise %s automatically", document.id, exc_info=True)
        _record(conn, document.id, document.revision, error=str(exc))
        return None
    _record(conn, document.id, document.revision, run_id=run_id)
    return run_id


def _record(
    conn: sqlite3.Connection, document_id: str, revision: int, **values: str | None
) -> None:
    columns = ", ".join(f"{column} = ?" for column in values)
    with conn:
        conn.execute(
            f"UPDATE document_maintenance SET {columns} "
            "WHERE document_id = ? AND revision = ?",
            (*values.values(), document_id, revision),
        )


def _publish_finished(conn: sqlite3.Connection) -> None:
    """Publish each automatic revision whose document was published before,
    to the same destination: that updates its open pull request or opens a
    new one, and a person still merges it."""
    rows = conn.execute(
        "SELECT m.document_id, m.revision, r.outcome, r.result_revision, "
        "d.delivery_destination FROM document_maintenance m "
        "JOIN documentation_runs r ON r.id = m.run_id "
        "LEFT JOIN generated_documents d ON d.id = m.document_id "
        "WHERE m.delivery IS NULL AND r.finished_at IS NOT NULL"
    ).fetchall()
    for row in rows:
        document_id, revision = str(row["document_id"]), int(row["revision"])
        if row["outcome"] != "document_written" or not row["delivery_destination"]:
            _record(conn, document_id, revision, delivery="none")
            continue
        with conn:
            claimed = conn.execute(
                "UPDATE document_maintenance SET delivery = 'publishing' "
                "WHERE document_id = ? AND revision = ? AND delivery IS NULL",
                (document_id, revision),
            ).rowcount
        if not claimed:
            continue
        try:
            publication.publish(
                conn,
                document_id,
                str(row["delivery_destination"]),
                int(row["result_revision"]),
            )
        except Exception as exc:
            logger.warning("could not publish %s", document_id, exc_info=True)
            _record(conn, document_id, revision, delivery="failed", error=str(exc))
        else:
            _record(conn, document_id, revision, delivery="published")


# --- what people are told --------------------------------------------------------

State = Literal[
    "proposed", "approved", "dismissed", "running", "revised", "refused", "failed"
]

#: How far back the list reaches for entries that no longer wait on anyone.
_HISTORY = timedelta(days=30)


class PullRequest(BaseModel):
    number: int
    url: str | None
    state: str | None


class Entry(BaseModel):
    document_id: str
    title: str
    guideline_set: str
    #: The revision that went out of date.
    revision: int
    action: Action
    state: State
    #: When the entry last changed: a revision's finish, otherwise the action.
    at: str
    changes: list[dict[str, object]]
    run_id: str | None
    #: The revision an automatic run wrote, diffed against `revision`.
    new_revision: int | None
    error: str | None
    delivery: str | None
    pull_request: PullRequest | None
    #: A person is needed: to approve a proposal, merge a pull request, or
    #: revise a document an automatic revision did not bring up to date.
    waiting: bool


class Feed(BaseModel):
    entries: list[Entry]


def feed(conn: sqlite3.Connection, now: datetime | None = None) -> Feed:
    now = now or datetime.now(UTC)
    rows = conn.execute(
        "SELECT m.*, d.title, d.current_revision, d.pull_request_number, "
        "d.pull_request_state, d.delivery_reference, "
        "r.finished_at, r.outcome, r.result_revision, r.started_at, "
        "i.state AS item_state "
        "FROM document_maintenance m "
        "JOIN generated_documents d ON d.id = m.document_id "
        "LEFT JOIN documentation_runs r ON r.id = m.run_id "
        "LEFT JOIN documentation_plans p ON p.guideline_set = m.guideline_set "
        "AND p.kind = 'maintenance' "
        "LEFT JOIN documentation_plan_items i ON i.plan_id = p.id "
        "AND i.key = 'stale:' || m.document_id || ':r' || m.revision "
        "WHERE m.action IS NOT NULL ORDER BY m.acted_at DESC"
    ).fetchall()
    since = timestamps.of(now - _HISTORY)
    entries = [_entry(row) for row in rows]
    return Feed(
        entries=[entry for entry in entries if entry.waiting or entry.at >= since][:100]
    )


def _state(row: sqlite3.Row) -> State:
    if row["action"] == "propose":
        state = row["item_state"]
        return (
            "dismissed"
            if state == "dismissed"
            else ("approved" if state == "approved" else "proposed")
        )
    if row["run_id"] is None:
        return "failed"
    if row["finished_at"] is None:
        return "running"
    if row["outcome"] == "document_written":
        return "revised"
    return "refused" if row["outcome"] == "nothing_written" else "failed"


def _entry(row: sqlite3.Row) -> Entry:
    state = _state(row)
    unrevised = int(row["current_revision"]) == int(row["revision"])
    pull_request = (
        PullRequest(
            number=int(row["pull_request_number"]),
            url=row["delivery_reference"],
            state=row["pull_request_state"],
        )
        if row["pull_request_number"] is not None
        else None
    )
    waiting = (
        (state in ("proposed", "refused", "failed") and unrevised)
        or (
            state == "revised"
            and row["delivery"] == "published"
            and pull_request is not None
            and pull_request.state == "open"
        )
        or (state == "revised" and row["delivery"] == "failed")
    )
    return Entry(
        document_id=str(row["document_id"]),
        title=str(row["title"]),
        guideline_set=str(row["guideline_set"]),
        revision=int(row["revision"]),
        action=row["action"],
        state=state,
        at=str(row["finished_at"] or row["acted_at"]),
        changes=json.loads(row["changes"]),
        run_id=row["run_id"],
        new_revision=row["result_revision"] if state == "revised" else None,
        error=row["error"],
        delivery=row["delivery"],
        pull_request=pull_request,
        waiting=waiting,
    )


# --- worker --------------------------------------------------------------------

SWEEP_INTERVAL_S = 60.0
_worker = workers.Worker(
    "document-maintenance",
    lambda _: sweep(),
    interval=SWEEP_INTERVAL_S,
    session=workers.no_session,
    delay_first=True,
)


def start() -> None:
    _worker.start()


def stop(timeout: float = 5.0) -> None:
    _worker.stop(timeout)
