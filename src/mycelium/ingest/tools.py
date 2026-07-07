"""Tool wiring for the inner model.

Two kinds of tool reach the model:
  * the discovered substrate READ primitives (from `substrate.tool_specs()`),
    and
  * one **terminal** tool — `emit_draft` — that the model calls to finish.

The model has NO write tool. `emit_draft` does not write anything either; it is
how the model hands its decided ops to the deterministic harness, which is the
only thing that queues them into a draft (see `draft.py` / `loop.py`).

`emit_draft`'s schema is strict-compatible — built from `object` / `array` /
`string` / `enum` primitives only. The crucial shape choice: each op's payload
is a JSON-object **string** (`payload_json`), not a nested object. Draft op
payloads are heterogeneous (an `upsert_statement` payload looks nothing like an
`add_links` payload), so they cannot be one strict object schema; the model
serialises each payload and the deterministic code `json.loads` it.
"""

from __future__ import annotations

import json
from typing import Any

from ..ask.substrate import ToolSpec
from .schema import OpKind

EMIT_TOOL = "emit_draft"

#: The OpKind literal values, surfaced as the `op` enum. Kept in lockstep with
#: schema.OpKind via __args__ so the two never drift.
_OP_KINDS: list[str] = list(OpKind.__args__)  # type: ignore[attr-defined]

#: The classifications the model may stamp on a ledger row at emit time.
#: ("unprocessed" is harness-assigned on a budget cap, not a model choice.)
_LEDGER_CLASSIFICATIONS = [
    "new",
    "duplicate",
    "refinement",
    "contradiction",
    "unphraseable",
]

_EMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ops": {
            "type": "array",
            "description": (
                "The proposed substrate operations. Empty when every candidate "
                "was a duplicate or nothing was extractable. Each op replays as "
                "the named write tool at curator review time — you do not run it."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": _OP_KINDS,
                        "description": (
                            "The substrate write-tool function name this op "
                            "replays as."
                        ),
                    },
                    "payload_json": {
                        "type": "string",
                        "description": (
                            "A JSON-object STRING of that tool's kwargs — e.g. "
                            'for upsert_statement: "{\\"kind\\": \\"event\\", '
                            '\\"text\\": \\"an invite is submitted\\", '
                            '\\"links\\": []}" (mentions are derived from text, '
                            "not set). Must parse to "
                            "an object. Omit keys you are not setting (do not "
                            "send null). Edge key names DIFFER by op: add_links "
                            'edges are {"from_id", "to_id", "link_type", "when"?} '
                            "(statement<->statement); add_entity_links edges are "
                            '{"from_entity_id", "to_entity_id", "link_type"} '
                            "(entity<->entity) — do not mix the two."
                        ),
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "Why this op. For a REFINEMENT, put the old text -> "
                            "new text change here so the reviewer sees it."
                        ),
                    },
                    "targets_existing": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Existing statement/entity ids this op targets or "
                            "links to (provenance)."
                        ),
                    },
                },
                "required": ["op", "payload_json", "rationale", "targets_existing"],
            },
        },
        "ledger": {
            "type": "array",
            "description": (
                "The per-candidate reconcile ledger: ONE row per extracted "
                "candidate, proving each was reconciled before classification. "
                "A NEW/REFINEMENT row must carry a non-empty matched_against and "
                "either link_candidates_considered or a note saying no adjacent "
                "statements were found."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidate": {
                        "type": "string",
                        "description": "the extracted candidate fact, in words",
                    },
                    "classification": {
                        "type": "string",
                        "enum": _LEDGER_CLASSIFICATIONS,
                    },
                    "matched_against": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "existing ids this candidate was reconciled against",
                    },
                    "link_candidates_considered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "existing statements considered as link targets (the "
                            "adjacency search)"
                        ),
                    },
                    "note": {"type": "string"},
                },
                "required": [
                    "candidate",
                    "classification",
                    "matched_against",
                    "link_candidates_considered",
                    "note",
                ],
            },
        },
        "flagged": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Contradictions (name BOTH sides) and anything you scoped out "
                "rather than resolving. No automatic resolution is proposed for a "
                "contradiction."
            ),
        },
        "skipped_duplicates": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Candidates skipped because the claim already exists, each as "
                '"candidate :: existing_id".'
            ),
        },
    },
    "required": ["ops", "ledger", "flagged", "skipped_duplicates"],
}


def emit_tool_def() -> dict:
    """The single terminal tool. `strict` guarantees schema-valid inputs."""
    return {
        "name": EMIT_TOOL,
        "description": (
            "Conclude by handing the harness your decided ops, the per-candidate "
            "reconcile ledger, flagged contradictions, and skipped duplicates. "
            "Call this EXACTLY ONCE, and only once every candidate has been "
            "reconciled: at least one reconcile read and at least one adjacency "
            "search must have happened, and every NEW/REFINEMENT ledger row must "
            "show what it was matched against and what it considered linking to. "
            "The harness queues your ops into a draft for human review — it does "
            "NOT write to the substrate, and neither do you."
        ),
        "strict": True,
        "input_schema": _EMIT_SCHEMA,
    }


def build_tools(read_specs: list[ToolSpec]) -> list[dict]:
    """Full tool list handed to the model: read primitives + the emit terminal."""
    read_tools = [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in read_specs
    ]
    return read_tools + [emit_tool_def()]


def parse_emit_input(data: dict) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Parse an `emit_draft` tool input into (ops, ledger, flagged, skipped).

    Each op's `payload_json` string is parsed here into a `payload` dict, so the
    rest of the harness deals in plain dicts. Raises `ValueError` on a malformed
    input (bad types, unparseable payload_json) for the loop's
    re-prompt-once path. Per-op *semantic* validation (kind in valid_kinds,
    required keys, phrasing) is deferred to `_assemble_draft`, which flags rather
    than throws — this function only enforces the wire shape.
    """
    if not isinstance(data, dict):
        raise ValueError("emit_draft input is not an object")

    raw_ops = data.get("ops")
    if raw_ops is None:
        raw_ops = []
    if not isinstance(raw_ops, list):
        raise ValueError("ops must be an array")

    ops: list[dict] = []
    for i, raw in enumerate(raw_ops):
        if not isinstance(raw, dict):
            raise ValueError(f"ops[{i}] is not an object")
        op_name = raw.get("op")
        if not isinstance(op_name, str) or not op_name:
            raise ValueError(f"ops[{i}].op missing or not a string")
        payload_json = raw.get("payload_json")
        if not isinstance(payload_json, str):
            raise ValueError(f"ops[{i}].payload_json must be a JSON-object string")
        try:
            payload = json.loads(payload_json)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"ops[{i}].payload_json is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"ops[{i}].payload_json must encode a JSON object")
        ops.append(
            {
                "op": op_name,
                "payload": payload,
                "rationale": str(raw.get("rationale") or ""),
                "targets_existing": _str_list(raw.get("targets_existing")),
            }
        )

    ledger = _parse_ledger(data.get("ledger"))
    flagged = _str_list(data.get("flagged"))
    skipped = _str_list(data.get("skipped_duplicates"))
    return ops, ledger, flagged, skipped


def _parse_ledger(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("ledger must be an array")
    out: list[dict] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"ledger[{i}] is not an object")
        out.append(
            {
                "candidate": str(row.get("candidate") or ""),
                "classification": str(row.get("classification") or "unprocessed"),
                "matched_against": _str_list(row.get("matched_against")),
                "link_candidates_considered": _str_list(
                    row.get("link_candidates_considered")
                ),
                "note": str(row.get("note") or ""),
            }
        )
    return out


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]
