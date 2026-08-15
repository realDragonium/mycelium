"""Write connected-batch proposals as individually editable draft operations.

Batch-local references become replay-time references to the batch operation result.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from mycelium import drafts_store, store

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


def _draft_ref(reference: str) -> str:
    """Rewrite a bare batch sibling reference for cross-op replay."""
    match = _BATCH_TARGET.fullmatch(reference)
    return f"@1:{match.group(1)}" if match else reference


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
) -> tuple[str, dict]:
    """Map one proposal to an existing replayable tool operation."""
    source = f"@1:{proposal.new_index}"
    target = _draft_ref(proposal.target)
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
) -> str:
    """Write a connected batch and its proposals into one open draft."""
    with store.transaction(conn):
        draft_id = drafts_store.create_draft(
            conn,
            created_by=created_by,
            session_id=session_id,
            title=title,
        )
        drafts_store.add_op(
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
            kind, payload = _proposal_op(proposal, batch, text_of)
            drafts_store.add_op(
                conn,
                draft_id=draft_id,
                kind=kind,
                payload=payload,
                provenance=proposal.provenance,
                created_by=created_by,
            )
    return draft_id


def summarize(conn: sqlite3.Connection, draft_id: str) -> dict:
    """Summarize the draft's current, possibly edited operation set."""
    statements = 0
    links = 0
    merges = 0
    conflicts = 0
    for op in drafts_store.list_ops(conn, draft_id):
        kind = op["kind"]
        if kind == "upsert_statements" and op["seq"] == 1:
            payload = json.loads(op["payload_json"])
            statements = len(payload.get("statements", []))
        elif kind == "add_links":
            links += 1
        elif kind == "merge_statements":
            merges += 1
        elif kind == "report_knowledge_gap":
            conflicts += 1
    return {
        "draft_id": draft_id,
        "statements": statements,
        "links": links,
        "merges": merges,
        "conflicts": conflicts,
    }
