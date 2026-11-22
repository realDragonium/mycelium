"""Reads only a documentation run has: a flow drawn from one statement, and
what the opening brief says about a concept beyond its statements.

`DocumentationSubstrate` adds them to the discovered read primitives, so they
are dispatched, recorded and scoped as every other read is. They read this
thread's substrate connection through unqualified table names, which is what
makes the audience boundary hold: `audience_scope.ScopedSubstrate` wraps each
call in views that shadow those tables.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from .. import docs_store, drafts_store, store
from ..agentloop import substrate_has
from ..ask.substrate import SubstrateError, SubstrateReader, ToolSpec
from . import flows, render
from .tools import PREVIEW_TOOL

#: Calls the harness makes and no model is offered: they are in no tool list.
DRAW_CALL = "draw_flow"
CONTEXT_CALL = "concept_context"
LINKS_CALL = "resolve_concept_links"
PAGES_CALL = "existing_pages"

MAX_FLOW_STARTS = 15
MAX_RELATED = 20
MAX_MORE_SPECIFIC = 20
MAX_NAMED_TOGETHER = 10

_PREVIEW_SPEC = ToolSpec(
    name=PREVIEW_TOOL,
    description=(
        "Preview the flow that would be drawn from one statement: the steps "
        "that follow from `start` over its stored links, each step's side "
        "outcomes, and the conditions on its arrows, every one with its "
        "statement id and text.\n\n"
        "Returns `{start, truncated, steps: [{step, id, kind, text, reached?, "
        "arrows?: [{to, joins?, label?}], outcomes?: [{id, kind, text, label}], "
        "more_outcomes?, continues?}], conditions: [{id, text}], missing?}`. "
        "`arrows` point at step numbers; an arrow without a label is the plain "
        "next step, and `joins` marks an arrow into a step drawn earlier. A "
        "label names its conditions by statement id; `conditions` holds their "
        "text.\n\n"
        f"A drawing holds at most {flows.MAX_STEPS} steps and "
        f"{flows.MAX_SIDE_OUTCOMES} side outcomes per step. `truncated`, and "
        "`continues` on the step where it happened, say a limit cut the "
        "drawing short: pick a later `start`, or pass `stop` to end the walk "
        "at those statements. `missing` lists a `start` or `stop` that does "
        "not exist or that this document's audience may not see.\n\n"
        "Every statement returned counts as read, so it may be cited."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "start": {
                "type": "string",
                "description": "The statement id (stm_…) the flow starts from.",
            },
            "stop": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": (
                    "Statement ids the walk does not continue past. Each is "
                    "still drawn when reached."
                ),
            },
        },
        "required": ["start"],
    },
)


class _FlowArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    stop: list[str] | None = None


class _LinkArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str]


class DrawnFlow(BaseModel):
    """What `DRAW_CALL` answers."""

    model_config = ConfigDict(extra="forbid")

    #: None when `start` cannot be read.
    drawing: flows.Drawing | None
    #: The `start` or `stop` statements that do not exist or may not be seen.
    missing: list[str]


class _ContextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str


class _PagesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guideline_set: str
    document_type: str
    entity_ids: list[str]
    limit: int


class ExistingPage(BaseModel):
    """A document this profile already holds about another concept."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    #: The concept's preferred name, which a link to the page is written with.
    name: str
    title: str
    #: How the page opens: the first paragraph of its lead, cut short.
    lead: str


EXISTING_PAGES: TypeAdapter[list[ExistingPage]] = TypeAdapter(list[ExistingPage])


class LinkedConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    link_type: str
    #: `outgoing` when the document's concept is the link's source.
    direction: Literal["outgoing", "incoming"]


class CountedConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    statements: int


class ConceptContext(BaseModel):
    """What the opening brief adds about the concept a document is about."""

    model_config = ConfigDict(extra="forbid")

    flow_starts: list[flows.FlowStart] = []
    related: list[LinkedConcept] = []
    more_specific: list[CountedConcept] = []
    #: `statements` counts those naming both concepts.
    named_together: list[CountedConcept] = []


