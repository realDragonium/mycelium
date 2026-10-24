"""Work queued for outside agents instead of a server model.

An action whose model setting is External agent calls no model. It queues a
task holding what the work needs: the instructions the internal run would
use, its inputs and the shape of the result. An agent claims tasks over MCP
for `LEASE`, renewed by its next claim of that kind; an expired claim puts
the task back in the pool. The agent submits a result, which passes the same
checks the internal run's output does, or releases the task with a reason.
A submission that fails a check comes back with findings, and the agent may
try again a bounded number of times, which each kind decides.

Each kind owns its brief, its reads and its checks (`docgen.external`,
`documentation_planning`, `audience_labelling`); this module only keeps the
queue. Tasks live in the drafts database beside the documentation runs and
plans most of them complete.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Literal, get_args

from pydantic import BaseModel, JsonValue, TypeAdapter

from . import timestamps

Kind = Literal[
    "documentation",
    "document_review",
    "documentation_planning",
    "audience_labelling",
]
KINDS: tuple[Kind, ...] = get_args(Kind)
Status = Literal["waiting", "claimed", "in_review", "done", "failed"]
LEASE = timedelta(minutes=30)
MAX_BATCH = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    id                TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,
    subject_id        TEXT,
    status            TEXT NOT NULL
                      CHECK (status IN ('waiting', 'claimed', 'in_review', 'done', 'failed')),
    brief             TEXT,
    state             TEXT NOT NULL DEFAULT '{}',
    findings          TEXT NOT NULL DEFAULT '[]',
    failures          INTEGER NOT NULL DEFAULT 0,
    excluded_claimant TEXT,
    claimed_by        TEXT,
    expires_at        TEXT,
    submitted_by      TEXT,
    release_reason    TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    finished_at       TEXT,
    error             TEXT
);
CREATE INDEX IF NOT EXISTS agent_tasks_open
    ON agent_tasks (kind, created_at) WHERE finished_at IS NULL;
CREATE INDEX IF NOT EXISTS agent_tasks_subject ON agent_tasks (subject_id);
"""

_state = TypeAdapter(dict[str, JsonValue])


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


class Finding(BaseModel):
    """One reason a submission was refused, for the agent to fix."""

    #: Which check refused it: `grounding`, `shape`, `exposure`,
    #: `conformance`, `labels`, ...
    check: str
    #: Where in the result the problem is, when the check can say.
    where: str | None = None
    problem: str


_findings = TypeAdapter(list[Finding])


class Task(BaseModel):
    id: str
    kind: Kind
    #: The documentation run or plan the task completes; None for labelling.
    subject_id: str | None
    status: Status
    #: What the agent is given; None until the first claim prepares it.
    brief: dict[str, JsonValue] | None
    #: What the server keeps between calls: what the agent read, attempts.
    state: dict[str, JsonValue]
    #: The last refused submission's findings.
    findings: list[Finding]
    #: How many submissions were refused.
    failures: int
    #: A principal that may not claim the task: a review's writer.
    excluded_claimant: str | None
    claimed_by: str | None
    expires_at: str | None
    submitted_by: str | None
    release_reason: str | None
    created_at: str
    updated_at: str
    finished_at: str | None
    error: str | None


class View(BaseModel):
    """A task as an operator sees it beside the run, plan or queue it serves."""

    id: str
    kind: Kind
    status: Status
    claimed_by: str | None
    expires_at: str | None
    failures: int
    findings: list[Finding]
    release_reason: str | None
    updated_at: str
    error: str | None


def _task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        kind=row["kind"],
        subject_id=row["subject_id"],
        status=row["status"],
        brief=None if row["brief"] is None else _state.validate_json(row["brief"]),
        state=_state.validate_json(row["state"]),
        findings=_findings.validate_json(row["findings"]),
        failures=row["failures"],
        excluded_claimant=row["excluded_claimant"],
        claimed_by=row["claimed_by"],
        expires_at=row["expires_at"],
        submitted_by=row["submitted_by"],
        release_reason=row["release_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
        error=row["error"],
    )


def view(task: Task) -> View:
    return current(View.model_validate(task.model_dump(include=set(View.model_fields))))


