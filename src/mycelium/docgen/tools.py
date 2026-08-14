"""Tool wiring for the inner model.

Three kinds of tool reach the model:

  * the discovered substrate READ primitives (from `substrate.tool_specs()`),
    which this module never names — `ask/substrate.py` decides what a read is,
    so a new read primitive reaches a documentation run with no edit here;
  * `report_knowledge_gap`, named explicitly because it is the one thing
    `ask/substrate.py` deliberately withholds. It carries `role="reader"` but
    writes a knowledge-gap record, so auto-discovery excludes it and every
    loop that wants it says so. A generation run wants it: a guideline
    section the substrate cannot support is a gap to file, not a paragraph to
    invent;
  * one **terminal** tool, `emit_document`, which is how the model hands the
    finished document to the harness.

There is no write tool and no `draft_id` splice, so nothing a documentation
run produces can reach the substrate.

`emit_document` takes a title, a body, and the statement ids the body rests
on. It does NOT take a slug: the page's identity is derived from the title by
the harness, so two runs that agree on the title agree on the page without
the model having to remember a naming convention.
"""

from __future__ import annotations

from typing import Any

from ..agentloop import read_tool_defs
from ..ask.substrate import ToolSpec

EMIT_TOOL = "emit_document"
GAP_TOOL = "report_knowledge_gap"
RESOLVE_TOOL = "choose_guideline_set"

_EMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {
            "type": "string",
            "description": (
                "The document's title, as a reader would see it. The page's "
                "stable identity is derived from it, so title the topic — "
                "'Configuring single sign-on' — rather than the request."
            ),
        },
        "body": {
            "type": "string",
            "description": (
                "The finished document in Markdown, written against the "
                "guideline set's template. Complete as it stands — nothing "
                "downstream edits it, fills a placeholder, or resolves a "
                "'TODO'."
            ),
        },
        "statement_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "The substrate statement ids (stm_…) this body rests on. "
                "Every one must be a statement you actually read during this "
                "run. A document with none is refused rather than recorded, "
                "and so is one citing an id this run never retrieved — an "
                "unsourced document is worse than no document."
            ),
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "What the template asked for that the substrate could not "
                "supply, and anything you marked as needing verification. "
                "Report each through report_knowledge_gap as you meet it; "
                "this is your own summary of the same ground."
            ),
        },
    },
    "required": ["title", "body", "statement_ids", "gaps"],
}

_GAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {
            "type": "string",
            "description": (
                "What the substrate could not answer, in enough detail that a "
                "curator can act on it: the topic, what the template needed, "
                "and which searches came back empty."
            ),
        }
    },
    "required": ["text"],
}


def emit_tool_def() -> dict:
    """The single terminal tool. `strict` guarantees schema-valid inputs."""
    return {
        "name": EMIT_TOOL,
        "description": (
            "Conclude by handing the harness the finished document: its "
            "title, its Markdown body, and the statement ids the body rests "
            "on. Call this EXACTLY ONCE, and only once every section either "
            "rests on statements you retrieved or is honestly marked. The "
            "harness stores what you hand it — there is no later editing "
            "pass."
        ),
        "strict": True,
        "input_schema": _EMIT_SCHEMA,
    }


def gap_tool_def() -> dict:
    """`report_knowledge_gap`, the one reader-role write the loop offers."""
    return {
        "name": GAP_TOOL,
        "description": (
            "File a gap in the knowledge base for a human curator. Call this "
            "whenever the guideline set asks for something the substrate does "
            "not hold — a section with no statements behind it, a "
            "contradiction between two, a fact you could only supply from "
            "your own prior knowledge. Filing it is what you do INSTEAD of "
            "writing the fact. Not terminal: keep going afterwards."
        ),
        "strict": True,
        "input_schema": _GAP_SCHEMA,
    }


def resolve_tool_def(catalogue: dict[str, list[str]], preferred: str | None) -> dict:
    """The forced tool of the resolution turn, built from the live catalogue.

    The enums ARE the store's contents, so a set added as three
    `save_prompt_text` calls is selectable on the next run and the model
    cannot name one that does not exist. `document_type` spans every set's
    types because a strict schema has no way to say "depends on the other
    field" — the pair is checked against the catalogue afterwards, and a
    mismatched pair is sent back rather than accepted.
    """
    sets = sorted(catalogue)
    types = sorted({t for slots in catalogue.values() for t in slots})
    hint = (
        f" This instance prefers '{preferred}' when nothing in the request "
        "points elsewhere."
        if preferred in catalogue
        else ""
    )
    return {
        "name": RESOLVE_TOOL,
        "description": (
            "Choose the guideline set and the document type this request "
            "should be written against, from what is configured." + hint
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "guideline_set": {"type": "string", "enum": sets},
                "document_type": {
                    "type": "string",
                    "enum": types,
                    "description": (
                        "Must be one the chosen set actually has a template "
                        "for; the listing in the message says which."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "One sentence: what in the request decided it.",
                },
            },
            "required": ["guideline_set", "document_type", "reason"],
        },
    }


def build_tools(read_specs: list[ToolSpec]) -> list[dict]:
    """Full tool list handed to the model: the discovered read primitives,
    the knowledge-gap report, and the emit terminal."""
    return read_tool_defs(read_specs) + [gap_tool_def(), emit_tool_def()]


def parse_emit_input(data: dict) -> tuple[str, str, list[str], list[str]]:
    """Parse an `emit_document` tool input into (title, body, ids, gaps).

    Wire shape only — raises `ValueError` for the loop's re-prompt path. What
    makes a document *acceptable* (ids present, ids actually retrieved, a
    title that yields a slug) is the loop's gate, not this function's, because
    those are re-promptable judgements about the run rather than malformed
    JSON.
    """
    if not isinstance(data, dict):
        raise ValueError("emit_document input is not an object")
    title = data.get("title")
    if not isinstance(title, str):
        raise ValueError("title must be a string")
    body = data.get("body")
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    ids = _str_list(data.get("statement_ids"))
    gaps = _str_list(data.get("gaps"))
    return title.strip(), body, ids, gaps


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]
