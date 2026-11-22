"""Whether a generated document still says what its sources say.

Each revision keeps the text its cited statements had when it was reviewed.
A document is out of date once any of those statements has been edited,
deleted or merged away since, or relabelled so that the audience the document
was written for may no longer see it. The same holds for an image it places
that was replaced, deleted or relabelled away from that audience; media keeps
no snapshot, so a replacement is one newer than the revision. Comparing
statement text rather than timestamps means a
kind change or an edit that was reverted does not count, and it hands the
reader the old and new wording without reading history.

A flow the document places is out of date once the step links leaving the
statements it draws differ, for that audience, from those stored with the
drawing: a link added or removed, or its condition changed.

The check is one keyed lookup of every cited id across the documents asked
about, plus a history read for the few that no longer exist, so listing the
library costs one pass over its citations rather than documents × statements.
Flows add one read of the links leaving their drawn statements, across all the
documents asked about, and nothing for documents without flows; no flow is
drawn again.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence, Set
from dataclasses import asdict, dataclass
from typing import Literal

from . import audiences, media, media_store, store, when_expression
from .docgen import flows as flow_drawing
from .docgen.schema import STORED_FLOWS, StoredFlow

#: How many changes a revision brief spells out before summarising the rest.
_BRIEF_CHANGES = 10
#: Statements are short; a longer one is cut so one cannot crowd out the rest.
_BRIEF_TEXT_CHARS = 300


@dataclass(frozen=True)
class StatementChange:
    statement_id: str
    change: Literal["edited", "deleted", "merged", "no_longer_visible"]
    old_text: str
    #: Current text: the statement's own when edited or no longer visible,
    #: the one it was merged into when merged, none when deleted.
    new_text: str | None
    merged_into: str | None = None


@dataclass(frozen=True)
class MediaChange:
    media_id: str
    change: Literal["replaced", "deleted", "no_longer_visible"]
    #: What the media shows now; empty when deleted.
    alt_text: str


@dataclass(frozen=True)
class FlowChange:
    """One step link of a placed flow that differs from the stored drawing."""

    #: The flow's name in the body, and its caption.
    flow: str
    title: str
    change: Literal["step_added", "step_removed", "condition_changed"]
    link_type: str
    #: The drawn statement the link leaves and the one it leads to, as the
    #: document's audience may read them; empty for one it may not.
    source_text: str
    target_text: str


@dataclass(frozen=True)
class Freshness:
    status: Literal["unknown", "current", "out_of_date"]
    changes: tuple[StatementChange, ...] = ()
    media_changes: tuple[MediaChange, ...] = ()
    flow_changes: tuple[FlowChange, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "changes": [asdict(change) for change in self.changes],
            "media_changes": [asdict(change) for change in self.media_changes],
            "flow_changes": [asdict(change) for change in self.flow_changes],
        }


@dataclass(frozen=True)
class _Cited:
    statements: dict[str, str] | None
    #: The audience the revision was written for, as (id, internal); None
    #: for a revision whose run recorded none.
    audience: tuple[str, bool] | None
    #: Media the body places, and when the revision was written.
    media_ids: tuple[str, ...] = ()
    written_at: str = ""
    flows: tuple[StoredFlow, ...] = ()


def assess(
    cited: Mapping[str, str] | None,
    current: Mapping[str, str],
    merged_into: Mapping[str, str],
    visible: Set[str] | None = None,
) -> Freshness:
    """Compare a revision's cited text with what the substrate holds now.

    `cited` is None for a revision saved before citations were recorded.
    `visible` holds the existing cited statements the document's audience may
    still see; None skips that check.
    """
    if cited is None:
        return Freshness("unknown")
    changes: list[StatementChange] = []
    for statement_id, old_text in cited.items():
        if statement_id in current:
            if visible is not None and statement_id not in visible:
                changes.append(
                    StatementChange(
                        statement_id,
                        "no_longer_visible",
                        old_text,
                        current[statement_id],
                    )
                )
            elif current[statement_id] != old_text:
                changes.append(
                    StatementChange(
                        statement_id, "edited", old_text, current[statement_id]
                    )
                )
        elif statement_id in merged_into:
            target = merged_into[statement_id]
            changes.append(
                StatementChange(
                    statement_id, "merged", old_text, current.get(target), target
                )
            )
        else:
            changes.append(StatementChange(statement_id, "deleted", old_text, None))
    return Freshness("out_of_date" if changes else "current", tuple(changes))


def assess_media(
    cited: _Cited, items: Mapping[str, sqlite3.Row]
) -> tuple[MediaChange, ...]:
    """The media a revision places that changed since it was written."""
    changes: list[MediaChange] = []
    for media_id in cited.media_ids:
        row = items.get(media_id)
        if row is None:
            changes.append(MediaChange(media_id, "deleted", ""))
        elif cited.audience is not None and not store.audience_labels.grants(
            media_store.label(row),
            audiences.sees_of(cited.audience[0]),
            cited.audience[1],
        ):
            changes.append(MediaChange(media_id, "no_longer_visible", row["alt_text"]))
        elif str(row["content_updated_at"]) > cited.written_at:
            changes.append(MediaChange(media_id, "replaced", row["alt_text"]))
    return tuple(changes)


class _LinkReader:
    """`flows.FlowReader` over statements and links read once for every flow
    asked about, as one audience may see them."""

    def __init__(
        self,
        statements: Mapping[str, flow_drawing.FlowStatement],
        links: Mapping[str, Sequence[flow_drawing.FlowLink]],
        visible: Set[str] | None,
    ) -> None:
        self._statements = statements
        self._links = links
        self._visible = visible

    def statement(self, statement_id: str) -> flow_drawing.FlowStatement | None:
        if self._visible is not None and statement_id not in self._visible:
            return None
        return self._statements.get(statement_id)

    def links(self, statement_id: str) -> Sequence[flow_drawing.FlowLink]:
        return self._links.get(statement_id, ())


def _link_readers(
    conn: sqlite3.Connection, snapshots: Mapping[str, _Cited]
) -> dict[tuple[str, bool] | None, _LinkReader]:
    """A reader per audience over the links that leave the statements the
    snapshots' flows draw, and the statements those links name. Empty, and
    nothing is read, when no snapshot places a flow."""
    sources = sorted(
        {
            statement_id
            for cited in snapshots.values()
            if cited.statements
            for flow in cited.flows
            for statement_id in flow_drawing.drawn_statements(flow.drawing)
        }
    )
    if not sources:
        return {}
    links = {
        source: [flow_drawing.FlowLink(*link) for link in found]
        for source, found in store.get_links_from(conn, sources).items()
    }
    named = sorted(
        {
            *sources,
            *(link.target for found in links.values() for link in found),
            *(
                leaf
                for found in links.values()
                for link in found
                for leaf in when_expression.leaves(link.when)
            ),
        }
    )
    kinds = store.get_statement_kinds(conn, named)
    texts = store.get_statement_texts(conn, named)
    statements = {
        statement_id: flow_drawing.FlowStatement(kind, texts[statement_id])
        for statement_id, kind in kinds.items()
        if statement_id in texts
    }
    readers: dict[tuple[str, bool] | None, _LinkReader] = {}
    for audience in {
        cited.audience
        for cited in snapshots.values()
        if cited.flows and cited.statements
    }:
        visible = (
            None
            if audience is None
            else store.audience_labels.visible_among(
                conn, audiences.sees_of(audience[0]), audience[1], sorted(statements)
            )
        )
        readers[audience] = _LinkReader(statements, links, visible)
    return readers


def assess_flows(
    flows: Sequence[StoredFlow], reader: flow_drawing.FlowReader
) -> tuple[FlowChange, ...]:
    """The step links of each placed flow that differ, as `reader` sees them
    now, from those stored with its drawing. Nothing is drawn."""
    changes: list[FlowChange] = []
    for flow in flows:
        drawing = flow.drawing
        before = _by_link(drawing.link_set)
        after = _by_link(flow_drawing.link_set(reader, drawing))
        if before == after:
            continue
        shown = {
            **{step.statement_id: step.text for step in drawing.steps},
            **{
                outcome.statement_id: outcome.text
                for step in drawing.steps
                for outcome in step.outcomes
            },
        }

        def text(statement_id: str, shown: Mapping[str, str] = shown) -> str:
            statement = reader.statement(statement_id)
            if statement is None:
                return ""
            return shown.get(statement_id, statement.text)

        for link in sorted(before.keys() | after.keys()):
            if before.get(link) == after.get(link):
                continue
            source, target, link_type = link
            changes.append(
                FlowChange(
                    flow=flow.name,
                    title=flow.title,
                    change="step_added"
                    if link not in before
                    else "step_removed"
                    if link not in after
                    else "condition_changed",
                    link_type=link_type,
                    source_text=text(source),
                    target_text=text(target),
                )
            )
    return tuple(changes)


def _by_link(
    links: Iterable[flow_drawing.StepLink],
) -> dict[tuple[str, str, str], frozenset[str]]:
    """Each link's conditions, by source, target and type."""
    found: dict[tuple[str, str, str], set[str]] = {}
    for link in links:
        found.setdefault((link.source, link.target, link.link_type), set()).add(
            link.when_hash
        )
    return {link: frozenset(hashes) for link, hashes in found.items()}


