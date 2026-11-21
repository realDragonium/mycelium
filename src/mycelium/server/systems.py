"""A statement's system: the entity of the app or platform its behaviour or
step belongs to. A statement without one belongs to the knowledge base's own
product.

Writes and filters name a system by entity id or exact name. A write's
omitted `system` is pydantic's `MISSING`, which keeps the current one, so
both transports tell it apart from `None`, which clears it.
Reads inside an audience scope neither show nor filter by it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict

from .. import store
from .runtime import _db


class SystemRef(TypedDict):
    entity_id: str
    name: str


def _find(value: str) -> str | None:
    if store.get_entity_by_id(_db(), value) is not None:
        return value
    row = store.get_name_by_text(_db(), value)
    return None if row is None else str(row["entity_id"])


def resolve(value: str | None) -> str | None:
    """The entity id a write's `system` names, or None for no system.

    Raises ValueError naming a value no entity id or name matches."""
    if value is None:
        return None
    entity_id = _find(value)
    if entity_id is None:
        raise ValueError(
            f"system {value!r} is not an entity id or name; "
            "create the entity with upsert_entity first"
        )
    return entity_id


def resolve_filter(value: str) -> str | None:
    """A read filter's system as an entity id, or `store.MAIN_SYSTEM` for
    statements without one; None when it names nothing.

    Raises ValueError inside an audience scope, whose reads do not see
    systems."""
    from .. import audience_scope  # local import: the scope imports the store

    if audience_scope.active() is not None:
        raise ValueError("system is not available to audience-scoped reads")
    if value == store.MAIN_SYSTEM:
        return store.MAIN_SYSTEM
    return _find(value)


def ref(entity_id: str) -> SystemRef:
    return refs([entity_id])[entity_id]


def refs(entity_ids: Iterable[str | None]) -> dict[str, SystemRef]:
    """Each system entity as reads show it, by entity id."""
    unique = list(dict.fromkeys(e for e in entity_ids if e is not None))
    names = store.entity_names(_db(), unique)
    return {
        entity_id: {"entity_id": entity_id, "name": names.get(entity_id, entity_id)}
        for entity_id in unique
    }
