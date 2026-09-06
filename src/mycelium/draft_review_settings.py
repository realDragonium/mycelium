"""Privileged review controls paired with the shared per-action model selection."""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import auth, model_settings, prompt_store, store
from .draft_review_store import Mode
from .model_settings import Conflict, Provider, ProviderAvailability, Unavailable

SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_review_settings (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    revision INTEGER NOT NULL CHECK(revision > 0),
    body_json TEXT NOT NULL
);
"""


class Controls(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, str_strip_whitespace=True
    )
    mode: Mode = "off"
    reviewer_id: str = Field(default="", max_length=200)
    application_enabled: bool = False


class ControlSnapshot(Controls):
    revision: int = Field(default=0, ge=0)
    source: Literal["default", "saved"] = "default"


class Settings(Controls):
    provider: Provider = "openai"
    model: str = Field(default="", max_length=200)


class Snapshot(Settings):
    revision: int = Field(default=0, ge=0)
    model_revision: int = Field(default=0, ge=0)
    source: Literal["default", "saved"] = "default"


class SaveSettings(Settings):
    revision: int = Field(ge=0)
    model_revision: int = Field(ge=0)


class ReviewerChoice(BaseModel):
    id: str
    name: str
    role: Literal["writer", "admin"]


class SettingsView(Snapshot):
    configuration_error: str | None = None
    can_review: bool
    can_configure: bool
    application_enabled: bool
    ready: bool
    issues: list[str]
    providers: list[ProviderAvailability]
    reviewers: list[ReviewerChoice]
    claude_model: str
    openai_model: str


def load_controls(conn: sqlite3.Connection) -> ControlSnapshot:
    try:
        row = conn.execute(
            "SELECT revision, body_json FROM draft_review_settings WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return ControlSnapshot()
        controls = Controls.model_validate_json(row["body_json"])
        return ControlSnapshot(
            **controls.model_dump(), revision=row["revision"], source="saved"
        )
    except (sqlite3.Error, ValidationError, RuntimeError):
        raise Unavailable(
            "Saved draft review settings cannot be read; review is disabled."
        ) from None


def editable_controls(conn: sqlite3.Connection) -> tuple[ControlSnapshot, str | None]:
    try:
        return load_controls(conn), None
    except Unavailable as exc:
        try:
            row = conn.execute(
                "SELECT revision FROM draft_review_settings WHERE singleton = 1"
            ).fetchone()
            return ControlSnapshot(
                revision=row["revision"] if row else 0,
                source="saved" if row else "default",
            ), str(exc)
        except (sqlite3.Error, ValidationError, RuntimeError):
            raise Unavailable("Instance review configuration cannot be read.") from None


def load(conn: sqlite3.Connection | None = None) -> Snapshot:
    try:
        with store.write_lock():
            db = conn if conn is not None else prompt_store.connection()
            controls = load_controls(db)
            model = model_settings.get("draft_review", conn=db)
            return Snapshot(
                **controls.model_dump(exclude={"source"}),
                provider=model.provider,
                model=model.model,
                model_revision=model.revision,
                source="saved"
                if controls.source == "saved" or model.source == "saved"
                else "default",
            )
    except RuntimeError:
        raise Unavailable(
            "Saved draft review settings cannot be read; review is disabled."
        ) from None


def configuration_issues(settings: Settings) -> list[str]:
    from . import server

    issues = []
    if not settings.model:
        issues.append("Enter a model ID for the selected provider.")
    availability = model_settings.provider_availability(settings.provider)
    if availability.reason:
        issues.append(availability.reason)
    principal = auth.resolve_session_user(server._auth_db(), settings.reviewer_id)
    if principal is None or not auth.principal_has_real_role(principal, "writer"):
        issues.append("Select an active writer or admin as the independent reviewer.")
    return issues


def view(principal: auth.Principal) -> SettingsView:
    from . import server

    with store.write_lock():
        db = prompt_store.connection()
        controls, controls_error = editable_controls(db)
        model, model_error = model_settings.editable("draft_review", conn=db)
        settings = Snapshot(
            **controls.model_dump(exclude={"source"}),
            provider=model.provider,
            model=model.model,
            model_revision=model.revision,
            source="saved"
            if controls.source == "saved" or model.source == "saved"
            else "default",
        )
    errors = [error for error in (controls_error, model_error) if error is not None]
    configuration_error = " ".join(errors) or None
    issues = errors + configuration_issues(settings)
    reviewers = []
    if principal.is_admin:
        reviewers = [
            ReviewerChoice(id=row["id"], name=row["name"], role=row["role"])
            for row in auth.list_users(server._auth_db())
            if row["status"] == "active" and row["role"] in ("writer", "admin")
        ]
    return SettingsView(
        **settings.model_dump(),
        configuration_error=configuration_error,
        claude_model=model.claude_model,
        openai_model=model.openai_model,
        can_review=auth.principal_has_real_role(principal, "writer"),
        can_configure=principal.is_admin,
        ready=not issues,
        issues=issues,
        providers=[
            model_settings.provider_availability("claude"),
            model_settings.provider_availability("openai"),
        ],
        reviewers=reviewers,
    )


def save(request: SaveSettings, principal: auth.Principal) -> Snapshot:
    if not principal.is_admin:
        raise auth.RoleRequired("admin role required")
    desired = Controls(
        mode=request.mode,
        reviewer_id=request.reviewer_id,
        application_enabled=request.application_enabled,
    )
    if desired.mode != "off":
        issues = configuration_issues(request)
        if issues:
            raise ValueError(" ".join(issues))
    db = prompt_store.connection()
    # Settings and automatic application share this ordering lock. Both rows
    # commit together, so changing a model cannot partially save review controls.
    with store.write_lock(), prompt_store._writing(db):
        current, controls_error = editable_controls(db)
        if current.revision != request.revision:
            raise Conflict("Review settings changed; reload before saving.")
        models, _ = model_settings.editable("draft_review", conn=db)
        model_settings.save_in_transaction(
            db,
            "draft_review",
            model_settings.SaveSelection(
                provider=request.provider,
                revision=request.model_revision,
                claude_model=request.model
                if request.provider == "claude"
                else models.claude_model,
                openai_model=request.model
                if request.provider == "openai"
                else models.openai_model,
            ),
        )
        unchanged = (
            Controls(
                mode=current.mode,
                reviewer_id=current.reviewer_id,
                application_enabled=current.application_enabled,
            )
            == desired
        )
        if controls_error or not unchanged or current.source != "saved":
            db.execute(
                "INSERT INTO draft_review_settings(singleton, revision, body_json) VALUES (1, ?, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET revision = excluded.revision, body_json = excluded.body_json",
                (current.revision + 1, desired.model_dump_json()),
            )
        return load(db)