def _with(
    freshness: Freshness,
    media_changes: tuple[MediaChange, ...],
    flow_changes: tuple[FlowChange, ...],
) -> Freshness:
    if not media_changes and not flow_changes:
        return freshness
    return Freshness("out_of_date", freshness.changes, media_changes, flow_changes)


def for_documents(
    drafts: sqlite3.Connection,
    substrate: Callable[[], sqlite3.Connection],
    document_ids: Sequence[str],
) -> dict[str, Freshness]:
    """Freshness of each document's current revision.

    The substrate is opened only when some revision recorded citations. A
    flow's statements are among them, so a revision without any has no flow
    to check.
    """
    snapshots = cited_snapshots(drafts, document_ids)
    cited_ids = sorted(
        {
            sid
            for cited in snapshots.values()
            if cited.statements
            for sid in cited.statements
        }
    )
    current: dict[str, str] = {}
    merged_into: dict[str, str] = {}
    visible: dict[tuple[str, bool], frozenset[str]] = {}
    readers: dict[tuple[str, bool] | None, _LinkReader] = {}
    if cited_ids:
        conn = substrate()
        readers = _link_readers(conn, snapshots)
        current = store.get_statement_texts(conn, cited_ids)
        missing = [sid for sid in cited_ids if sid not in current]
        merged_into = store.merge_targets(conn, missing) if missing else {}
        survivors = sorted(set(merged_into.values()) - current.keys())
        for audience in {cited.audience for cited in snapshots.values()}:
            if audience is not None:
                existing = sorted(
                    {
                        sid
                        for cited in snapshots.values()
                        if cited.audience == audience and cited.statements
                        for sid in cited.statements
                        if sid in current
                    }
                )
                audience_id, internal = audience
                visible[audience] = store.audience_labels.visible_among(
                    conn, audiences.sees_of(audience_id), internal, existing
                )
        if survivors:
            current.update(store.get_statement_texts(conn, survivors))
    placed = {item for cited in snapshots.values() for item in cited.media_ids}
    items: dict[str, sqlite3.Row] = {}
    if placed and media_store.is_configured():
        items = {
            row["id"]: row
            for row in media_store.get_many(media_store.connection(), placed)
        }
    unrecorded = _Cited(None, None)
    return {
        document_id: _with(
            assess(
                (cited := snapshots.get(document_id, unrecorded)).statements,
                current,
                merged_into,
                visible.get(cited.audience) if cited.audience is not None else None,
            ),
            assess_media(cited, items) if media_store.is_configured() else (),
            assess_flows(cited.flows, readers[cited.audience])
            if cited.audience in readers
            else (),
        )
        for document_id in document_ids
    }


