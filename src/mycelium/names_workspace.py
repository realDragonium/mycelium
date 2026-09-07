"""Preview and apply vocabulary edits without rewriting statement prose."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
)

from . import plurals, store
from .store.kernel import _load_when_tree, _record

NameText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddAlias(Model):
    kind: Literal["add"]
    entity_id: str
    text: NameText


class CorrectAlias(Model):
    kind: Literal["correct"]
    entity_id: str
    name_id: str
    text: NameText


class PreferName(Model):
    kind: Literal["prefer"]
    entity_id: str
    name_id: str


class MoveAlias(Model):
    kind: Literal["move"]
    entity_id: str
    name_id: str
    target_entity_id: str


class SplitConcept(Model):
    kind: Literal["split"]
    entity_id: str
    name_ids: list[str] = Field(min_length=1)
    preferred_name_id: str
    description: str = Field(max_length=20000)


class MergeConcepts(Model):
    kind: Literal["merge"]
    entity_id: str
    target_entity_id: str
    preferred_name_id: str
    description: str = Field(max_length=20000)


class RemoveAlias(Model):
    kind: Literal["remove"]
    entity_id: str
    name_id: str


Action = Annotated[
    AddAlias
    | CorrectAlias
    | PreferName
    | MoveAlias
    | SplitConcept
    | MergeConcepts
    | RemoveAlias,
    Field(discriminator="kind"),
]


class PreviewRequest(Model):
    action: Action


class ApplyRequest(PreviewRequest):
    expected_revision: str


class Name(Model):
    id: str
    text: str
    generated_from_name_id: str | None


class Concept(Model):
    id: str
    description: str
    preferred_name_id: str | None
    label: str
    names: list[Name]


class Catalogue(Model):
    revision: str
    entities: list[Concept]
    can_write: bool = False
    allowed_actions: list[
        Literal["add", "correct", "prefer", "move", "split", "merge", "remove"]
    ] = Field(default_factory=list)


class Example(Model):
    id: str
    kind: str
    text: str


class Relationship(Model):
    source: str
    target: str
    link_type: str
    family: Literal["concept", "statement"] = "concept"
    statement_text: str | None = None
    condition: JsonValue = None


class History(Model):
    at: str
    actor: str | None
    op: str
    target_id: str
    before_json: str | None
    after_json: str | None
    context_json: str | None


class Detail(Model):
    revision: str
    entity: Concept
    examples: list[Example]
    example_count: int
    relationships: list[Relationship]
    history: list[History]
    history_available: bool


class Preview(Model):
    revision: str
    action: Action
    summary: str
    names: list[Name]
    examples: list[Example]
    example_count: int
    relationships_before: list[Relationship]
    relationships_after: list[Relationship]
    warnings: list[str]


class Applied(Model):
    entity_id: str
    revision: str


class Conflict(ValueError):
    pass


def revision(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    # Include prose and relationships because they are part of the impact preview.
    tables = ["entities", "names", "statements", "entity_links"]
    if _has_mixed_links(conn):
        tables.extend(("entity_statement_links", "when_nodes"))
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(json.dumps(dict(row), sort_keys=True).encode())
    return digest.hexdigest()


def concept(conn: sqlite3.Connection, entity_id: str) -> Concept:
    entity = store.get_entity_by_id(conn, entity_id)
    if entity is None:
        raise ValueError("The concept no longer exists")
    names = [
        Name.model_validate(dict(row))
        for row in conn.execute(
            "SELECT id, text, generated_from_name_id FROM names WHERE entity_id = ? ORDER BY text",
            (entity_id,),
        )
    ]
    preferred = next(
        (name for name in names if name.id == entity["preferred_name_id"]), None
    )
    return Concept(
        id=entity_id,
        description=entity["description"] or "",
        preferred_name_id=preferred.id if preferred else None,
        label=preferred.text if preferred else names[0].text if names else entity_id,
        names=names,
    )


def catalogue(conn: sqlite3.Connection, query: str = "") -> Catalogue:
    with store.write_lock():
        entities = [
            concept(conn, row["id"]) for row in conn.execute("SELECT id FROM entities")
        ]
        if query:
            needle = query.casefold()
            entities = [
                item
                for item in entities
                if needle in item.description.casefold()
                or any(needle in name.text.casefold() for name in item.names)
                or needle in item.id.casefold()
            ]
        return Catalogue(
            revision=revision(conn),
            entities=sorted(entities, key=lambda item: item.label.casefold()),
        )


def _has_mixed_links(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'entity_statement_links' AND type = 'table'"
        ).fetchone()
        is not None
    )


def _relationships(
    conn: sqlite3.Connection, entity_ids: set[str]
) -> list[Relationship]:
    result = [
        Relationship(
            source=row["from_entity_id"],
            target=row["to_entity_id"],
            link_type=row["link_type"],
        )
        for row in conn.execute(
            "SELECT from_entity_id, to_entity_id, link_type FROM entity_links"
        )
        if row["from_entity_id"] in entity_ids or row["to_entity_id"] in entity_ids
    ]
    if _has_mixed_links(conn):
        for row in conn.execute(
            "SELECT l.*, s.text FROM entity_statement_links l JOIN statements s ON s.id = l.statement_id"
        ):
            if row["entity_id"] not in entity_ids:
                continue
            source, target = (
                (row["entity_id"], row["statement_id"])
                if row["direction"] == "es"
                else (row["statement_id"], row["entity_id"])
            )
            condition = TypeAdapter(JsonValue).validate_python(
                _load_when_tree(conn, row["link_id"], link_kind="entity_statement")
            )
            result.append(
                Relationship(
                    source=source,
                    target=target,
                    link_type=row["link_type"],
                    family="statement",
                    statement_text=row["text"],
                    condition=condition,
                )
            )
    return sorted(result, key=lambda item: item.model_dump_json())


def _merged_relationships(
    before: list[Relationship], source: str, target: str
) -> list[Relationship]:
    result: dict[str, Relationship] = {}
    for item in before:
        updated = item.model_copy(
            update={
                "source": target if item.source == source else item.source,
                "target": target if item.target == source else item.target,
            }
        )
        if updated.source == updated.target and (
            item.source == source or item.target == source
        ):
            continue
        result[updated.model_dump_json()] = updated
    return [result[key] for key in sorted(result)]


def _examples(conn: sqlite3.Connection, names: list[Name]) -> tuple[list[Example], int]:
    needles = [name.text.casefold() for name in names]
    rows = [
        Example(id=row["id"], text=row["text"], kind=row["kind"])
        for row in conn.execute("SELECT id, text, kind FROM statements ORDER BY rowid")
        if any(needle in row["text"].casefold() for needle in needles)
    ]
    return rows[:30], len(rows)


def detail(conn: sqlite3.Connection, entity_id: str) -> Detail:
    with store.write_lock():
        entity = concept(conn, entity_id)
        examples, count = _examples(conn, entity.names)
        history: list[History] = []
        if store.has_history(conn):
            ids = [entity_id, *(name.id for name in entity.names)]
            placeholders = ",".join("?" for _ in ids)
            history = [
                History.model_validate(dict(row))
                for row in conn.execute(
                    "SELECT at, actor, op, target_id, before_json, after_json, context_json "
                    f"FROM history.history_events WHERE target_id IN ({placeholders}) "
                    "ORDER BY event_id DESC LIMIT 50",
                    ids,
                )
            ]
        return Detail(
            revision=revision(conn),
            entity=entity,
            examples=examples,
            example_count=count,
            relationships=_relationships(conn, {entity_id}),
            history=history,
            history_available=store.has_history(conn),
        )


def _authored(entity: Concept, name_id: str) -> Name:
    name = next((name for name in entity.names if name.id == name_id), None)
    if name is None:
        raise ValueError("The name no longer belongs to this concept")
    if name.generated_from_name_id:
        raise ValueError("Edit the source name; its generated plural follows it")
    return name


def _proposed_names(conn: sqlite3.Connection, text: str) -> list[Name]:
    names = [Name(id="proposed", text=text, generated_from_name_id=None)]
    plural = plurals.regular_plural(text)
    if plural and store.get_name_by_text(conn, plural) is None:
        names.append(
            Name(id="proposed-plural", text=plural, generated_from_name_id="proposed")
        )
    return names


def _validate(conn: sqlite3.Connection, action: Action, entity: Concept) -> list[Name]:
    if isinstance(action, (AddAlias, CorrectAlias)):
        existing = store.get_name_by_text(conn, action.text)
        same = existing is not None and existing["entity_id"] == entity.id
        if (
            existing is not None
            and not (same and isinstance(action, AddAlias))
            and not (
                isinstance(action, CorrectAlias) and existing["id"] == action.name_id
            )
        ):
            raise ValueError(
                "That name already exists. Move it or merge the concepts instead."
            )
    if isinstance(action, (MoveAlias, MergeConcepts)):
        if action.target_entity_id == entity.id:
            raise ValueError("Choose a different destination concept")
        target = concept(conn, action.target_entity_id)
        if isinstance(action, MergeConcepts):
            _authored(
                entity
                if any(n.id == action.preferred_name_id for n in entity.names)
                else target,
                action.preferred_name_id,
            )
            return entity.names + target.names
    if isinstance(action, SplitConcept):
        if len(set(action.name_ids)) != len(action.name_ids):
            raise ValueError("Choose each name once")
        for name_id in action.name_ids:
            _authored(entity, name_id)
        if action.preferred_name_id not in action.name_ids:
            raise ValueError("Choose a preferred name from the names being split")
        return [
            name
            for name in entity.names
            if name.id in action.name_ids
            or name.generated_from_name_id in action.name_ids
        ]
    if isinstance(action, AddAlias):
        return _proposed_names(conn, action.text)
    _authored(entity, action.name_id)
    selected = [
        name
        for name in entity.names
        if name.id == action.name_id or name.generated_from_name_id == action.name_id
    ]
    if isinstance(action, CorrectAlias):
        selected.extend(_proposed_names(conn, action.text))
    return selected


def preview(conn: sqlite3.Connection, action: Action) -> Preview:
    with store.write_lock():
        entity = concept(conn, action.entity_id)
        names = _validate(conn, action, entity)
        ids = {entity.id}
        if isinstance(action, MergeConcepts):
            ids.add(action.target_entity_id)
        before = _relationships(conn, ids)
        after = before
        warnings = [
            "Statement text is retained. Text matches are discovery candidates, not confirmed equivalences."
        ]
        if isinstance(action, MergeConcepts):
            after = _merged_relationships(before, entity.id, action.target_entity_id)
            warnings.append(
                "The source concept is removed. Duplicate relationships and relationships that become self-links are removed."
            )
        if isinstance(action, (MoveAlias, SplitConcept)):
            warnings.append(
                "Concept relationships and the source description stay with the source concept."
            )
        summaries = {
            "add": "Recognize another name for this concept.",
            "correct": "Replace this spelling and regenerate its plural. The old spelling stops matching.",
            "prefer": "Use this name for display. All existing aliases remain recognizable.",
            "move": "Move this name and its generated plural to the selected concept.",
            "split": "Create a concept from the selected names and their generated plurals.",
            "merge": "Combine names and relationships under the destination concept and chosen description.",
            "remove": "Stop recognizing this name and its generated plural.",
        }
        if (
            isinstance(action, CorrectAlias)
            and _authored(entity, action.name_id).text.casefold()
            == action.text.casefold()
        ):
            summaries["correct"] = (
                "Update capitalization while retaining name matches and historical approvals."
            )
        examples, count = _examples(conn, names)
        return Preview(
            revision=revision(conn),
            action=action,
            summary=summaries[action.kind],
            names=names,
            examples=examples,
            example_count=count,
            relationships_before=before,
            relationships_after=after,
            warnings=warnings,
        )


def _perform(conn: sqlite3.Connection, action: Action) -> str:
    from . import (
        server,  # local import: server exposes the shared indexed write operations
    )

    if isinstance(action, AddAlias):
        server.upsert_name(action.text, action.entity_id)
    elif isinstance(action, CorrectAlias):
        server.rename_name(action.name_id, action.text)
    elif isinstance(action, PreferName):
        store.set_preferred_name(conn, action.entity_id, action.name_id)
    elif isinstance(action, MoveAlias):
        server.move_name(action.name_id, action.target_entity_id)
        return action.target_entity_id
    elif isinstance(action, RemoveAlias):
        server.delete_name(action.name_id)
    elif isinstance(action, SplitConcept):
        target = store.create_entity(conn, action.description)
        for name_id in action.name_ids:
            server.move_name(name_id, target)
        store.set_preferred_name(conn, target, action.preferred_name_id)
        return target
    elif isinstance(action, MergeConcepts):
        server.merge_entities(action.entity_id, action.target_entity_id)
        store.update_entity_description(
            conn, action.target_entity_id, action.description
        )
        store.set_preferred_name(
            conn, action.target_entity_id, action.preferred_name_id
        )
        return action.target_entity_id
    return action.entity_id


def apply(body: ApplyRequest) -> Applied:
    from . import (
        server,  # local import: server owns index persistence and recovery markers
    )

    conn = server._db()
    with store.write_lock():
        current = preview(conn, body.action)
        if body.expected_revision != current.revision:
            raise Conflict(
                "The vocabulary or previewed knowledge changed. Review a fresh preview before applying."
            )
        with server._persisted_index_write(names=True):
            before = concept(conn, body.action.entity_id).model_dump()
            destination_before = before
            if isinstance(body.action, (MoveAlias, MergeConcepts)):
                destination_before = concept(
                    conn, body.action.target_entity_id
                ).model_dump()
            elif isinstance(body.action, SplitConcept):
                destination_before = None
            entity_id = _perform(conn, body.action)
            _record(
                conn,
                "update",
                "entity",
                entity_id,
                before=destination_before,
                after=concept(conn, entity_id).model_dump(),
                context={
                    "vocabulary_action": body.action.model_dump(),
                    "source_before": before,
                },
            )
            if (
                entity_id != body.action.entity_id
                and store.get_entity_by_id(conn, body.action.entity_id) is not None
            ):
                _record(
                    conn,
                    "update",
                    "entity",
                    body.action.entity_id,
                    before=before,
                    after=concept(conn, body.action.entity_id).model_dump(),
                    context={
                        "vocabulary_action": body.action.model_dump(),
                        "destination_entity_id": entity_id,
                    },
                )
        return Applied(entity_id=entity_id, revision=revision(conn))
