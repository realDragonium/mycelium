"""Versioned behavioral instructions shared by providers and their UI previews."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import prompt_store

Action = Literal[
    "ask",
    "ingest",
    "research",
    "docgen",
    "document_review",
    "draft_review",
    "alias_discovery",
]
ACTIONS: tuple[Action, ...] = (
    "ask",
    "ingest",
    "research",
    "docgen",
    "document_review",
    "draft_review",
    "alias_discovery",
)
TITLES: dict[Action, str] = {
    "ask": "Questions",
    "ingest": "Ingestion",
    "research": "Research",
    "docgen": "Document generation",
    "document_review": "Document review",
    "draft_review": "Draft review",
    "alias_discovery": "Alias discovery",
}


class Reference(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Action
    version: int
    source: Literal["saved", "default", "file"]
    digest: str
    note: str | None = None


class Snapshot(Reference):
    text: str

    def reference(self) -> Reference:
        return Reference(**self.model_dump(exclude={"text"}))


def default_text(action: Action) -> str:
    if action in ("ingest", "research", "docgen"):
        return (Path(__file__).parent / action / "doctrine.md").read_text(
            encoding="utf-8"
        )
    if action == "ask":
        from .ask.prompts import DEFAULT_INSTRUCTIONS
    elif action == "document_review":
        from .docgen.prompts import DEFAULT_REVIEW_INSTRUCTIONS as DEFAULT_INSTRUCTIONS
    elif action == "draft_review":
        from .draft_review_model import DEFAULT_INSTRUCTIONS
    else:
        from .alias_suggestions import DEFAULT_INSTRUCTIONS
    return DEFAULT_INSTRUCTIONS


def _default_path(action: Action) -> str | None:
    if action == "ingest":
        from .ingest.config import IngestConfig

        return IngestConfig.from_env().doctrine_path
    if action == "research":
        from .research.config import ResearchConfig

        return ResearchConfig.from_env().doctrine_path
    if action == "docgen":
        from .docgen.config import DocgenConfig

        return DocgenConfig.from_env().doctrine_path
    return None


def resolve(
    action: Action, *, default_path: str | None = None, strict: bool = False
) -> Snapshot:
    note = None
    try:
        row = (
            prompt_store.connection()
            .execute(
                "SELECT * FROM prompt_texts WHERE type = 'doctrine' AND name = ? ORDER BY version DESC LIMIT 1",
                (action,),
            )
            .fetchone()
            if prompt_store.is_configured()
            else None
        )
    except (sqlite3.Error, RuntimeError):
        if strict:
            raise
        row = None
        note = "Prompt store unavailable; using default instructions."
        logging.getLogger(__name__).warning("%s: %s", action, note)
    version = int(row["version"]) if row is not None else 0
    default_path = default_path or _default_path(action)
    source: Literal["saved", "default", "file"]
    if row is not None and not row["deleted"]:
        text, source = str(row["text"]), "saved"
    elif default_path is not None:
        try:
            text = Path(default_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            text, note = "", f"doctrine unreadable ({default_path}): {exc}"
        source = "file"
    else:
        text, source = default_text(action), "default"
    return Snapshot(
        action=action,
        version=version,
        source=source,
        text=text,
        note=note,
        digest=hashlib.sha256(text.encode()).hexdigest(),
    )


class EditorView(BaseModel):
    current: Snapshot
    default_text: str
    preview: str


def editor(action: Action) -> EditorView:
    current = resolve(action, strict=True)
    return EditorView(
        current=current,
        default_text=default_text(action),
        preview=preview(action, current.text),
    )


def preview(action: Action, text: str) -> str:
    """Use the runtime builders; per-request evidence and tool schemas stay dynamic."""
    if action == "ask":
        from .ask.prompts import build_system_prompt
    elif action == "ingest":
        from .ingest.prompts import build_system_prompt
    elif action == "research":
        from .research.prompts import build_system_prompt
    elif action == "draft_review":
        from .draft_review_model import build_system_prompt
    elif action == "alias_discovery":
        from .alias_suggestions import build_system_prompt
    else:
        from .docgen import prompts

        if action == "docgen":
            return prompts.build_system_prompt(
                text,
                guideline_set="Selected profile",
                document_type="Selected template",
                guidance="[Writing guidance from the selected profile]",
                exposure="[Disclosure rules from the selected profile]",
                template="[Selected document template]",
            )
        return prompts.build_review_system_prompt(
            instructions=text,
            guideline_set="Selected profile",
            document_type="Selected template",
            exposure="[Disclosure rules, if configured]",
            template="[Selected document template]",
        )
    return build_system_prompt(text)