class StoreFlowReader:
    """`flows.FlowReader` over a substrate connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def statement(self, statement_id: str) -> flows.FlowStatement | None:
        row = store.get_statement(self._conn, statement_id)
        if row is None:
            return None
        return flows.FlowStatement(kind=str(row["kind"]), text=str(row["text"]))

    def links(self, statement_id: str) -> list[flows.FlowLink]:
        return [
            flows.FlowLink(target=target, link_type=link_type, when=when)
            for target, link_type, when in store.get_links(self._conn, statement_id)
        ]


def preview(drawing: flows.Drawing) -> dict[str, Any]:
    """A drawing as a writer reads it. Statements sit under `id` keys, which
    is what makes them count as retrieved."""
    return {
        "start": drawing.start,
        "truncated": drawing.truncated,
        "steps": [_step(step) for step in drawing.steps],
        "conditions": [
            {"id": statement_id, "text": text}
            for statement_id, text in drawing.conditions.items()
        ],
    }


def _step(step: flows.Step) -> dict[str, Any]:
    row: dict[str, Any] = {
        "step": step.number,
        "id": step.statement_id,
        "kind": step.kind,
        "text": step.text,
    }
    reached = flows.reached_text(step)
    if reached:
        row["reached"] = reached
    if step.arrows:
        row["arrows"] = [_arrow(arrow) for arrow in step.arrows]
    if step.outcomes:
        row["outcomes"] = [
            {
                "id": outcome.statement_id,
                "kind": outcome.kind,
                "text": outcome.text,
                # No texts given, so a condition reads as its statement id;
                # `conditions` carries each text once.
                "label": flows.links_text(outcome.links, {}, side=True),
            }
            for outcome in step.outcomes
        ]
    if step.more_outcomes:
        row["more_outcomes"] = step.more_outcomes
    if step.continues:
        row["continues"] = True
    return row


def _arrow(arrow: flows.Arrow) -> dict[str, Any]:
    row: dict[str, Any] = {"to": arrow.to}
    if arrow.joins:
        row["joins"] = True
    label = flows.links_text(arrow.links, {})
    if label:
        row["label"] = label
    return row


def _draw(conn: sqlite3.Connection, arguments: _FlowArguments) -> DrawnFlow:
    reader = StoreFlowReader(conn)
    stop = arguments.stop or []
    return DrawnFlow(
        drawing=flows.draw_flow(reader, arguments.start, stop),
        missing=[
            statement_id
            for statement_id in dict.fromkeys([arguments.start, *stop])
            if reader.statement(statement_id) is None
        ],
    )


def _preview_flow(
    conn: sqlite3.Connection, arguments: _FlowArguments
) -> dict[str, Any]:
    drawn = _draw(conn, arguments)
    result: dict[str, Any] = (
        {"start": arguments.start} if drawn.drawing is None else preview(drawn.drawing)
    )
    if drawn.missing:
        result["missing"] = drawn.missing
    return result


def resolve_concept_links(
    conn: sqlite3.Connection, names: Sequence[str]
) -> dict[str, str]:
    """The concept each name or alias belongs to, matched ignoring case. A name
    that matches no concept, or more than one, is left out."""
    resolved: dict[str, str] = {}
    for name in dict.fromkeys(names):
        rows = conn.execute(
            "SELECT DISTINCT entity_id FROM names WHERE text = ? COLLATE NOCASE",
            (name,),
        ).fetchall()
        if len(rows) == 1:
            resolved[name] = str(rows[0]["entity_id"])
    return resolved


def _name(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute(
        "SELECT COALESCE("
        "(SELECT text FROM names WHERE id = e.preferred_name_id), "
        "(SELECT MIN(text) FROM names WHERE entity_id = e.id)) AS name "
        "FROM entities e WHERE e.id = ?",
        (entity_id,),
    ).fetchone()
    return None if row is None or row["name"] is None else str(row["name"])


def _related(conn: sqlite3.Connection, entity_id: str) -> list[LinkedConcept]:
    """The concept's direct links, without those `_more_specific` lists.
    Its own parents come first."""
    found: list[tuple[str, str, Literal["outgoing", "incoming"]]] = [
        (other, link_type, "outgoing")
        for other, link_type in store.get_entity_links_outgoing(conn, entity_id)
        if link_type != "contains"
    ]
    found += [
        (other, link_type, "incoming")
        for other, link_type in store.get_entity_links_incoming(conn, entity_id)
        if link_type != "sub-type"
    ]
    related: list[LinkedConcept] = []
    for other, link_type, direction in found:
        name = _name(conn, other)
        if other != entity_id and name is not None:
            related.append(
                LinkedConcept(
                    entity_id=other, name=name, link_type=link_type, direction=direction
                )
            )
    related.sort(
        key=lambda link: (
            link.link_type not in ("contains", "sub-type"),
            link.link_type,
            link.name.lower(),
            link.entity_id,
        )
    )
    return related[:MAX_RELATED]


def _more_specific(conn: sqlite3.Connection, entity_id: str) -> list[CountedConcept]:
    children = [
        other
        for other, link_type in store.get_entity_links_outgoing(conn, entity_id)
        if link_type == "contains"
    ] + [
        other
        for other, link_type in store.get_entity_links_incoming(conn, entity_id)
        if link_type == "sub-type"
    ]
    found: list[CountedConcept] = []
    for child in dict.fromkeys(children):
        name = _name(conn, child)
        if child != entity_id and name is not None:
            found.append(
                CountedConcept(
                    entity_id=child,
                    name=name,
                    statements=store.count_statements(conn, entity_id=child),
                )
            )
    found.sort(key=lambda c: (-c.statements, c.name.lower(), c.entity_id))
    return found[:MAX_MORE_SPECIFIC]


def _named_together(conn: sqlite3.Connection, entity_id: str) -> list[CountedConcept]:
    rows = conn.execute(
        "SELECT n2.entity_id AS entity_id, COUNT(DISTINCT m2.statement_id) AS shared "
        "FROM names n "
        "JOIN statement_mentions m ON m.name_id = n.id "
        "JOIN statement_mentions m2 ON m2.statement_id = m.statement_id "
        "JOIN names n2 ON n2.id = m2.name_id "
        "WHERE n.entity_id = ? AND n2.entity_id != ? "
        "GROUP BY n2.entity_id ORDER BY shared DESC, n2.entity_id LIMIT ?",
        (entity_id, entity_id, MAX_NAMED_TOGETHER),
    ).fetchall()
    found: list[CountedConcept] = []
    for row in rows:
        name = _name(conn, str(row["entity_id"]))
        if name is not None:
            found.append(
                CountedConcept(
                    entity_id=str(row["entity_id"]),
                    name=name,
                    statements=int(row["shared"]),
                )
            )
    return found


def concept_context(conn: sqlite3.Connection, entity_id: str) -> ConceptContext:
    statement_ids = [
        str(row["id"])
        for row in conn.execute(
            "SELECT s.id FROM statements s WHERE s.id IN ("
            "SELECT m.statement_id FROM statement_mentions m "
            "JOIN names n ON n.id = m.name_id WHERE n.entity_id = ?) "
            "ORDER BY s.rowid",
            (entity_id,),
        )
    ]
    return ConceptContext(
        flow_starts=flows.flow_starts(
            StoreFlowReader(conn), statement_ids, MAX_FLOW_STARTS
        ),
        related=_related(conn, entity_id),
        more_specific=_more_specific(conn, entity_id),
        named_together=_named_together(conn, entity_id),
    )


def existing_pages(
    conn: sqlite3.Connection,
    documents: sqlite3.Connection,
    arguments: _PagesArguments,
) -> list[ExistingPage]:
    """The documents of one profile anchored on `entity_ids`, in that order
    and at most `limit`. `documents` is the documentation store. A page is
    listed only when `conn` can read every statement it cites, so one resting
    on something the audience may no longer see is left out."""
    pages = docs_store.linked_documents(
        documents,
        arguments.guideline_set,
        arguments.document_type,
        arguments.entity_ids,
    )
    found: list[ExistingPage] = []
    for entity_id in dict.fromkeys(arguments.entity_ids):
        if len(found) >= arguments.limit:
            break
        row = (
            docs_store.get_document(documents, pages[entity_id])
            if entity_id in pages
            else None
        )
        name = _name(conn, entity_id)
        if row is None or name is None:
            continue
        cited: list[str] = json.loads(row["statement_ids"])
        if len(store.get_statement_kinds(conn, cited)) < len(set(cited)):
            continue
        found.append(
            ExistingPage(
                entity_id=entity_id,
                name=name,
                title=str(row["title"]),
                lead=render.lead_paragraph(str(row["body"])),
            )
        )
    return found


class DocumentationSubstrate:
    """A `SubstrateReader` with the documentation-only reads added."""

    _OWN = frozenset({PREVIEW_TOOL, DRAW_CALL, CONTEXT_CALL, LINKS_CALL, PAGES_CALL})

    def __init__(self, inner: SubstrateReader) -> None:
        self._inner = inner

    def tool_specs(self) -> list[ToolSpec]:
        return [*self._inner.tool_specs(), _PREVIEW_SPEC]

    def has(self, name: str) -> bool:
        return name in self._OWN or substrate_has(self._inner, name)

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._OWN:
            return self._inner.call(name, arguments)
        conn = store.substrate_connection()
        try:
            if name == CONTEXT_CALL:
                entity_id = _ContextArguments.model_validate(arguments).entity_id
                return concept_context(conn, entity_id).model_dump(mode="json")
            if name == LINKS_CALL:
                names = _LinkArguments.model_validate(arguments).names
                return resolve_concept_links(conn, names)
            if name == PAGES_CALL:
                if not drafts_store.is_configured():
                    return []
                pages = existing_pages(
                    conn,
                    drafts_store.connection(),
                    _PagesArguments.model_validate(arguments),
                )
                return [page.model_dump(mode="json") for page in pages]
            flow = _FlowArguments.model_validate(arguments)
            if name == PREVIEW_TOOL:
                return _preview_flow(conn, flow)
            return _draw(conn, flow).model_dump(mode="json")
        except (ValidationError, sqlite3.Error) as exc:
            raise SubstrateError(f"{name} failed: {exc}") from exc
