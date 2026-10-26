"""Settings and prompt texts over every transport.

Agents read the settings a person sees: product limits, the AI model chosen per
action, draft review, AI usage and the setup checklist (the last two an admin's,
as in the web app). Saving settings stays in the web app: it operates the
server. The texts that steer the AI (writing profile slots and AI
instructions) are edited here as Settings edits them, through the same
validation, role rules and revision check. The web app's routes call these
same functions.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from .. import (
    ai_prompts,
    ai_usage,
    auth,
    documentation_profiles,
    drafts_store,
    model_settings,
    product_settings,
    setup_checklist,
)
from .. import draft_review_settings as review_settings
from .registry import tool
from .runtime import _caller, _db

SettingsKind = Literal[
    "product",
    "models",
    "draft_review",
    "setup",
    "ai_usage",
    "ai_instructions",
    "text_history",
]


class AiInstructions(BaseModel):
    names: tuple[str, ...]
    actions: list[ai_prompts.Summary]
    can_write: bool


def ai_instructions(principal: auth.Principal) -> AiInstructions:
    return AiInstructions(
        names=documentation_profiles.INSTRUCTIONS,
        actions=ai_prompts.summaries(),
        can_write=auth.principal_has_real_role(principal, "writer"),
    )


class TextHistory(BaseModel):
    versions: list[documentation_profiles.TextVersion]


def text_history(type: str, name: str) -> TextHistory:
    from .. import prompt_store

    documentation_profiles.editable_key(type, name)
    return TextHistory(
        versions=[
            documentation_profiles.text_version(row)
            for row in prompt_store.history(prompt_store.connection(), type, name)
        ]
    )


class InstructionPreview(BaseModel):
    preview: str


def _require_admin(what: str) -> auth.Principal:
    principal = _caller()
    if not principal.is_admin:
        raise auth.RoleRequired(f"{what} needs the admin role")
    return principal


@tool
def get_settings(
    kind: SettingsKind,
    days: int = 30,
    action: ai_prompts.Action | None = None,
    preview_text: str | None = None,
    text_type: str | None = None,
    text_name: str | None = None,
) -> dict[str, JsonValue]:
    """Read a Settings screen.

    `product`: limits for the connect pass, curation, labelling, planning,
    media, concurrency and retries. `models`: the provider and model each AI
    action uses, or External agent. `draft_review`: whether and how the
    internal reviewer reviews and applies drafts. `setup`: the setup
    checklist (admin). `ai_usage`: tokens and calls per action, model and
    day over the last `days` (1 to 366; admin). `ai_instructions`: the
    instructions each AI action follows; with `action`, that action's
    editor view with its saved and default text, and with `preview_text`
    as well, the full prompt that text would give. `text_history`: every
    saved version of one writing profile slot or AI instruction
    (`text_type`, `text_name`), for `edit_prompt_text` to restore."""
    return _read(kind, days, action, preview_text, text_type, text_name).model_dump(
        mode="json"
    )


def _read(
    kind: SettingsKind,
    days: int,
    action: ai_prompts.Action | None,
    preview_text: str | None,
    text_type: str | None,
    text_name: str | None,
) -> BaseModel:
    principal = _caller()
    if kind == "product":
        return product_settings.view(principal)
    if kind == "models":
        return model_settings.view(principal)
    if kind == "draft_review":
        return review_settings.view(principal)
    if kind == "setup":
        _require_admin("the setup checklist")
        return setup_checklist.view(_db())
    if kind == "ai_usage":
        _require_admin("AI usage")
        if not 1 <= days <= 366:
            raise ValueError("days must be between 1 and 366")
        return ai_usage.view(drafts_store.connection(), days)
    if kind == "text_history":
        if text_type is None or text_name is None:
            raise ValueError("Give text_type and text_name.")
        return text_history(text_type, text_name)
    if action is None:
        return ai_instructions(principal)
    if preview_text is not None:
        return InstructionPreview(preview=ai_prompts.preview(action, preview_text))
    return ai_prompts.editor(action)


class SaveText(documentation_profiles.SaveText):
    action: Literal["save"]


class RestoreText(documentation_profiles.RestoreText):
    action: Literal["restore"]


TextChange = Annotated[SaveText | RestoreText, Field(discriminator="action")]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_text_change: TypeAdapter[TextChange] = TypeAdapter(TextChange)


def save_text(
    request: documentation_profiles.SaveText, principal: auth.Principal
) -> documentation_profiles.TextVersion:
    documentation_profiles.editable_key(request.type, request.name)
    return documentation_profiles.save_text(
        request.type,
        request.name,
        request.text,
        principal,
        revision=request.revision,
    )


def restore_text(
    request: documentation_profiles.RestoreText, principal: auth.Principal
) -> documentation_profiles.TextVersion:
    documentation_profiles.editable_key(request.type, request.name)
    return documentation_profiles.restore_text(request, principal)


@tool(role="writer", real_role=True)
def edit_prompt_text(request: TextChange) -> dict[str, JsonValue]:
    """Save or restore one text that steers the AI, as Settings does: a
    writing profile slot (`type` "guideline-set", `name`
    "<profile>/<slot>") or
    an AI action's instructions (`type` "doctrine", `name` the action).

    `save` stores `text` at the current `revision`; `restore` brings back
    saved `version` (from `get_settings` kind `text_history`). A stale
    revision is refused and nothing is written. Real writers and admins
    only; a profile's audience or destinations slot needs an admin. Lands
    live. Returns the saved version."""
    request = _text_change.validate_python(request)
    principal = _caller()
    body = request.model_dump(exclude={"action"})
    saved = (
        save_text(documentation_profiles.SaveText(**body), principal)
        if isinstance(request, SaveText)
        else restore_text(documentation_profiles.RestoreText(**body), principal)
    )
    return saved.model_dump(mode="json")
