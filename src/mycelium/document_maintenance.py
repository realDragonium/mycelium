"""Keeping generated documents up to date by themselves.

The same sweep also plans for profiles whose planning policy is not `off`
(`documentation_planning.plan_automatically`), has an AI reviewer decide
the plan items of profiles whose plan review is `ai`
(`documentation_plan_review`), retries the runs that wrote nothing of
profiles whose recovery is `ai`, and publishes what profiles whose delivery
is `auto` wrote. Each finished run is decided once, for both, from the
database: whether it was retried and whether it was published.

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
    documentation_plan_review,
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
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(document_maintenance)")
    }
    if "attempts" not in columns:
        # Automatic revisions that could not start their run.
        conn.execute(
            "ALTER TABLE document_maintenance ADD COLUMN attempts INTEGER "
            "NOT NULL DEFAULT 0"
        )


def mark_interrupted(conn: sqlite3.Connection) -> None:
    """At startup nothing is starting or publishing, so a claim left without
    its outcome was cut off by the restart. It is reported, not repeated."""
    interrupted = (
        "interrupted by restart while publishing; publish it from the document"
    )
    with conn:
        conn.execute(
            "UPDATE document_maintenance SET error = 'interrupted by restart "
            "before its run started', attempts = attempts + 1 "
            "WHERE action = 'auto-revise' AND run_id IS NULL AND error IS NULL"
        )
        conn.execute(
            "UPDATE document_maintenance SET delivery = 'failed', error = ? "
            "WHERE delivery = 'publishing'",
            (interrupted,),
        )
        conn.execute(
            "UPDATE documentation_runs SET delivery = 'failed', delivery_error = ? "
            "WHERE delivery = 'publishing'",
            (interrupted,),
        )


# --- the sweep -----------------------------------------------------------------


@request_timing.tracked("background maintenance sweep")
def sweep(now: datetime | None = None) -> list[str]:
    """Act on every out-of-date document of a profile that is not maintained
    by hand, publish finished automatic revisions, and plan for profiles
    that plan by themselves. Returns the ids of the runs it started."""
    from . import server

    now = now or datetime.now(UTC)
    drafts = drafts_store.connection()
    limits = product_settings.get(product_settings.DocumentationMaintenanceSettings)
    max_active = product_settings.get(
        product_settings.ConcurrencySettings
    ).documentation_runs
    snapshot = documentation_profiles.capture()
    _deliver_finished(drafts, snapshot, limits.delivery_retries)
    # Without credentials a revision would only fail, so the document waits
    # unclaimed and is revised once they are configured.
    can_revise = model_settings.credentials_error("docgen") is None
    started: list[str] = []
    for profile in snapshot.profiles:
        audience = snapshot.audience(profile.name)
        # An AI reviewer decides out-of-date documents a person would
        # otherwise notice, so they are proposed to it.
        if audience is None or (
            profile.maintenance == "manual" and profile.plan_review == "person"
        ):
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
                or _awaiting_labels(document, audience.id)
            ):
                continue
            row = _observe(drafts, profile.name, document, now)
            if (
                profile.recovery == "ai"
                and row["action"] == "auto-revise"
                and row["run_id"] is None
                and row["error"] is not None
                and row["attempts"] <= limits.revision_start_retries
            ):
                _record(drafts, document.id, document.revision, action=None)
            elif row["action"] is not None:
                continue
            if profile.maintenance != "auto-revise":
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
    started += documentation_planning.plan_automatically(
        drafts, store.substrate_connection(), snapshot
    )
    started += documentation_plan_review.sweep(snapshot)
    started += _retry_finished(drafts, snapshot, limits.run_retries, max_active)
    return started


def _awaiting_labels(document: ExistingDocument, audience_id: str) -> bool:
    """An edit drops a statement's AI label until it is labelled again, and
    the new label's grant to an external audience may wait for a curator, so
    until then the edit looks like the statement was hidden from the
    audience. Acting on that would remove the fact instead of updating it."""

    hidden = [
        change.statement_id
        for change in document.freshness.changes
        if change.change == "no_longer_visible"
    ]
    return bool(hidden) and bool(
        store.audience_labels.awaiting_label(
            store.substrate_connection(), hidden, audience_id
        )
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
        with conn:
            conn.execute(
                "UPDATE document_maintenance SET error = ?, attempts = attempts + 1 "
                "WHERE document_id = ? AND revision = ?",
                (str(exc), document.id, document.revision),
            )
        return None
    _record(conn, document.id, document.revision, run_id=run_id, error=None)
    return run_id


def _record(
    conn: sqlite3.Connection,
    document_id: str,
    revision: int,
    **values: str | int | None,
) -> None:
    columns = ", ".join(f"{column} = ?" for column in values)
    with conn:
        conn.execute(
            f"UPDATE document_maintenance SET {columns} "
            "WHERE document_id = ? AND revision = ?",
            (*values.values(), document_id, revision),
        )


def _deliver_finished(
    conn: sqlite3.Connection,
    snapshot: documentation_profiles.CatalogueSnapshot,
    retries: int,
) -> None:
    """Publish each finished run's revision that is published automatically,
    while it is still its document's current one: under `auto` delivery,
    to where the document was published before or the profile's
    destination; and an automatic revision of a document published before,
    whatever the delivery, to the same destination. That opens or updates
    the pull request; the destination repository merges it. A failed
    publication is tried again while the profile's recovery attempts last."""
    profiles = {profile.name: profile for profile in snapshot.profiles}
    rows = conn.execute(
        "SELECT r.id, r.guideline_set, r.outcome, r.result_revision, "
        "r.delivery_attempts, d.id AS document_id, d.current_revision, "
        "d.delivery_destination, m.action AS maintenance "
        "FROM documentation_runs r "
        "LEFT JOIN generated_documents d ON d.id = r.document_id "
        "LEFT JOIN document_maintenance m ON m.run_id = r.id "
        "WHERE r.delivery IS NULL AND r.finished_at IS NOT NULL"
    ).fetchall()
    for row in rows:
        run_id = str(row["id"])
        profile = profiles.get(str(row["guideline_set"] or ""))
        destination = row["delivery_destination"] or (
            profile.delivery_destination
            if profile is not None and profile.delivery == "auto"
            else None
        )
        automatic = (profile is not None and profile.delivery == "auto") or row[
            "maintenance"
        ] == "auto-revise"
        if (
            row["outcome"] != "document_written"
            or not automatic
            or not destination
            or row["result_revision"] != row["current_revision"]
        ):
            _delivered(conn, run_id, "none")
            continue
        with conn:
            claimed = conn.execute(
                "UPDATE documentation_runs SET delivery = 'publishing' "
                "WHERE id = ? AND delivery IS NULL",
                (run_id,),
            ).rowcount
        if not claimed:
            continue
        _delivered(conn, run_id, "publishing")
        try:
            publication.publish(
                conn,
                str(row["document_id"]),
                str(destination),
                int(row["result_revision"]),
            )
        except Exception as exc:
            logger.warning("could not publish %s", row["document_id"], exc_info=True)
            attempts = int(row["delivery_attempts"]) + 1
            again = profile is not None and profile.recovery == "ai"
            again = again and attempts <= retries
            _delivered(conn, run_id, None if again else "failed", str(exc), attempts)
        else:
            _delivered(conn, run_id, "published")


