"""Per-action model selection with instance persistence and server credentials."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import auth, errors, prompt_store, store
from .ai import Provider, ReasoningEffort
from .ai.types import ClaudeEffort
from .model_credentials import claude_configuration_error

logger = logging.getLogger(__name__)

Action = Literal[
    "ask",
    "ingest",
    "docgen",
    "draft_review",
    "alias_discovery",
    "audience_labelling",
    "documentation_planning",
    "connect",
]
ACTIONS: tuple[Action, ...] = (
    "ask",
    "ingest",
    "docgen",
    "draft_review",
    "alias_discovery",
    "audience_labelling",
    "documentation_planning",
    "connect",
)
#: Actions whose work an outside agent may do instead of a server model. For
#: Ask that agent is the caller itself: the `ask` tool runs no model and the
#: caller researches with the read tools.
AGENT_ACTIONS: frozenset[Action] = frozenset(
    {
        "ask",
        "docgen",
        "draft_review",
        "documentation_planning",
        "audience_labelling",
        "ingest",
        "connect",
        "alias_discovery",
    }
)
#: Who reviews a document an outside agent wrote: the server's reviewer on
#: the action's provider, or an agent other than the writer.
AgentReview = Literal["server", "agent"]
PROVIDERS: tuple[Provider, ...] = ("claude", "openai")
ACTION_NAMES: dict[Action, str] = {
    "ask": "Ask",
    "ingest": "Ingestion",
    "docgen": "Document generation",
    "draft_review": "Draft review",
    "alias_discovery": "Alias discovery",
    "audience_labelling": "Audience labelling",
    "documentation_planning": "Documentation planning",
    "connect": "Connecting statements",
}
#: The Claude models actions ran on when no model was saved for them, before
#: models came from the catalog. Only an upgrade reads them, to save them
#: explicitly so no action changes model; a fresh instance has no models.
_FORMER_CLAUDE_DEFAULTS: dict[Action, str] = {
    "ask": "claude-haiku-4-5",
    "ingest": "claude-sonnet-4-6",
    "docgen": "claude-sonnet-4-6",
    "alias_discovery": "claude-sonnet-4-6",
    "audience_labelling": "claude-haiku-5-5",
    "documentation_planning": "claude-sonnet-4-6",
    "connect": "claude-sonnet-4-6",
}
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
    claude_reasoning_effort: ClaudeEffort | None = None
    openai_reasoning_effort: ReasoningEffort | None = None
    #: Queue the action's work for outside agents (`agent_tasks`) instead of
    #: calling `provider`, which then only reviews documents agents wrote.
    external_agent: bool = False
    agent_review: AgentReview = "server"

    def model_for(self, provider: Provider) -> str:
        return self.claude_model if provider == "claude" else self.openai_model

    def effort_for(self, provider: Provider) -> ReasoningEffort | None:
        return (
            self.claude_reasoning_effort
            if provider == "claude"
            else self.openai_reasoning_effort
        )

    @property
    def reasoning_effort(self) -> ReasoningEffort | None:
        return self.effort_for(self.provider)

    def needs_provider(self, action: Action) -> bool:
        """Whether `action` calls `provider` at all: only documentation's
        server reviewer does while an agent does the work."""
        return not self.external_agent or (
            action == "docgen" and self.agent_review == "server"
        )


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
    #: Whether External agent may be chosen for this action.
    agent_supported: bool
    configuration_error: str | None = None
    #: Set when the selected model id belongs to the other provider.
    model_warning: str | None = None
    providers: list[ProviderAvailability]


class CatalogModel(BaseModel):
    provider: Provider
    model: str


class SettingsView(BaseModel):
    can_configure: bool
    actions: list[ActionView]
    #: The models an admin made selectable, per provider in their order.
    catalog: list[CatalogModel]


class Unavailable(ValueError):
    pass


class Conflict(errors.Conflict):
    pass


def defaults(action: Action) -> Selection:
    """An action nobody configured: it has no model, so it cannot run."""
    return Selection(
        provider="openai" if action == "draft_review" else "claude",
        claude_model="",
        openai_model="",
    )


def former_default(action: Action) -> Selection:
    return Selection(
        provider="openai" if action == "draft_review" else "claude",
        claude_model=_FORMER_CLAUDE_DEFAULTS.get(action, ""),
        openai_model="",
    )


def legacy_selection(action: Action) -> dict[str, str]:
    """Capture legacy values without hiding invalid configuration during migration."""
    default = former_default(action)
    if action in (
        "alias_discovery",
        "audience_labelling",
        "documentation_planning",
        "connect",
    ):
        return {
            "provider": default.provider,
            "claude_model": default.claude_model,
            "openai_model": default.openai_model,
        }
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


def adopt_catalog(conn: sqlite3.Connection, *, upgrading: bool) -> None:
    """Once per instance, before models come only from the catalog: save the
    model an upgraded action without a saved selection ran on, then seed the
    catalog with every model a saved selection names."""
    from . import product_settings

    if upgrading:
        saved = {
            row["action"] for row in conn.execute("SELECT action FROM model_settings")
        }
        for action in ACTIONS:
            if action in saved:
                continue
            selection = former_default(action)
            conn.execute(
                "INSERT INTO model_settings VALUES (?, 1, ?)",
                (action, selection.model_dump_json()),
            )
            logger.warning(
                "saved %s model %s for %s, which ran on it by default",
                _PROVIDER_NAMES[selection.provider],
                selection.claude_model or "(none)",
                ACTION_NAMES[action],
            )
    try:
        current = product_settings.get(product_settings.ModelCatalogSettings, conn=conn)
    except Unavailable:
        current = product_settings.ModelCatalogSettings()
    models: dict[Provider, list[str]] = {
        "claude": list(current.claude),
        "openai": list(current.openai),
    }
    seeded: list[str] = []
    for row in conn.execute("SELECT body_json FROM model_settings ORDER BY action"):
        try:
            selection = Selection.model_validate_json(row["body_json"])
        except ValidationError:
            continue
        pairs: tuple[tuple[Provider, str], ...] = (
            ("claude", selection.claude_model),
            ("openai", selection.openai_model),
        )
        for provider, model in pairs:
            # An id saved under the wrong provider stays refused at run time
            # and never enters the catalog.
            if (
                model
                and model not in models[provider]
                and provider_of(model)
                in (
                    None,
                    provider,
                )
            ):
                models[provider].append(model)
                seeded.append(model)
    if not seeded:
        return
    catalog = product_settings.ModelCatalogSettings(
        claude=tuple(models["claude"]), openai=tuple(models["openai"])
    )
    conn.execute(
        "INSERT INTO product_settings VALUES (?, 1, ?) ON CONFLICT(section) DO UPDATE "
        "SET revision = revision + 1, body_json = excluded.body_json",
        (catalog.kind, catalog.model_dump_json()),
    )
    logger.info("added %s to the model catalog", ", ".join(seeded))


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


_PROVIDER_NAMES: dict[Provider, str] = {"claude": "Claude", "openai": "OpenAI"}


# Bedrock and Vertex ids wrap the Claude name (`us.anthropic.claude-…`,
# `claude-…@20250101`), so a Claude id is recognised anywhere after a separator.
_CLAUDE_ID = re.compile(r"(^|[.:/])claude-")
_OPENAI_ID = re.compile(r"^(ft:)?(gpt-|chatgpt-|codex-|o\d)")


def provider_of(model: str) -> Provider | None:
    """The provider a model id belongs to by its shape; None for an id
    neither provider's naming recognises."""
    if _CLAUDE_ID.search(model):
        return "claude"
    if _OPENAI_ID.match(model):
        return "openai"
    return None


