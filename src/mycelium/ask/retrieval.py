"""Bounded name resolution and one-hop evidence retrieval, without model turns."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import JsonValue

from ..ai.types import JSON_OBJECT

Read = Callable[[str, dict[str, JsonValue]], JsonValue]


def _objects(value: JsonValue) -> list[dict[str, JsonValue]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _bounded_record(
    record: dict[str, JsonValue], edge_limit: int = 20
) -> dict[str, JsonValue]:
    out = dict(record)
    for key in ("links", "incoming_links", "when_references", "names", "mentions"):
        items = out.get(key)
        if isinstance(items, list) and len(items) > edge_limit:
            total = out.get(f"{key}_truncated")
            out[f"{key}_truncated"] = (
                max(total, len(items)) if isinstance(total, int) else len(items)
            )
            out[key] = items[:edge_limit]
    return out


def _pointers(value: JsonValue) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in ("from_id", "to_id", "statement_id")
                and isinstance(item, str)
                and item.startswith("stm_")
            ):
                found.append(item)
            elif isinstance(item, (dict, list)):
                found.extend(_pointers(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_pointers(item))
    return found


def retrieve_context(
    read: Read,
    *,
    query: str,
    names: list[str],
    entity_limit: int = 3,
    statement_limit: int = 6,
    linked_limit: int = 8,
) -> dict[str, JsonValue]:
    """Resolve aliases, search within each candidate, then hydrate one linked frontier."""
    if (
        not query.strip()
        or not 1 <= len(names) <= 3
        or any(not n.strip() for n in names)
    ):
        raise ValueError("query and one to three non-empty names are required")
    for value, maximum in ((entity_limit, 3), (statement_limit, 8), (linked_limit, 12)):
        if not 1 <= value <= maximum:
            raise ValueError(f"retrieval limit must be between 1 and {maximum}")
    calls: list[JsonValue] = []

    def call(name: str, arguments: dict[str, JsonValue]) -> JsonValue:
        result = read(name, arguments)
        calls.append({"name": name, "arguments": arguments})
        return result

    resolutions: list[JsonValue] = []
    entities: dict[str, JsonValue] = {}
    statements: dict[str, JsonValue] = {}
    for name in dict.fromkeys(names):
        matches = JSON_OBJECT.validate_python(
            call("list_entities", {"prefix": name, "limit": entity_limit + 1})
        )
        candidates = _objects(matches.get("entities"))
        method = "name_prefix"
        if not candidates:
            matches = JSON_OBJECT.validate_python(
                call("search_entities", {"query": name, "k": entity_limit + 1})
            )
            candidates = _objects(matches.get("entities"))
            method = "semantic_names"
        selected: list[JsonValue] = []
        for candidate in candidates:
            eid = candidate.get("id")
            if not isinstance(eid, str) or (
                eid not in entities and len(entities) >= entity_limit
            ):
                continue
            selected.append(candidate)
            if eid in entities:
                continue
            entity = JSON_OBJECT.validate_python(call("get_entity", {"id": eid}))
            entities[eid] = _bounded_record(entity)
            aliases = _objects(entity.get("names"))
            if aliases:
                hits = call(
                    "search_statements",
                    {
                        "query": query,
                        "mentions": [aliases[0]["text"]],
                        "limit": statement_limit + 1,
                        "depth": 0,
                    },
                )
                for hit in _objects(hits):
                    sid = hit.get("id")
                    if isinstance(sid, str):
                        statements[sid] = _bounded_record(hit)
        resolutions.append(
            {
                "name": name,
                "method": method,
                "candidates": selected,
                "truncated": len(selected) < len(candidates)
                or (
                    isinstance(matches.get("total"), int)
                    and matches["total"] > len(selected)
                ),
            }
        )

    direct_ids = list(statements)[:statement_limit]
    direct = [statements[sid] for sid in direct_ids]
    frontier = list(
        dict.fromkeys(sid for sid in _pointers(direct) if sid not in direct_ids)
    )
    linked = (
        JSON_OBJECT.validate_python(
            call("get_statements", {"ids": frontier[:linked_limit]})
        )
        if frontier
        else {"statements": [], "missing": []}
    )
    evidence = {sid: statements[sid] for sid in direct_ids}
    for statement in _objects(linked.get("statements")):
        sid = statement.get("id")
        if isinstance(sid, str):
            evidence[sid] = _bounded_record(statement)
    return {
        "resolutions": resolutions,
        "entities": list(entities.values()),
        "statements": list(evidence.values()),
        "direct_ids": direct_ids,
        "missing": linked.get("missing", []),
        "limits": {
            "entities": entity_limit,
            "direct_statements": statement_limit,
            "linked_statements": linked_limit,
            "edges_per_list": 20,
            "hops": 1,
        },
        "truncated": {
            "direct_statements": len(statements) > statement_limit,
            "linked_statements": len(frontier) > linked_limit,
        },
        "reads": calls,
    }