def current(stored: View, *, now: str | None = None) -> View:
    """`stored` as it stands now: a claim whose lease ran out reads as
    waiting, since the next claim frees it."""
    if stored.status != "claimed" or (stored.expires_at or "") > (
        now or timestamps.now()
    ):
        return stored
    return stored.model_copy(
        update={"status": "waiting", "claimed_by": None, "expires_at": None}
    )


#: The newest task serving run `r`, as a `View`'s JSON, for run listings.
VIEW_SQL = (
    "(SELECT json_object('id', t.id, 'kind', t.kind, 'status', t.status, "
    "'claimed_by', t.claimed_by, 'expires_at', t.expires_at, "
    "'failures', t.failures, 'findings', json(t.findings), "
    "'release_reason', t.release_reason, 'updated_at', t.updated_at, "
    "'error', t.error) FROM agent_tasks AS t WHERE t.subject_id = {subject} "
    "ORDER BY t.created_at DESC, t.rowid DESC LIMIT 1)"
)


def parse_view(text: str | None) -> View | None:
    return None if text is None else current(View.model_validate_json(text))


def create(
    conn: sqlite3.Connection,
    kind: Kind,
    *,
    subject_id: str | None,
    state: dict[str, JsonValue],
    brief: dict[str, JsonValue] | None = None,
    excluded_claimant: str | None = None,
) -> str:
    """Queue a task."""
    task_id = "agt_" + uuid.uuid4().hex[:16]
    now = timestamps.now()
    conn.execute(
        "INSERT INTO agent_tasks (id, kind, subject_id, status, brief, state, "
        "excluded_claimant, created_at, updated_at) "
        "VALUES (?, ?, ?, 'waiting', ?, ?, ?, ?, ?)",
        (
            task_id,
            kind,
            subject_id,
            None if brief is None else json.dumps(brief),
            json.dumps(state),
            excluded_claimant,
            now,
            now,
        ),
    )
    conn.commit()
    return task_id


def get(conn: sqlite3.Connection, task_id: str) -> Task | None:
    row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    return None if row is None else _task(row)


def latest_for(conn: sqlite3.Connection, subject_id: str) -> Task | None:
    """The newest task serving `subject_id`: a run's review task once its
    writing task is in review."""
    row = conn.execute(
        "SELECT * FROM agent_tasks WHERE subject_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (subject_id,),
    ).fetchone()
    return None if row is None else _task(row)


def open_tasks(conn: sqlite3.Connection, kind: Kind) -> list[Task]:
    return [
        _task(row)
        for row in conn.execute(
            "SELECT * FROM agent_tasks WHERE kind = ? AND finished_at IS NULL "
            "ORDER BY created_at, rowid",
            (kind,),
        )
    ]


def open_subjects(conn: sqlite3.Connection) -> set[str]:
    """Runs and plans an unfinished task still serves; a restart must not
    fail them, since their work happens outside this process."""
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT subject_id FROM agent_tasks "
            "WHERE finished_at IS NULL AND subject_id IS NOT NULL"
        )
    }


def claim(
    conn: sqlite3.Connection,
    kind: Kind,
    *,
    claimant: str,
    limit: int,
    now: datetime,
) -> tuple[list[Task], list[str], str]:
    """Lease up to `limit` waiting tasks of `kind` to `claimant`, oldest
    first, and extend the lease on those of that kind it already holds.

    Returns the new tasks, the ids renewed and when the lease ends."""
    stamp = timestamps.of(now)
    expires = timestamps.of(now + LEASE)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE agent_tasks SET status = 'waiting', claimed_by = NULL, "
            "expires_at = NULL, updated_at = ? "
            "WHERE status = 'claimed' AND expires_at <= ?",
            (stamp, stamp),
        )
        renewed = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM agent_tasks WHERE status = 'claimed' "
                "AND kind = ? AND claimed_by = ? ORDER BY created_at, rowid",
                (kind, claimant),
            )
        ]
        conn.execute(
            "UPDATE agent_tasks SET expires_at = ? "
            "WHERE status = 'claimed' AND kind = ? AND claimed_by = ?",
            (expires, kind, claimant),
        )
        ids = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM agent_tasks WHERE status = 'waiting' AND kind = ? "
                "AND excluded_claimant IS NOT ? ORDER BY created_at, rowid LIMIT ?",
                (kind, claimant, limit),
            )
        ]
        conn.executemany(
            "UPDATE agent_tasks SET status = 'claimed', claimed_by = ?, "
            "expires_at = ?, release_reason = NULL, updated_at = ? WHERE id = ?",
            [(claimant, expires, stamp, task_id) for task_id in ids],
        )
    chosen = [task for task_id in ids if (task := get(conn, task_id)) is not None]
    return chosen, renewed, expires


