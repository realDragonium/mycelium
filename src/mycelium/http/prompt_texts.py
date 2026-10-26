"""Editable prompt texts: documentation profiles, their prompts and the AI instructions.

Every route here needs an authenticated caller; whether a save is allowed is
decided by `documentation_profiles` and `ai_prompts` from that principal. The
MCP tools `get_settings` and `edit_prompt_text` call the same functions.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from pydantic import Field as PydField

from .. import ai_prompts, documentation_profiles
from ..request_timing import TimedRoute
from ..server import settings
from .access import _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/documentation/profiles")
def documentation_profiles_http(request: Request) -> documentation_profiles.Profiles:
    return documentation_profiles.view(_require_principal(request))


@router.get("/api/documentation/profiles/{name}")
def documentation_profile_http(
    name: str, request: Request
) -> documentation_profiles.Profile:
    _require_principal(request)
    return documentation_profiles.read(name)


@router.put("/api/documentation/profiles/{name}")
def save_documentation_profile_http(
    name: str, body: documentation_profiles.SaveProfile, request: Request
) -> documentation_profiles.Profile:
    return documentation_profiles.save(name, body, _require_principal(request))


@router.delete("/api/documentation/profiles/{name}")
def retire_documentation_profile_http(
    name: str, body: documentation_profiles.RevisionRequest, request: Request
) -> documentation_profiles.Profile:
    return documentation_profiles.retire(
        name, body.revision, _require_principal(request)
    )


@router.get("/api/documentation/prompts/history")
def documentation_prompt_history_http(
    type: str, name: str, request: Request
) -> settings.TextHistory:
    _require_principal(request)
    return settings.text_history(type, name)


@router.put("/api/documentation/prompts")
def save_documentation_prompt_http(
    body: documentation_profiles.SaveText, request: Request
) -> documentation_profiles.TextVersion:
    return settings.save_text(body, _require_principal(request))


@router.post("/api/documentation/prompts/restore")
def restore_documentation_prompt_http(
    body: documentation_profiles.RestoreText, request: Request
) -> documentation_profiles.TextVersion:
    return settings.restore_text(body, _require_principal(request))


@router.get("/api/ai-instructions")
def ai_instructions_http(request: Request) -> settings.AiInstructions:
    return settings.ai_instructions(_require_principal(request))


@router.get("/api/ai-instructions/{action}")
def ai_instruction_http(
    action: ai_prompts.Action, request: Request
) -> ai_prompts.EditorView:
    _require_principal(request)
    return ai_prompts.editor(action)


class PromptPreviewBody(BaseModel):
    text: str = PydField(max_length=100000)


@router.post("/api/ai-instructions/{action}/preview")
def ai_instruction_preview_http(
    action: ai_prompts.Action, body: PromptPreviewBody, request: Request
) -> dict[str, str]:
    _require_principal(request)
    return {"preview": ai_prompts.preview(action, body.text)}
