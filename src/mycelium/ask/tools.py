"""Tool wiring for the inner model.

Two kinds of tool reach the model:
  * the discovered read primitives (from `substrate.tool_specs()`), and
  * two **terminal** tools — `submit_answer` and `request_clarification` —
    that the model calls to finish. Forcing the answer through a strict tool
    schema (rather than free-text JSON) is what makes the structured output
    reliable and keeps everything in one tool-use context.

Terminal inputs carry only prose, uncertainty, interpretation changes and
evidence references. The harness supplies deterministic result metadata.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..agentloop import read_tool_defs
from .schema import Answered, Interpretation, NeedsClarification
from .substrate import ToolSpec

SUBMIT_TOOL = "submit_answer"
CLARIFY_TOOL = "request_clarification"
TERMINAL_TOOLS = frozenset({SUBMIT_TOOL, CLARIFY_TOOL})


class InterpretationChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resolved_to: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(
        min_length=1,
        description="Answer the literal question when answerable. State contradictions and relevant conditions explicitly.",
    )
    confidence: Literal["high", "medium", "low"]
    interpretation: InterpretationChange | None = Field(
        description="Null unless the interpretation changed; then give the resolved question and reason."
    )
    gaps: list[str] = Field(
        description="Unresolved coverage, absent terms, unfollowed relevant links, contradictions and rejected adjacency. Confidence must reflect these gaps."
    )
    provenance: list[str] = Field(
        description="Short statement refs (s1, s2, ...) supplied in evidence; never entity IDs or unread link targets."
    )


_SUBMIT_SCHEMA = AnswerInput.model_json_schema()


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    interpretation: str = Field(min_length=1)
    would_pull: str = Field(
        min_length=1,
        description="The real topics/entities this interpretation would retrieve.",
    )


class ClarificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1)
    candidates: list[CandidateInput] = Field(min_length=2)
    known_so_far: str


_CLARIFY_SCHEMA = ClarificationInput.model_json_schema()


_SUBMIT_DESC_FLOOR = (
    "Conclude only after targeted retrieval and a later concept-seeded adjacency re-search. "
    "Report substantive uncertainty in gaps; code records retrieval checks and original question."
)
_SUBMIT_DESC_QUICK = (
    "Conclude when evidence supports an answer; no adjacency re-search is required in quick mode. "
    "Report substantive uncertainty in gaps."
)


def terminal_tool_defs(*, enforce_floor: bool = True) -> list[dict]:
    """Describe the evidence gate for this depth; validate inputs locally too."""
    return [
        {
            "name": SUBMIT_TOOL,
            "description": _SUBMIT_DESC_FLOOR if enforce_floor else _SUBMIT_DESC_QUICK,
            "strict": True,
            "input_schema": _SUBMIT_SCHEMA,
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
    tools = read_tool_defs(specs)
    for tool in tools:
        if tool["name"] in {"search_statements", "survey_statements"}:
            schema = dict(tool["input_schema"])
            schema["properties"] = {
                **schema.get("properties", {}),
                "adjacency_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For adjacency research: refs of statements already supplied by earlier turns whose concepts seed this query. Omit for ordinary targeted search.",
                },
            }
            tool["input_schema"] = schema
    return tools + terminal_tool_defs(enforce_floor=enforce_floor)


def answered_from_tool_input(data: dict, trace: dict) -> Answered:
    parsed = AnswerInput.model_validate(data)
    change = parsed.interpretation
    return Answered(
        answer=parsed.answer,
        confidence=parsed.confidence,
        interpretation=Interpretation(
            as_asked=trace["question"],
            resolved_to=change.resolved_to if change else trace["question"],
            reframed=change is not None,
            reframe_reason=change.reason if change else None,
        ),
        gaps=parsed.gaps,
        provenance=parsed.provenance,
        trace=trace,
    )


def clarification_from_tool_input(data: dict, trace: dict) -> NeedsClarification:
    parsed = ClarificationInput.model_validate(data)
    return NeedsClarification(
        question=parsed.question,
        candidates=[candidate.model_dump() for candidate in parsed.candidates],
        known_so_far=parsed.known_so_far,
        trace=trace,
    )