def check_model_id(provider: Provider, model: str) -> None:
    """Refuse an id that belongs to the other provider. An id neither
    provider's naming recognises is allowed, so a new model works before this
    build knows it."""
    owner = provider_of(model) if model else None
    if owner is not None and owner != provider:
        raise ValueError(
            f"'{model}' is a model ID for {_PROVIDER_NAMES[owner]}, "
            f"not {_PROVIDER_NAMES[provider]}."
        )


def model_warning(provider: Provider, model: str) -> str | None:
    try:
        check_model_id(provider, model)
    except ValueError as exc:
        return str(exc)
    return None


def _action_phrase(action: Action) -> str:
    return ACTION_NAMES[action] if action == "ask" else ACTION_NAMES[action].lower()


def missing_model(action: Action, provider: Provider) -> str:
    name = _PROVIDER_NAMES[provider]
    article = "an" if name[0] in "AEIOU" else "a"
    return f"Choose {article} {name} model for {_action_phrase(action)} in AI settings."


def model_error(action: Action, selected: Selection) -> str | None:
    """Why `action` cannot run on `selected`: it needs a model it lacks."""
    model = (
        selected.claude_model
        if selected.provider == "claude"
        else selected.openai_model
    )
    if selected.needs_provider(action) and not model:
        return missing_model(action, selected.provider)
    return None