class NotHeld(PermissionError):
    pass


def held(conn: sqlite3.Connection, task_id: str, claimant: str) -> Task:
    """The task, if `claimant` holds an unexpired claim on it."""
    task = get(conn, task_id)
    if task is None:
        raise ValueError(f"agent task '{task_id}' does not exist")
    if (
        task.status != "claimed"
        or task.claimed_by != claimant
        or (task.expires_at or "") <= timestamps.now()
    ):
        raise NotHeld(
            f"agent task '{task_id}' is not claimed by you; claim it with "
            "claim_agent_task first"
        )
    return task


def save(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    brief: dict[str, JsonValue] | None = None,
    state: dict[str, JsonValue] | None = None,
    findings: list[Finding] | None = None,
    failures: int | None = None,
    submitted_by: str | None = None,
) -> None:
    """Record what a call changed on an unfinished task."""
    conn.execute(
        "UPDATE agent_tasks SET brief = COALESCE(?, brief), "
        "state = COALESCE(?, state), findings = COALESCE(?, findings), "
        "failures = COALESCE(?, failures), "
        "submitted_by = COALESCE(?, submitted_by), updated_at = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (
            None if brief is None else json.dumps(brief),
            None if state is None else json.dumps(state),
            None if findings is None else _findings.dump_json(findings).decode(),
            failures,
            submitted_by,
            timestamps.now(),
            task_id,
        ),
    )
    conn.commit()


def set_status(
    conn: sqlite3.Connection,
    task_id: str,
    status: Literal["waiting", "in_review"],
    *,
    release_reason: str | None = None,
) -> None:
    """Hand a task back to the pool, or hold it while its result is reviewed;
    either ends the claim."""
    conn.execute(
        "UPDATE agent_tasks SET status = ?, claimed_by = NULL, expires_at = NULL, "
        "release_reason = ?, updated_at = ? WHERE id = ? AND finished_at IS NULL",
        (status, release_reason, timestamps.now(), task_id),
    )
    conn.commit()


def finish(
    conn: sqlite3.Connection,
    task_id: str,
    status: Literal["done", "failed"],
    *,
    error: str | None = None,
) -> None:
    now = timestamps.now()
    conn.execute(
        "UPDATE agent_tasks SET status = ?, claimed_by = NULL, expires_at = NULL, "
        "error = ?, finished_at = ?, updated_at = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (status, error, now, now, task_id),
    )
    conn.commit()


class Submitted(BaseModel):
    """What came of a submission, as the agent is told."""

    task_id: str
    #: `accepted`: done. `refused`: fix the findings and submit again while
    #: `retries_left` lasts. `in_review`: another agent reviews it next.
    #: `failed`: the task is closed and nothing was kept.
    status: Literal["accepted", "refused", "in_review", "failed"]
    findings: list[Finding] = []
    retries_left: int = 0
    message: str


#: The calls an agent makes, named in every brief.
PROTOCOL = (
    "You are doing work this server would otherwise give its own model. The "
    "brief's `instructions` are that model's system prompt and `input` its "
    "first message; follow them exactly. They name tools in the model's "
    "terms. Call a read tool with read_for_agent_task(task_id, tool, "
    "arguments): only those reads count as read for this task. Report a "
    "knowledge gap with report_knowledge_gap. Hand in the result, shaped as "
    "`result_schema`, with submit_agent_task(task_id, result): that is the "
    "final tool call the instructions name. A refused submission returns "
    "findings; fix them and submit again. Give the task back with "
    "release_agent_task when you cannot finish it."
)
