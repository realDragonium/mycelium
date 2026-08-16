"""Write connected-batch proposals as individually editable draft operations.

Batch-local references become replay-time references to the batch operation result.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from mycelium import drafts_store, store

from .cue_gate import ABSORBING_DECISIONS, CueResolution
from .extract import FLAG_SOURCES, FlagInput
from .proposals import Proposal

_BATCH_TARGET = re.compile(r"^@(\d+)$")
_PROPOSAL_ORDER = {"link": 0, "merge": 1, "conflict": 2}


@dataclass(frozen=True)
class BatchInput:
    kind: str
    text: str
    links: list[dict] = field(default_factory=list)
    allow_phrasing_violations: bool = False


def _batch_payload(batch: list[BatchInput]) -> dict:
    """Build the single batch-upsert payload without default-valued fields."""
    statements = []
    for item in batch:
        statement = {"kind": item.kind, "text": item.text}
        if item.links:
            statement["links"] = item.links
        if item.allow_phrasing_violations:
            statement["allow_phrasing_violations"] = True
        statements.append(statement)
    return {"statements": statements}


def _draft_ref(reference: str, batch_seq: int) -> str:
    """Rewrite a bare batch sibling reference for cross-op replay."""
    match = _BATCH_TARGET.fullmatch(reference)
    return f"@{batch_seq}:{match.group(1)}" if match else reference


def _conflict_text(
    proposal: Proposal,
    batch: list[BatchInput],
    text_of: Callable[[str], str | None],
) -> str:
    """Render a contradiction proposal for the existing gap primitive."""
    provenance = proposal.provenance
    forward = provenance["forward"]
    backward = provenance["backward"]
    existing_text = text_of(proposal.target) or ""
    return (
        f"Possible contradiction — new statement #{proposal.new_index} "
        f'"{batch[proposal.new_index].text}" vs {proposal.target} '
        f'"{existing_text}". NLI: forward {forward["label"]} '
        f"({forward['confidence']:.2f}), backward {backward['label']} "
        f"({backward['confidence']:.2f}); similarity "
        f"{provenance['score']:.2f}."
    )


def _proposal_op(
    proposal: Proposal,
    batch: list[BatchInput],
    text_of: Callable[[str], str | None],
    batch_seq: int,
) -> tuple[str, dict]:
    """Map one proposal to an existing replayable tool operation."""
    source = f"@{batch_seq}:{proposal.new_index}"
    target = _draft_ref(proposal.target, batch_seq)
    if proposal.kind == "link":
        return (
            "add_links",
            {
                "links": [
                    {
                        "from_id": source,
                        "to_id": target,
                        "link_type": proposal.link_type,
                    }
                ]
            },
        )
    if proposal.kind == "merge":
        return "merge_statements", {"from_id": source, "into_id": target}
    if proposal.kind == "conflict":
        return "report_knowledge_gap", {
            "text": _conflict_text(proposal, batch, text_of)
        }
    raise ValueError(f"unknown proposal kind: {proposal.kind}")


def assemble_draft(
    conn: sqlite3.Connection,
    *,
    batch: list[BatchInput],
    proposals: list[Proposal],
    text_of: Callable[[str], str | None],
    created_by: str | None,
    title: str | None = None,
    session_id: str | None = None,
    flags: Sequence[FlagInput] = (),
    cues: Sequence[CueResolution] = (),
) -> str:
    """Write a connected batch and its proposals into one open draft."""
    with store.transaction(conn):
        draft_id = drafts_store.create_draft(
            conn,
            created_by=created_by,
            session_id=session_id,
            title=title,
        )
        if batch:
            batch_seq = drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="upsert_statements",
                payload=_batch_payload(batch),
                created_by=created_by,
            )
            ordered_proposals = sorted(
                proposals, key=lambda proposal: _PROPOSAL_ORDER[proposal.kind]
            )
            for proposal in ordered_proposals:
                kind, payload = _proposal_op(proposal, batch, text_of, batch_seq)
                drafts_store.add_op(
                    conn,
                    draft_id=draft_id,
                    kind=kind,
                    payload=payload,
                    provenance=proposal.provenance,
                    created_by=created_by,
                )
        # Replay is what writes an alias, so a rejected draft never teaches the
        # vocabulary.
        for resolution in cues:
            if resolution.decision not in ABSORBING_DECISIONS:
                continue
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="upsert_link_type_alias",
                payload={
                    "link_type": resolution.link_type,
                    "alias": resolution.cue,
                    "provenance": resolution.decision,
                    "score": resolution.score,
                },
                provenance={
                    "source": "cue-gate",
                    "cue": resolution.cue,
                    "candidates": [list(c) for c in resolution.candidates],
                },
                created_by=created_by,
            )
        for flag in flags:
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind="flag",
                payload={
                    "text": flag.text,
                    "reason": flag.reason,
                    "detail": flag.detail,
                    "sentence": flag.sentence,
                    "span": list(flag.span),
                },
                provenance={
                    **(flag.provenance or {}),
                    "source": FLAG_SOURCES[flag.reason],
                    "reason": flag.reason,
                    "fragment_index": flag.fragment_index,
                },
                created_by=created_by,
            )
    return draft_id


def summarize(conn: sqlite3.Connection, draft_id: str) -> dict:
    """Summarize the draft's current, possibly edited operation set."""
    statements = 0
    links = 0
    merges = 0
    conflicts = 0
    flags = 0
    aliases = 0
    for op in drafts_store.list_ops(conn, draft_id):
        kind = op["kind"]
        if kind == "upsert_statements":
            payload = json.loads(op["payload_json"])
            statements += len(payload.get("statements", []))
        elif kind == "add_links":
            payload = json.loads(op["payload_json"])
            links += len(payload.get("links", []))
        elif kind == "merge_statements":
            merges += 1
        elif kind == "report_knowledge_gap":
            conflicts += 1
        elif kind == "flag":
            flags += 1
        elif kind == "upsert_link_type_alias":
            aliases += 1
    return {
        "draft_id": draft_id,
        "statements": statements,
        "links": links,
        "merges": merges,
        "conflicts": conflicts,
        "flags": flags,
        "aliases": aliases,
    }
