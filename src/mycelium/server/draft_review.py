"""Reviewing a submitted draft: what it would change, and whether it still can.

`inspect_draft_review` returns the exact draft revision together with a
fingerprint of every statement and entity its operations touch. A review
records both, so a recorded outcome only applies to the knowledge it was made
against: if either has changed by the time the outcome is recorded or applied,
the review is refused as stale. The operation findings flag what replay
would trip over before anyone approves it.
"""

from __future__ import annotations

import hashlib
import json as _json
import re
import sqlite3
from typing import Any, Literal, TypedDict

from pydantic import JsonValue

from .. import mentions, phrasing, store
from .draft_queue import _MUTATION_PREFIXES
from .drafts import _identified_principal, _require_mutable_draft
from .entities import get_entity
from .lookups import get_statements
from .registry import _ORIG_SIGNATURES, TOOLS, tool
from .runtime import _db, _drafts_db
from .specs import (
    BatchStatementSpec,
    EdgeSpec,
    EntityEdgeSpec,
    IncomingLinkSpec,
    LinkSpec,
)


class KnowledgePrecondition(TypedDict):
    kind: Literal["entity", "statement"]
    id: str
    fingerprint: str


class DraftOperationFinding(TypedDict):
    operation_ref: str
    kind: str
    finding: str


class DraftReviewRecord(TypedDict):
    review_id: str
    draft_id: str
    outcome: Literal["accepted", "refined", "rejected", "needs_context"]
    rationale: str
    draft_revision: int
    knowledge_preconditions: list[KnowledgePrecondition]
    unresolved_questions: list[str]
    reviewed_at: str
    reviewed_by: str


class DraftReviewInspection(TypedDict):
    draft: dict[str, JsonValue]
    draft_revision: int
    knowledge_preconditions: list[KnowledgePrecondition]
    operation_findings: list[DraftOperationFinding]
    unresolved: bool
    reviews: list[DraftReviewRecord]
    applications: list[dict[str, JsonValue]]


class DraftCorrectionReceipt(TypedDict):
    draft_id: str
    operation_ref: str
    seq: int
    revision: int


def _payload_knowledge_ids(
    value: JsonValue,
) -> tuple[set[str], set[str], set[str]]:
    entities: set[str] = set()
    statements: set[str] = set()
    names: set[str] = set()

    def visit(item: JsonValue) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            if item.startswith("ent_"):
                entities.add(item)
            elif item.startswith("stm_"):
                statements.add(item)
            elif item.startswith("nam_"):
                names.add(item)

    visit(value)
    return entities, statements, names


def _fingerprint(value: JsonValue) -> str:
    encoded = _json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


# Only these operations recompute mentions on existing statements; a statement
# that merely mentions an entity the draft touches is not affected otherwise.
_MENTION_REMAPPING_OPERATIONS = frozenset(
    {"merge_entities", "move_name", "rename_name", "delete_name", "delete_entity"}
)


def _name_owner_ids(name_ids: set[str]) -> set[str]:
    owners: set[str] = set()
    for name_id in name_ids:
        row = store.get_name_by_id(_db(), name_id)
        if row is not None:
            owners.add(row["entity_id"])
    return owners


