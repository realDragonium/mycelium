"""Durable internal review attempts, separate from authoritative draft reviews."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from typing_extensions import TypedDict

from . import ai_prompts, timestamps
from .ai.types import ReasoningEffort

Mode = Literal["off", "review-only", "review-and-apply"]


class Precondition(TypedDict):
    kind: Literal["entity", "statement"]
    id: str
    fingerprint: str


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["revise", "strike", "append"]
    operation_ref: str | None
    tool_name: str | None
    payload_json: str | None
    reason: str = Field(min_length=1, max_length=2000)


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: Literal["good", "changes_suggested", "reject", "needs_context"]
    rationale: str = Field(min_length=1, max_length=6000)
    questions: list[str] = Field(max_length=12)
    corrections: list[Correction] = Field(max_length=8)


class ReviewRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    draft_id: str
    status: Literal["running", "completed", "failed"] = "running"
    mode: Mode
    draft_revision: int
    provider: Literal["claude", "openai"] | None = None
    model: str | None = None
    prompt: ai_prompts.Reference | None = None
    reasoning_effort: ReasoningEffort | None = None
    reviewer_id: str | None = None
    settings_revision: int | None = None
    model_settings_revision: int | None = None
    review_id: str | None = None
    stale: bool = False
    knowledge_preconditions: list[Precondition] = Field(default_factory=list)
    label: Literal["good", "changes_suggested", "reject", "needs_context"] | None = None
    rationale: str | None = None
    questions: list[str] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    application: Literal["unapplied", "applied", "rejected"] = "unapplied"
    detail: str | None = None
    started_at: str = Field(default_factory=timestamps.now)
    finished_at: str | None = None


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS draft_review_runs (
            id TEXT PRIMARY KEY,
            draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            body_json TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS draft_review_run_active
        ON draft_review_runs(draft_id) WHERE status = 'running';
    """)


def latest(conn: sqlite3.Connection, draft_id: str) -> ReviewRun | None:
    row = conn.execute(
        "SELECT review_assessment_json, revision FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    if row is None or row["review_assessment_json"] is None:
        return None
    run = ReviewRun.model_validate_json(row["review_assessment_json"])
    run.stale = run.draft_revision != row["revision"]
    return run


def get(conn: sqlite3.Connection, run_id: str) -> ReviewRun:
    row = conn.execute(
        "SELECT r.body_json, d.revision FROM draft_review_runs r "
        "JOIN drafts d ON d.id = r.draft_id WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError("draft review run not found")
    run = ReviewRun.model_validate_json(row["body_json"])
    run.stale = run.draft_revision != row["revision"]
    return run


def save(conn: sqlite3.Connection, run: ReviewRun) -> None:
    body = run.model_dump_json()
    conn.execute(
        "INSERT INTO draft_review_runs(id, draft_id, status, body_json) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "status = excluded.status, body_json = excluded.body_json",
        (run.run_id, run.draft_id, run.status, body),
    )
    conn.execute(
        "UPDATE drafts SET review_assessment_json = ? WHERE id = ?",
        (body, run.draft_id),
    )


def new(draft_id: str, mode: Mode, revision: int) -> ReviewRun:
    return ReviewRun(
        run_id="drv_" + uuid.uuid4().hex[:12],
        draft_id=draft_id,
        mode=mode,
        draft_revision=revision,
    )


def reconcile(
    conn: sqlite3.Connection,
    run: ReviewRun,
    committed: Callable[[str], bool] | None = None,
) -> bool:
    if run.review_id is None:
        return False
    application = conn.execute(
        "SELECT id, status FROM draft_applications WHERE review_id = ? "
        "ORDER BY rowid DESC LIMIT 1",
        (run.review_id,),
    ).fetchone()
    if application and (
        application["status"] == "committed"
        or (committed is not None and committed(application["id"]))
    ):
        run.application = "applied"
        run.detail = "Application committed; recovered from its durable receipt."
    else:
        row = conn.execute(
            "SELECT outcome FROM draft_reviews WHERE id = ?", (run.review_id,)
        ).fetchone()
        if row is None or row["outcome"] != "rejected":
            return False
        run.application = "rejected"
        run.detail = "Draft rejection committed; recovered from its review record."
    run.status = "completed"
    return True


def mark_orphaned(
    conn: sqlite3.Connection, committed: Callable[[str], bool] | None = None
) -> None:
    rows = conn.execute(
        "SELECT body_json FROM draft_review_runs WHERE status = 'running'"
    ).fetchall()
    for row in rows:
        run = ReviewRun.model_validate_json(row["body_json"])
        run.status = "failed"
        run.detail = "Review interrupted by restart; request an explicit rerun."
        if run.review_id:
            run.detail = (
                "Review interrupted; inspect the authoritative review and "
                "recover its application with apply_reviewed_draft."
            )
        reconcile(conn, run, committed)
        run.finished_at = timestamps.now()
        save(conn, run)
    conn.commit()


def serialized_assessment(
    body: str | None, revision: int
) -> dict[str, JsonValue] | None:
    if body is None:
        return None
    run = ReviewRun.model_validate_json(body)
    run.stale = run.draft_revision != revision
    return run.model_dump(mode="json")