def cited_snapshots(
    conn: sqlite3.Connection, document_ids: Iterable[str]
) -> dict[str, _Cited]:
    wanted = list(document_ids)
    snapshots: dict[str, _Cited] = {}
    for offset in range(0, len(wanted), 500):
        chunk = wanted[offset : offset + 500]
        placeholders = ", ".join("?" for _document_id in chunk)
        rows = conn.execute(
            "SELECT r.document_id, r.cited_statements, r.body, r.created_at, r.flows, "
            "json_extract(run.profile_snapshot, '$.audience.id') AS audience, "
            "json_extract(run.profile_snapshot, '$.audience.scope') AS scope "
            "FROM generated_documents AS d JOIN generated_document_revisions AS r "
            "ON r.document_id = d.id AND r.revision = d.current_revision "
            "LEFT JOIN documentation_runs AS run ON run.id = r.run_id "
            f"WHERE d.id IN ({placeholders})",
            tuple(chunk),
        )
        for row in rows:
            raw = row["cited_statements"]
            snapshots[str(row["document_id"])] = _Cited(
                None if raw is None else dict(json.loads(raw)),
                None
                if row["audience"] is None
                else (str(row["audience"]), row["scope"] == "internal"),
                tuple(media.referenced(str(row["body"]))),
                str(row["created_at"]),
                tuple(STORED_FLOWS.validate_json(row["flows"])) if row["flows"] else (),
            )
    return snapshots