def _named_entity_ids(
    kind: str, payload: dict[str, Any], all_names: list[sqlite3.Row]
) -> set[str]:
    entity_ids: set[str] = set()
    texts: list[str] = []
    if isinstance(payload.get("text"), str):
        texts.append(payload["text"])
    texts.extend(
        item["text"]
        for item in payload.get("statements", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )
    for name_row in all_names:
        if any(mentions.text_contains_name(text, name_row["text"]) for text in texts):
            entity_ids.add(name_row["entity_id"])
    names: list[str] = []
    if kind == "upsert_entity" and isinstance(payload.get("name"), str):
        names.append(payload["name"])
    if kind == "upsert_entities":
        names.extend(
            item["name"]
            for item in payload.get("entities", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
    for name in names:
        row = store.get_name_by_text(_db(), name)
        if row is not None:
            entity_ids.add(row["entity_id"])
    return entity_ids


def _knowledge_preconditions(ops: list[sqlite3.Row]) -> list[KnowledgePrecondition]:
    entity_ids: set[str] = set()
    remapped_entity_ids: set[str] = set()
    statement_ids: set[str] = set()
    all_names = store.list_all_names(_db())
    for op in ops:
        payload = _json.loads(op["payload_json"])
        entities, statements, names = _payload_knowledge_ids(payload)
        targeted = entities | _name_owner_ids(names)
        entity_ids.update(targeted)
        entity_ids.update(_named_entity_ids(op["kind"], payload, all_names))
        statement_ids.update(statements)
        if op["kind"] in _MENTION_REMAPPING_OPERATIONS:
            remapped_entity_ids.update(targeted)

    for entity_id in remapped_entity_ids:
        for name_row in store.get_names_by_entity(_db(), entity_id):
            statement_ids.update(
                store.statements_mentioning_name(_db(), name_row["id"])
            )

    out: list[KnowledgePrecondition] = []
    for entity_id in sorted(entity_ids):
        entity = get_entity(entity_id)
        out.append(
            {"kind": "entity", "id": entity_id, "fingerprint": _fingerprint(entity)}
        )
    ordered_statement_ids = sorted(statement_ids)
    statements = get_statements(ordered_statement_ids)["statements"]
    statements_by_id = {statement["id"]: statement for statement in statements}
    for statement_id in ordered_statement_ids:
        hydrated = statements_by_id.get(statement_id)
        statement: JsonValue = (
            {"statements": [hydrated], "missing": []}
            if hydrated is not None
            else {"statements": [], "missing": [statement_id]}
        )
        out.append(
            {
                "kind": "statement",
                "id": statement_id,
                "fingerprint": _fingerprint(statement),
            }
        )
    return out


def _review_knowledge_preconditions(
    ops: list[sqlite3.Row], expected: list[KnowledgePrecondition]
) -> list[KnowledgePrecondition]:
    """Include supporting records actually inspected beyond operation targets."""
    current = {
        (item["kind"], item["id"]): item for item in _knowledge_preconditions(ops)
    }
    for item in expected:
        key = (item["kind"], item["id"])
        if key in current:
            continue
        value = (
            get_entity(item["id"])
            if item["kind"] == "entity"
            else get_statements([item["id"]])
        )
        current[key] = {
            "kind": item["kind"],
            "id": item["id"],
            "fingerprint": _fingerprint(value),
        }
    return [current[key] for key in sorted(current)]


def _batch_nested_parameter_findings(payload: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    allowed = set(BatchStatementSpec.__annotations__)
    for index, item in enumerate(payload.get("statements", [])):
        if not isinstance(item, dict):
            continue
        unknown = sorted(set(item) - allowed)
        if unknown:
            findings.append(
                f"unknown_parameters:statements[{index}]." + ",".join(unknown)
            )
        for path, link_allowed in (
            ("links", set(LinkSpec.__annotations__)),
            ("incoming_links", set(IncomingLinkSpec.__annotations__)),
        ):
            for link_index, link in enumerate(item.get(path, [])):
                if isinstance(link, dict):
                    unknown_link = sorted(set(link) - link_allowed)
                    if unknown_link:
                        findings.append(
                            f"unknown_parameters:statements[{index}]."
                            f"{path}[{link_index}]." + ",".join(unknown_link)
                        )
    return findings


def _nested_parameter_findings(kind: str, payload: dict[str, Any]) -> list[str]:
    specs: list[tuple[str, JsonValue, set[str]]] = []
    if kind in ("add_links", "remove_links"):
        specs.append(("links", payload.get("links", []), set(EdgeSpec.__annotations__)))
    elif kind in ("add_entity_links", "remove_entity_links"):
        specs.append(
            ("links", payload.get("links", []), set(EntityEdgeSpec.__annotations__))
        )
    elif kind == "upsert_statement":
        specs.extend(
            (
                ("links", payload.get("links", []), set(LinkSpec.__annotations__)),
                (
                    "incoming_links",
                    payload.get("incoming_links", []),
                    set(IncomingLinkSpec.__annotations__),
                ),
            )
        )
    findings: list[str] = []
    for path, items, allowed in specs:
        if isinstance(items, list):
            for index, item in enumerate(items):
                if isinstance(item, dict):
                    unknown = sorted(set(item) - allowed)
                    if unknown:
                        findings.append(
                            f"unknown_parameters:{path}[{index}]." + ",".join(unknown)
                        )
    if kind == "upsert_statements":
        findings.extend(_batch_nested_parameter_findings(payload))
    return findings


def _unbypassed_phrasing_texts(
    kind: str, payload: dict[str, Any]
) -> list[tuple[str, str, str]]:
    if payload.get("allow_phrasing_violations"):
        return []
    if kind == "upsert_statements":
        return [
            (f"statements[{index}]", item["text"], item["kind"])
            for index, item in enumerate(payload.get("statements", []))
            if isinstance(item, dict)
            and isinstance(item.get("text"), str)
            and isinstance(item.get("kind"), str)
            and not item.get("allow_phrasing_violations")
        ]
    if kind == "upsert_statement" and isinstance(payload.get("text"), str):
        return [("text", payload["text"], str(payload.get("kind") or "event"))]
    if kind in ("replace_text", "patch_statement") and isinstance(
        payload.get("text"), str
    ):
        row = store.get_statement(_db(), str(payload.get("id")))
        statement_kind = payload.get("kind") or (row["kind"] if row else None)
        return [("text", payload["text"], str(statement_kind or "event"))]
    return []


def _phrasing_findings(kind: str, payload: dict[str, Any]) -> list[str]:
    return [
        f"phrasing:{position}:{violation['rule']}: {violation['recommendation']}"
        for position, text, statement_kind in _unbypassed_phrasing_texts(kind, payload)
        for violation in phrasing.check(text, kind=statement_kind)
    ]


def _draft_operation_findings(ops: list[sqlite3.Row]) -> list[DraftOperationFinding]:
    from .. import drafts_store

    findings: list[DraftOperationFinding] = []
    tools_by_name = {wrapper.__name__: wrapper for wrapper in TOOLS}
    producers = {int(op["seq"]): op for op in ops}
    for op in ops:
        kind = op["kind"]
        operation_ref = op["id"]
        if kind == drafts_store.ALIAS_SUGGESTION_KIND:
            from ..alias_suggestions import Suggestion

            suggestion = Suggestion.model_validate_json(op["payload_json"])
            messages = (
                ["alias_requires_human_review"]
                if suggestion.status == "pending"
                else []
            )
        elif kind == "flag":
            messages = ["unresolved_flag"]
        elif kind in drafts_store.NON_REPLAYING_OP_KINDS:
            messages = []
        elif kind not in tools_by_name or kind not in _ORIG_SIGNATURES:
            messages = ["obsolete_tool"]
        else:
            payload = _json.loads(op["payload_json"])
            unknown = sorted(set(payload) - set(_ORIG_SIGNATURES[kind].parameters))
            messages = ["unknown_parameters:" + ",".join(unknown)] if unknown else []
            messages.extend(_nested_parameter_findings(kind, payload))
            messages.extend(_phrasing_findings(kind, payload))
        for reference, result_index_text in re.findall(
            r'"@(\d+):(\d+)"', op["payload_json"]
        ):
            producer = int(reference)
            producer_op = producers.get(producer)
            result_index = int(result_index_text)
            if producer_op is None or producer >= int(op["seq"]):
                messages.append(f"unresolved_operation_reference:@{reference}")
            elif producer_op["kind"] != "upsert_statements" or result_index >= len(
                _json.loads(producer_op["payload_json"]).get("statements", [])
            ):
                messages.append(
                    f"unresolved_operation_reference:@{reference}:{result_index_text}"
                )
        findings.extend(
            {"operation_ref": operation_ref, "kind": kind, "finding": message}
            for message in messages
        )
    return findings


@tool(role="writer", real_role=True)
def inspect_draft_review(draft_id: str) -> DraftReviewInspection:
    """Inspect exact draft content and affected knowledge for review."""
    from .. import drafts_store

    _identified_principal()
    row, ops = drafts_store.get_draft_snapshot(_drafts_db(), draft_id)
    if row is None:
        raise ValueError(f"draft '{draft_id}' not found")
    findings = _draft_operation_findings(ops)
    reviews = drafts_store.list_reviews(_drafts_db(), draft_id)
    applications = drafts_store.list_applications(_drafts_db(), draft_id)
    return {
        "draft": drafts_store.serialize_draft(row, ops=ops),
        "draft_revision": int(row["revision"]),
        "knowledge_preconditions": _knowledge_preconditions(ops),
        "operation_findings": findings,
        "unresolved": bool(findings),
        "reviews": [drafts_store.serialize_review(review) for review in reviews],
        "applications": [
            drafts_store.serialize_application(application)
            for application in applications
        ],
    }


@tool(role="writer", real_role=True)
def append_draft_correction(
    draft_id: str,
    tool_name: str,
    payload: dict[str, JsonValue],
    expected_revision: int | None = None,
) -> DraftCorrectionReceipt:
    """Append one supported substrate mutation to an open or submitted draft."""
    from .. import drafts_store

    principal = _identified_principal()
    wrapper = next((item for item in TOOLS if item.__name__ == tool_name), None)
    if wrapper is None or not tool_name.startswith(_MUTATION_PREFIXES):
        raise ValueError(f"unsupported correction tool '{tool_name}'")
    signature = _ORIG_SIGNATURES[tool_name]
    signature.bind(**payload)
    conn = _drafts_db()
    with store.transaction(conn):
        row = _require_mutable_draft(draft_id)
        drafts_store._check_revision(row, expected_revision)
        seq = drafts_store.add_op(
            conn,
            draft_id=draft_id,
            kind=tool_name,
            payload=payload,
            created_by=principal.id,
        )
        revision = drafts_store.current_revision(conn, draft_id)
        operation = next(
            op for op in drafts_store.list_ops(conn, draft_id) if op["seq"] == seq
        )
    return {
        "draft_id": draft_id,
        "operation_ref": operation["id"],
        "seq": seq,
        "revision": revision,
    }


_REVIEW_OUTCOMES = ("accepted", "refined", "rejected", "needs_context")


@tool(role="writer", real_role=True)
def record_draft_review(
    draft_id: str,
    outcome: Literal["accepted", "refined", "rejected", "needs_context"],
    rationale: str,
    draft_revision: int,
    knowledge_preconditions: list[KnowledgePrecondition],
    unresolved_questions: list[str] | None = None,
) -> DraftReviewRecord:
    """Record a durable outcome against exact inspected draft and knowledge state."""
    from .. import drafts_store

    principal = _identified_principal()
    if outcome not in _REVIEW_OUTCOMES:
        raise ValueError("invalid review outcome")
    if not rationale.strip():
        raise ValueError("review rationale is required")
    conn = _drafts_db()
    with store.write_lock():
        inspected = inspect_draft_review(draft_id)
        if inspected["draft"]["status"] != "submitted":
            raise ValueError("only submitted drafts can be reviewed")
        if inspected["draft_revision"] != draft_revision:
            raise drafts_store.StaleDraftRevisionError("draft changed since inspection")
        current_knowledge = _review_knowledge_preconditions(
            drafts_store.list_ops(conn, draft_id), knowledge_preconditions
        )
        if current_knowledge != knowledge_preconditions:
            raise ValueError("affected knowledge changed since inspection")
        unresolved = list(unresolved_questions or [])
        unresolved.extend(
            finding["finding"] for finding in inspected["operation_findings"]
        )
        if outcome in ("accepted", "refined") and unresolved:
            raise ValueError("accepted reviews cannot contain unresolved findings")
        with store.transaction(conn):
            review_id = drafts_store.create_review(
                conn,
                draft_id=draft_id,
                outcome=outcome,
                rationale=rationale.strip(),
                draft_revision=draft_revision,
                preconditions=knowledge_preconditions,
                unresolved_questions=unresolved,
                reviewed_by=principal.id,
            )
            if outcome == "rejected":
                drafts_store.set_decision(
                    conn, draft_id, decision="rejected", by=principal.id
                )
    review = drafts_store.get_review(conn, review_id)
    assert review is not None  # written in the transaction above
    return drafts_store.serialize_review(review)
