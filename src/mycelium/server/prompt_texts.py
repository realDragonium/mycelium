"""Prompt text reads and retirement, plus startup seeding.

Doctrines, prompt preambles and guideline sets are editable rows (see
`prompt_store`). They are instance configuration, not knowledge, so an edit
lands live instead of queueing on a draft, and retirement requires the
caller's real role. Startup seeds the packaged loop doctrines, which is why
those names cannot be retired.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import audiences, documentation_profiles
from ..auth import Principal as AuthPrincipal
from .registry import tool
from .runtime import _prompts_db

logger = logging.getLogger(__name__)


def _seeded_prompt_texts() -> tuple[tuple[str, str, Callable[[], Path]], ...]:
    """Loop doctrines whose packaged defaults remain available after restart."""
    from ..docgen.config import DOCTRINE_NAME as DOCGEN_DOCTRINE
    from ..docgen.config import DocgenConfig
    from ..ingest.config import DOCTRINE_NAME as INGEST_DOCTRINE
    from ..ingest.config import IngestConfig

    return (
        (
            "doctrine",
            INGEST_DOCTRINE,
            lambda: Path(IngestConfig.from_env().doctrine_path),
        ),
        (
            "doctrine",
            DOCGEN_DOCTRINE,
            lambda: Path(DocgenConfig.from_env().doctrine_path),
        ),
    )


def _is_seeded(type: str, name: str) -> bool:
    """Whether startup seeds (type, name). Keys are compared as the store
    stores them — stripped."""
    key = (type.strip(), name.strip())
    return any(key == (t, n) for t, n, _ in _seeded_prompt_texts())


def _seed_prompt_texts() -> None:
    """Seed starter profiles once and the loop doctrines when absent, then
    bring untouched seeded texts up to this build's defaults and warn about
    saved texts that predate them (see `prompt_defaults`)."""
    from .. import ai_prompts, prompt_defaults, prompt_store

    try:
        documentation_profiles.seed_starters(_prompts_db())
    except Exception:
        logger.warning("could not seed documentation starter profiles", exc_info=True)
    try:
        audiences.seed(_prompts_db())
    except Exception:
        logger.warning("could not seed documentation audiences", exc_info=True)

    for type, name, source in _seeded_prompt_texts():
        try:
            # Resolution inside the guard: `from_env` also parses that loop's
            # numeric tunables, and one malformed op cap must not stop a
            # server booting.
            prompt_store.save_if_absent(
                _prompts_db(),
                type=type,
                name=name,
                text=source().read_text(encoding="utf-8"),
                created_by="seed",
            )
        except Exception:
            logger.warning(
                "could not seed prompt text %s/%s", type, name, exc_info=True
            )

    for action in ai_prompts.ACTIONS:
        try:
            since = prompt_defaults.sync(
                _prompts_db(), "doctrine", action, ai_prompts.shipped_text(action)
            )
        except Exception:
            logger.warning(
                "could not update the shipped default for %s", action, exc_info=True
            )
            continue
        if since is not None:
            logger.warning(
                "saved %s instructions predate the default this build ships "
                "(first seen %s); compare them in AI settings → Prompts",
                action,
                since,
            )


# --- prompt-text tools ------------------------------------------------------
# Steering texts (doctrines, prompt preambles, guideline sets) as editable
# rows — see `prompt_store`. Deliberately named outside `_MUTATION_PREFIXES`:
# prompt texts are instance configuration, so an edit takes effect directly
# and never queues onto a draft. `retire_` carries the admin gate that the
# `delete_` prefix would otherwise have derived, and because retirement
# lands live, the tool checks the caller's REAL role so the
# drafter-equivalence in `auth.principal_satisfies` can't stand in for one.


@tool
def get_prompt_text(type: str, name: str) -> dict[str, Any]:
    """Fetch the current text stored under (type, name), body included.

    Returns the row {id, type, name, text, version, deleted, created_at,
    created_by}. Raises when the name has never been saved or was retired."""
    from .. import prompt_store

    row = prompt_store.latest(_prompts_db(), type, name)
    if row is None:
        raise ValueError(f"prompt text not found: {type}/{name}")
    return prompt_store.serialize(row)


@tool
def list_prompt_texts(type: str | None = None) -> dict[str, Any]:
    """List the prompt texts currently in force, optionally narrowed to one
    `type`. Retired names are omitted.

    Bodies are left out — use `get_prompt_text` for one. Returns
    {"prompt_texts": [{type, name, version, chars, created_at, created_by}]}.
    """
    from .. import prompt_store

    return {
        "prompt_texts": [
            prompt_store.serialize_summary(row)
            for row in prompt_store.list_current(_prompts_db(), type)
        ]
    }


@tool(role="admin", real_role=True)
def retire_prompt_text(
    type: str, name: str, expected_version: int | None = None
) -> dict[str, Any]:
    """Retire a text, preserving history. Packaged loop doctrines remain protected.

    Documentation starters are user-owned; only an active default's final
    template is protected until another default is selected. Pass expected_version
    to reject retirement when another caller has changed the text.
    """
    if _is_seeded(type, name):
        raise ValueError(
            f"prompt text '{type}/{name}' is seeded at startup and cannot be "
            f"retired: the next start would re-seed the packaged default at a "
            f"new version. Edit it in Settings → Prompts instead."
        )
    retired = documentation_profiles.retire_text(
        type, name, _prompt_principal(), expected_version=expected_version
    )
    return {"retired": retired}


def _prompt_principal() -> AuthPrincipal:
    from .. import auth

    return auth.current_principal.get() or auth.LOCAL_ADMIN
