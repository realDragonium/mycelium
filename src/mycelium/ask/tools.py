"""Tool wiring for the inner model.

Two kinds of tool reach the model:
  * the discovered read primitives (from `substrate.tool_specs()`), and
  * two **terminal** tools — `submit_answer` and `request_clarification` —
    that the model calls to finish. Forcing the answer through a strict tool
    schema (rather than free-text JSON) is what makes the structured output
    reliable and keeps everything in one tool-use context.

The terminal-tool *inputs* carry a couple of extra fields beyond the public
`Answered`/`NeedsClarification` shapes (the sub-question ledger, the adjacency
note) — those feed the trace and the floor check, then are stripped when we map
onto the caller-facing models.
"""

from __future__ import annotations

from typing import Any

from .schema import Answered, Interpretation, NeedsClarification
from .substrate import ToolSpec

SUBMIT_TOOL = "submit_answer"
CLARIFY_TOOL = "request_clarification"
TERMINAL_TOOLS = frozenset({SUBMIT_TOOL, CLARIFY_TOOL})

_SUBMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {
            "type": "string",
            "description": (
                "The answer to what the caller actually asked. If the literal "
                "question is answerable but a more relevant question exists, "
                "answer it AND say so here — never withhold a real answer on a "
                "hunch. State contradictions explicitly; never silently pick."
            ),
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": (
                "Derived from gaps, not vibes. high = derivation chain walked, "
                "key terms resolved, no open contradictions. medium = supported "
                "but with non-trivial gaps. low = key terms returned nothing, "
                "the question references things absent from the substrate, or "
                "the cap was hit with the core unresolved. Do not round up."
            ),
        },
        "interpretation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "as_asked": {"type": "string", "description": "the caller's literal question"},
                "resolved_to": {"type": "string", "description": "what you set out to answer"},
                "reframed": {"type": "boolean"},
                "reframe_reason": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "why you reframed, or null",
                },
            },
            "required": ["as_asked", "resolved_to", "reframed", "reframe_reason"],
        },
        "sub_questions": {
            "type": "array",
            "description": (
                "The sub-questions the question decomposes into, each marked "
                "resolved / partial / unresolved. This ledger informs gaps and "
                "goes into the trace."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sub_question": {"type": "string"},
                    "status": {"type": "string", "enum": ["resolved", "partial", "unresolved"]},
                    "note": {"type": "string"},
                },
                "required": ["sub_question", "status", "note"],
            },
        },
        "adjacency_note": {
            "type": "string",
            "description": (
                "What the concept-seeded re-search surfaced (statements with no "
                "edge pointing at them, reachable via mentions / shared entity / "
                "embedding proximity) — or 'nothing new'. Required: the loop will "
                "not let you conclude without having attempted it and reported it."
            ),
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Unresolved parts, zero-result terms (absence is a signal, not "
                "inference), relevant-but-unfollowed links, adjacency considered-"
                "and-rejected, open contradictions."
            ),
        },
        "provenance": {
            "type": "array",
            "items": {"type": "string"},
            "description": "statement ids the answer rests on",
        },
    },
    "required": [
        "answer",
        "confidence",
        "interpretation",
        "sub_questions",
        "adjacency_note",
        "gaps",
        "provenance",
    ],
}

_CLARIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question": {
            "type": "string",
            "description": "the single clarifying question to hand back to the caller",
        },
        "candidates": {
            "type": "array",
            "description": (
                "Two or more genuinely distinct interpretations, each naming the "
                "topics/entities it would pull. These are real (recon already "
                "ran), not guessed."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "interpretation": {"type": "string"},
                    "would_pull": {
                        "type": "string",
                        "description": "the topics/entities this interpretation would retrieve",
                    },
                },
                "required": ["interpretation", "would_pull"],
            },
        },
        "known_so_far": {
            "type": "string",
            "description": "what recon established, so the caller has context",
        },
    },
    "required": ["question", "candidates", "known_so_far"],
}