def _delivered(
    conn: sqlite3.Connection,
    run_id: str,
    delivery: str | None,
    error: str | None = None,
    attempts: int | None = None,
) -> None:
    """Record what came of publishing a run's revision, on the run and on
    the automatic revision it made, if it made one. No delivery leaves the
    run to be published on the next sweep."""
    with conn:
        conn.execute(
            "UPDATE documentation_runs SET delivery = ?, delivery_error = ?, "
            "delivery_attempts = COALESCE(?, delivery_attempts) WHERE id = ?",
            (delivery, error, attempts, run_id),
        )
        conn.execute(
            "UPDATE document_maintenance SET delivery = ?, "
            "error = COALESCE(?, error) WHERE run_id = ?",
            (delivery, error, run_id),
        )


def _retry_finished(
    conn: sqlite3.Connection,
    snapshot: documentation_profiles.CatalogueSnapshot,
    retries: int,
    max_active: int,
) -> list[str]:
    """Start again each finished run that wrote nothing, of a profile whose
    recovery is `ai`, while the active-run limit has room: briefed with the
    review's findings when the review refused it. After `retries` automatic
    retries it is given up with a reason. Returns the ids of the runs
    started."""
    from . import document_edits, server

    recovering = {
        profile.name for profile in snapshot.profiles if profile.recovery == "ai"
    }
    can_run = model_settings.credentials_error("docgen") is None
    started: list[str] = []
    for row in conn.execute(
        "SELECT id, guideline_set, outcome, prompt, provider, attempt, summary, "
        "error FROM documentation_runs WHERE recovery IS NULL "
        "AND finished_at IS NOT NULL ORDER BY finished_at"
    ).fetchall():
        run_id = str(row["id"])
        if (
            row["outcome"] == "document_written"
            or row["guideline_set"] not in recovering
            or row["prompt"] == document_edits.MANUAL_EDIT_PROMPT
        ):
            _recovered(conn, run_id, "none")
            continue
        if int(row["attempt"]) >= retries:
            _recovered(
                conn,
                run_id,
                "gave_up",
                f"Gave up after {row['attempt']} automatic "
                f"retr{'y' if row['attempt'] == 1 else 'ies'}: {row['error']}"
                if row["attempt"]
                else f"Gave up without an automatic retry: {row['error']}",
            )
            continue
        if (not can_run and row["provider"] != "agent") or docs_store.count_active(
            conn
        ) >= max_active:
            continue
        notes = bool(
            row["summary"] and json.loads(row["summary"]).get("review_findings")
        )
        try:
            run = server.retry_documentation_run(
                run_id, with_review_notes=notes, automatic=True
            )
        except Exception as exc:
            logger.warning("could not retry %s", run_id, exc_info=True)
            _recovered(conn, run_id, "gave_up", f"Could not retry it: {exc}")
            continue
        started.append(str(run["id"]))
    return started


def _recovered(
    conn: sqlite3.Connection, run_id: str, recovery: str, note: str | None = None
) -> None:
    with conn:
        conn.execute(
            "UPDATE documentation_runs SET recovery = ?, recovery_note = ? "
            "WHERE id = ? AND recovery IS NULL",
            (recovery, note, run_id),
        )


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
