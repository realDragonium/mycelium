"""Writing profile tools: what Settings → Documentation edits, over MCP.

Each call goes through `documentation_profiles`, so it gets the same
validation, role checks and revision check as the web editor. A profile is
instance configuration, so a save lands live and never queues on a draft;
the tools are named outside `_MUTATION_PREFIXES` for that reason and check
the caller's real role.
"""

from __future__ import annotations

from typing import Any

from .. import audiences, documentation_profiles
from .prompt_texts import _prompt_principal
from .registry import tool
from .runtime import _prompts_db


@tool
def list_writing_profiles() -> dict[str, Any]:
    """List every writing profile with its audience, policies, destinations,
    template names, readiness and `revision`, retired ones included.

    Returns {"profiles": [...], "default_profile", "can_write",
    "can_retire"}. Texts are left out; use `get_writing_profile` for one."""
    view = documentation_profiles.view(_prompt_principal())
    return {
        "profiles": [
            {
                **profile.model_dump(
                    mode="json", exclude={"guidance", "exposure", "templates"}
                ),
                "templates": [item.name for item in profile.templates],
            }
            for profile in view.profiles
        ],
        "default_profile": view.default_profile,
        "can_write": view.can_write,
        "can_retire": view.can_retire,
    }


@tool
def get_writing_profile(name: str) -> dict[str, Any]:
    """Read one writing profile in full: guidance, disclosure rules
    (`exposure`), every template, audience, policies, destinations,
    readiness and the `revision` a save must send back.

    Returns {"profile": {...}, "audience": {id, name, scope, description}}.
    `audience` is the audience runs of the profile write for, after the
    default applies; null when it was retired."""
    db = _prompts_db()
    profile = documentation_profiles.read(name, db)
    if not profile.revision:
        raise ValueError(f"No writing profile is named '{name}'.")
    audience = documentation_profiles.audience_brief(
        next(
            (
                item
                for item in audiences.live(db)
                if item.id == profile.effective_audience
            ),
            None,
        )
    )
    return {
        "profile": profile.model_dump(mode="json"),
        "audience": None if audience is None else audience.model_dump(mode="json"),
    }


@tool(real_role=True)
def save_writing_profile(
    name: str,
    revision: str,
    templates: list[dict[str, str]],
    guidance: str = "",
    exposure: str = "",
    audience: str | None = None,
    maintenance: documentation_profiles.Maintenance = "manual",
    planning: documentation_profiles.Planning = "off",
    plan_review: documentation_profiles.PlanReview = "person",
    delivery: documentation_profiles.Delivery = "people",
    destinations: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update a writing profile with its whole content, as the
    web editor saves it.

    Send every field: what is left out is reset or removed. `templates` is
    [{"name", "text"}]. `revision` is the one `get_writing_profile` returned;
    "" creates a profile that does not exist yet. A stale revision is refused
    and nothing is written. Needs a real writer; removing a template or
    slot, or changing the audience or destinations of an existing profile,
    needs an admin. `audience` must be a live audience id, or null for the
    default internal audience; `destinations` empty allows every configured
    destination. Returns the saved profile."""
    request = documentation_profiles.SaveProfile.model_validate(
        {
            "revision": revision,
            "guidance": guidance,
            "exposure": exposure,
            "audience": audience,
            "maintenance": maintenance,
            "planning": planning,
            "plan_review": plan_review,
            "delivery": delivery,
            "destinations": destinations or [],
            "templates": templates,
        }
    )
    return documentation_profiles.save(name, request, _prompt_principal()).model_dump(
        mode="json"
    )


@tool(role="admin", real_role=True)
def retire_writing_profile(name: str, revision: str) -> dict[str, Any]:
    """Retire every text of a writing profile, keeping its history and its
    documents. Needs a real admin and the profile's current `revision`. The
    default profile cannot be retired. Returns the retired profile."""
    return documentation_profiles.retire(
        name, revision, _prompt_principal()
    ).model_dump(mode="json")


@tool(role="admin", real_role=True)
def restore_writing_profile(name: str, revision: str) -> dict[str, Any]:
    """Bring a retired writing profile back with the texts it held when it was
    retired. Needs a real admin and the retired profile's current
    `revision`. Returns the restored profile."""
    return documentation_profiles.restore(
        name, revision, _prompt_principal()
    ).model_dump(mode="json")