def require(action: Action) -> ModelSnapshot:
    """`action`'s selection, refused while it needs a model it lacks."""
    selected = get(action)
    if reason := model_error(action, selected):
        raise ValueError(reason)
    return selected


def credentials_error(action: Action) -> str | None:
    """Why `action` cannot run: no model, or no credentials for its
    provider. Checks presence only, so it costs no request."""
    try:
        selected = get(action)
    except Unavailable as exc:
        return str(exc)
    if not selected.needs_provider(action):
        return None
    return (
        model_error(action, selected) or provider_availability(selected.provider).reason
    )


def catalog(conn: sqlite3.Connection | None = None) -> dict[Provider, tuple[str, ...]]:
    from . import product_settings

    saved = product_settings.get(product_settings.ModelCatalogSettings, conn=conn)
    return {provider: saved.models(provider) for provider in PROVIDERS}


def models_in_use(
    conn: sqlite3.Connection, provider: Provider
) -> dict[str, list[Action]]:
    """The actions each `provider` model is saved for and could run on: the
    selected provider's model, and both of documentation's, since a document
    can be generated on either provider."""
    used: dict[str, list[Action]] = {}
    for action in ACTIONS:
        try:
            selected = get(action, conn=conn)
        except Unavailable:
            continue
        model = selected.model_for(provider)
        if model and (selected.provider == provider or action == "docgen"):
            used.setdefault(model, []).append(action)
    return used


def refuse_removing_used(
    conn: sqlite3.Connection, provider: Provider, removed: set[str]
) -> None:
    used = models_in_use(conn, provider)
    blocked = [
        f"'{model}' is used by "
        + ", ".join(ACTION_NAMES[action] for action in used[model])
        for model in sorted(removed)
        if model in used
    ]
    if blocked:
        raise ValueError("; ".join(blocked) + ". Choose another model for them first.")


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
        agent_supported=action in AGENT_ACTIONS,
        configuration_error=error,
        model_warning=model_warning(selected.provider, selected.model),
        providers=[provider_availability("claude"), provider_availability("openai")],
    )


def catalog_view() -> list[CatalogModel]:
    return [
        CatalogModel(provider=provider, model=model)
        for provider, models in catalog().items()
        for model in models
    ]


def view(principal: auth.Principal) -> SettingsView:
    return SettingsView(
        can_configure=principal.is_admin,
        actions=[action_view(action) for action in ACTIONS],
        catalog=catalog_view(),
    )


def save_in_transaction(
    conn: sqlite3.Connection, action: Action, request: SaveSelection
) -> ModelSnapshot:
    current, error = editable(action, conn=conn)
    if current.revision != request.revision:
        raise Conflict("Model settings changed; reload before saving.")
    before = Selection.model_validate(
        current.model_dump(include=set(Selection.model_fields))
    )
    desired = Selection.model_validate(
        {
            **before.model_dump(),
            **request.model_dump(exclude={"revision"}, exclude_unset=True),
        }
    )
    if error is None and desired == before and current.source == "saved":
        return current
    offered = catalog(conn)
    for provider in PROVIDERS:
        model = desired.model_for(provider)
        if (
            model
            and model != before.model_for(provider)
            and model not in offered[provider]
        ):
            raise ValueError(
                f"'{model}' is not in the {_PROVIDER_NAMES[provider]} model "
                "catalog. Add it in AI settings first."
            )
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
    if request.external_agent and action not in AGENT_ACTIONS:
        raise ValueError("This action cannot be done by an external agent.")
    if request.agent_review == "agent" and action != "docgen":
        raise ValueError("Only documentation has an agent review.")
    selected_model = (
        request.claude_model if request.provider == "claude" else request.openai_model
    )
    if not selected_model and request.needs_provider(action):
        raise ValueError(missing_model(action, request.provider))
    check_model_id("claude", request.claude_model)
    check_model_id("openai", request.openai_model)
    conn = prompt_store.connection()
    with store.write_lock(), prompt_store._writing(conn):
        return save_in_transaction(conn, action, request)