def revision_brief(
    changes: Sequence[StatementChange],
    media_changes: Sequence[MediaChange] = (),
    flow_changes: Sequence[FlowChange] = (),
) -> str:
    """Instructions for a revision that brings a document up to date."""
    lines = [
        "Bring this document up to date with these knowledge-base changes to "
        "what it cites and shows. Keep everything else as it is. Read a statement "
        "with get_statements before citing it; never cite a deleted one, and "
        "drop or re-source what rested only on it."
    ]
    for item in media_changes:
        if item.change == "replaced":
            lines.append(
                f"- Image {item.media_id} was replaced; it now shows: "
                f"{_clip(item.alt_text)!r}. Keep it only where that still fits, "
                "and update its alt text."
            )
        elif item.change == "no_longer_visible":
            lines.append(
                f"- Image {item.media_id} is no longer visible to this audience; "
                "remove it."
            )
        else:
            lines.append(f"- Image {item.media_id} was deleted; remove it.")
    for change in changes[:_BRIEF_CHANGES]:
        old = _clip(change.old_text)
        if change.change == "edited":
            lines.append(
                f"- {change.statement_id} was edited. Was: {old!r}. "
                f"Now: {_clip(change.new_text or '')!r}."
            )
        elif change.change == "merged":
            lines.append(
                f"- {change.statement_id} ({old!r}) was merged into "
                f"{change.merged_into}"
                + (
                    f", which says: {_clip(change.new_text)!r}."
                    if change.new_text is not None
                    else "."
                )
            )
        elif change.change == "no_longer_visible":
            lines.append(
                f"- {change.statement_id} ({old!r}) is no longer visible to this "
                "audience; remove what rested only on it."
            )
        else:
            lines.append(f"- {change.statement_id} ({old!r}) was deleted.")
    if len(changes) > _BRIEF_CHANGES:
        lines.append(
            f"- …and {len(changes) - _BRIEF_CHANGES} more cited statements changed; "
            "re-read every statement the document cites."
        )
    lines.extend(_flow_lines(flow_changes))
    return "\n".join(lines)


def _flow_lines(changes: Sequence[FlowChange]) -> list[str]:
    """What changed in each placed flow, by statement text."""
    by_flow: dict[str, list[FlowChange]] = {}
    for change in changes:
        by_flow.setdefault(change.flow, []).append(change)
    lines: list[str] = []
    for name, found in by_flow.items():
        lines.append(
            f"- The steps of flow `{name}` ({found[0].title!r}) changed since "
            "it was drawn. Preview it again with preview_flow, bring the text "
            "around it in line, and submit the flow again so it is redrawn:"
        )
        for change in found[:_BRIEF_CHANGES]:
            source = _said(change.source_text)
            target = _said(change.target_text)
            if change.change == "step_added":
                lines.append(
                    f"  - step added: {source} now leads to {target} "
                    f"({change.link_type})."
                )
            elif change.change == "step_removed":
                lines.append(
                    f"  - step removed: {source} no longer leads to {target} "
                    f"({change.link_type})."
                )
            else:
                lines.append(
                    f"  - condition changed on the step from {source} to {target} "
                    f"({change.link_type})."
                )
        if len(found) > _BRIEF_CHANGES:
            lines.append(f"  - …and {len(found) - _BRIEF_CHANGES} more changes.")
    return lines


def _said(text: str) -> str:
    return repr(_clip(text)) if text else "a statement this audience cannot read"


def addition_brief(statements: Mapping[str, str]) -> str:
    """Instructions for a revision that takes in statements the document
    does not cite yet, given by id with their current text."""
    lines = [
        "Add what these statements say to this document, where a reader would "
        "look for it; they are not cited yet. Keep everything else as it is. "
        "Read a statement with get_statements before citing it."
    ]
    listed = list(statements.items())
    lines.extend(
        f"- {statement_id}: {_clip(text)!r}"
        for statement_id, text in listed[:_BRIEF_CHANGES]
    )
    if len(listed) > _BRIEF_CHANGES:
        lines.append(
            "- …and "
            + ", ".join(statement_id for statement_id, _ in listed[_BRIEF_CHANGES:])
        )
    return "\n".join(lines)


def _clip(text: str) -> str:
    if len(text) <= _BRIEF_TEXT_CHARS:
        return text
    return text[: _BRIEF_TEXT_CHARS - 1] + "…"
