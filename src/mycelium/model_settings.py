"""Per-action model selection with instance persistence and server credentials."""

from __future__ import annotations

import os
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import auth, prompt_store, store
from .ai import Provider
from .model_credentials import claude_configuration_error

Action = Literal["ask", "ingest", "research", "docgen", "draft_review"]
ACTIONS: tuple[Action, ...] = ("ask", "ingest", "research", "docgen", "draft_review")
SCHEMA = """
CREATE TABLE IF NOT EXISTS model_settings (
    action TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK(revision > 0),
    body_json TEXT NOT NULL
);
"""


class Selection(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, str_strip_whitespace=True
    )
    provider: Provider
    claude_model: str = Field(max_length=200)
    openai_model: str = Field(max_length=200)


class ModelSnapshot(Selection):
    action: Action
    model: str
    revision: int = Field(ge=0)
    source: Literal["default", "saved"]


class SaveSelection(Selection):
    revision: int = Field(ge=0)


class ProviderAvailability(BaseModel):
    provider: Provider
    available: bool
    reason: str | None


class ActionView(ModelSnapshot):
    configuration_error: str | None = None
    providers: list[ProviderAvailability]


class SettingsView(BaseModel):
    can_configure: bool
    actions: list[ActionView]


class Unavailable(ValueError):
    pass


class Conflict(ValueError):
    pass


def defaults(action: Action) -> Selection:
    from .ask.config import DEFAULT_MODEL as ASK_MODEL
    from .ingest.config import DEFAULT_MODEL as INGEST_MODEL

    return Selection(
        provider="openai" if action == "draft_review" else "claude",
        claude_model=""
        if action == "draft_review"
        else ASK_MODEL
        if action == "ask"
        else INGEST_MODEL,
        openai_model="",
    )


def legacy_selection(action: Action) -> dict[str, str]:
    """Capture legacy values without hiding invalid configuration during migration."""
    default = defaults(action)
    prefix = "MYCELIUM_" + action.upper()
    provider = os.environ.get(prefix + "_PROVIDER", default.provider)
    if action == "draft_review":
        legacy = os.environ.get(prefix + "_MODEL", "")
        claude = os.environ.get(
            prefix + "_CLAUDE_MODEL", legacy if provider == "claude" else ""
        )
        openai = os.environ.get(
            prefix + "_OPENAI_MODEL", legacy if provider == "openai" else ""
        )
    else:
        fallback = (
            default.claude_model
            if action == "ask"
            else os.environ.get("MYCELIUM_INGEST_MODEL") or default.claude_model
        )
        claude = os.environ.get(prefix + "_MODEL") or fallback
        openai = os.environ.get(prefix + "_OPENAI_MODEL", "")
    return {"provider": provider, "claude_model": claude, "openai_model": openai}


def get(action: Action, *, conn: sqlite3.Connection | None = None) -> ModelSnapshot:
    try:
        row = None
        if conn is not None or prompt_store.is_configured():
            db = conn if conn is not None else prompt_store.connection()
            row = db.execute(
                "SELECT revision, body_json FROM model_settings WHERE action = ?",
                (action,),
            ).fetchone()
        selected = (
            Selection.model_validate_json(row["body_json"]) if row else defaults(action)
        )
        return ModelSnapshot(
            action=action,
            **selected.model_dump(),
            model=selected.claude_model
            if selected.provider == "claude"
            else selected.openai_model,
            revision=row["revision"] if row else 0,
            source="saved" if row else "default",
        )
    except (sqlite3.Error, ValidationError, RuntimeError):
        raise Unavailable(
            f"Model settings for {action} cannot be read; the action is disabled."
        ) from None


def provider_availability(provider: Provider) -> ProviderAvailability:
    reason = (
        claude_configuration_error()
        if provider == "claude"
        else None
        if os.environ.get("OPENAI_API_KEY", "").strip()
        else "Set OPENAI_API_KEY on the server."
    )
    return ProviderAvailability(
        provider=provider, available=reason is None, reason=reason
    )


def editable(
    action: Action, *, conn: sqlite3.Connection | None = None
) -> tuple[ModelSnapshot, str | None]:
    try:
        return get(action, conn=conn), None
    except Unavailable as exc:
        db = conn if conn is not None else prompt_store.connection()
        try:
            row = db.execute(
                "SELECT revision FROM model_settings WHERE action = ?", (action,)
            ).fetchone()
            return ModelSnapshot(
                action=action,
                provider="openai" if action == "draft_review" else "claude",
                claude_model="",
                openai_model="",
                model="",
                revision=row["revision"] if row else 0,
                source="saved" if row else "default",
            ), str(exc)
        except (sqlite3.Error, ValidationError, RuntimeError):
            raise Unavailable("Instance model configuration cannot be read.") from None


def action_view(action: Action) -> ActionView:
    selected, error = editable(action)
    return ActionView(
        **selected.model_dump(),
        configuration_error=error,
        providers=[provider_availability("claude"), provider_availability("openai")],
    )


def view(principal: auth.Principal) -> SettingsView:
    return SettingsView(
        can_configure=principal.is_admin,
        actions=[action_view(action) for action in ACTIONS],
    )


def save_in_transaction(
    conn: sqlite3.Connection, action: Action, request: SaveSelection
) -> ModelSnapshot:
    current, error = editable(action, conn=conn)
    if current.revision != request.revision:
        raise Conflict("Model settings changed; reload before saving.")
    desired = Selection.model_validate(request.model_dump(exclude={"revision"}))
    before = Selection.model_validate(
        current.model_dump(include={"provider", "claude_model", "openai_model"})
    )
    if error is None and desired == before and current.source == "saved":
        return current
    conn.execute(
        "INSERT INTO model_settings(action, revision, body_json) VALUES (?, ?, ?) "
        "ON CONFLICT(action) DO UPDATE SET revision = excluded.revision, body_json = excluded.body_json",
        (action, current.revision + 1, desired.model_dump_json()),
    )
    return get(action, conn=conn)


def save(
    action: Action, request: SaveSelection, principal: auth.Principal
) -> ModelSnapshot:
    if not principal.is_admin:
        raise auth.RoleRequired("admin role required")
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        return save_in_transaction(conn, action, request)