_SUBMIT_DESC_FLOOR = (
    "Conclude with the structured answer. Only call this once the "
    "floor is met: recon ran, at least one targeted retrieval round "
    "happened, and at least one concept-seeded adjacency re-search "
    "was attempted and is reported in adjacency_note."
)
#: Quick-mode: the floor is off, so don't demand the adjacency re-search — call
#: as soon as recon plus a targeted read or two answer the question.
_SUBMIT_DESC_QUICK = (
    "Conclude with the structured answer. Call this as soon as recon plus a "
    "targeted retrieval or two answer the question — no adjacency re-search is "
    "required in quick mode (put 'skipped — quick mode' in adjacency_note if you "
    "skip it). Still fill every required field honestly."
)

#: Quick-mode text for the `adjacency_note` *field*. The floor version (baked
#: into `_SUBMIT_SCHEMA`) says the loop won't let you conclude without it — false
#: in quick mode, and left uncorrected it would push the model to re-search
#: anyway, defeating the point. So the field description is depth-aware too.
_ADJACENCY_DESC_QUICK = (
    "What a concept-seeded re-search surfaced (statements with no edge pointing "
    "at them, reachable via mentions / shared entity / embedding proximity) — or "
    "'nothing new'. OPTIONAL in quick mode: if you skipped the re-search, put "
    "'skipped — quick mode' here. Still a required field, so never leave it empty."
)


def _submit_schema(*, enforce_floor: bool) -> dict[str, Any]:
    """The `submit_answer` input schema, adjacency_note description tuned to the
    depth. Floor-on returns the module constant unchanged (so `standard` is
    byte-for-byte identical); floor-off swaps only that one field's description."""
    if enforce_floor:
        return _SUBMIT_SCHEMA
    props = dict(_SUBMIT_SCHEMA["properties"])
    props["adjacency_note"] = {
        **props["adjacency_note"],
        "description": _ADJACENCY_DESC_QUICK,
    }
    return {**_SUBMIT_SCHEMA, "properties": props}


def terminal_tool_defs(*, enforce_floor: bool = True) -> list[dict]:
    """The two terminal tools. `strict` guarantees schema-valid inputs.

    `enforce_floor` tunes the `submit_answer` description AND its adjacency_note
    field text (the structural gate itself lives in the loop): off, both drop the
    adjacency demand so a quick-mode model isn't told to do work the loop won't
    require.
    """
    return [
        {
            "name": SUBMIT_TOOL,
            "description": _SUBMIT_DESC_FLOOR if enforce_floor else _SUBMIT_DESC_QUICK,
            "strict": True,
            "input_schema": _submit_schema(enforce_floor=enforce_floor),
        },
        {
            "name": CLARIFY_TOOL,
            "description": (
                "Stop and ask for disambiguation. Use ONLY for genuine ambiguity "
                "(two or more plausible distinct referents, or you can't tell "
                "which question serves the caller's goal). This is terminal — the "
                "caller will re-ask. Do not also commit an answer."
            ),
            "strict": True,
            "input_schema": _CLARIFY_SCHEMA,
        },
    ]


def build_tools(specs: list[ToolSpec], *, enforce_floor: bool = True) -> list[dict]:
    """Full tool list handed to the model: read primitives + terminal tools."""
    read_tools = [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in specs
    ]
    return read_tools + terminal_tool_defs(enforce_floor=enforce_floor)


def answered_from_tool_input(data: dict, trace: dict) -> Answered:
    """Map a `submit_answer` tool input onto the public `Answered` model.

    The ledger / adjacency_note live in `trace`, not on `Answered`.
    """
    interp = data["interpretation"]
    return Answered(
        answer=data["answer"],
        confidence=data["confidence"],
        interpretation=Interpretation(
            as_asked=interp["as_asked"],
            resolved_to=interp["resolved_to"],
            reframed=bool(interp["reframed"]),
            reframe_reason=interp.get("reframe_reason"),
        ),
        gaps=list(data.get("gaps") or []),
        provenance=list(data.get("provenance") or []),
        trace=trace,
    )


def clarification_from_tool_input(data: dict, trace: dict) -> NeedsClarification:
    return NeedsClarification(
        question=data["question"],
        candidates=list(data.get("candidates") or []),
        known_so_far=data.get("known_so_far", ""),
        trace=trace,
    )
