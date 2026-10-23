"""Edges an ingest draft must not queue because they point the wrong way.

Applying a draft rejects an edge whose statement kinds show it is flipped, and
that rejection fails the whole draft. Dropping such edges before they are
queued keeps the rest of the draft applicable.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import link_rules

_BATCH_MEMBER = re.compile(r"@(\d+)")


@dataclass(frozen=True)
class Statement:
    kind: str
    text: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    link_type: str
    #: The list in the op payload that holds the edge, and the edge itself.
    holder: list[object] = field(compare=False, repr=False)
    raw: Mapping[str, Any] = field(compare=False, repr=False)


def _items(op: Mapping[str, Any]) -> list[object]:
    payload = op.get("payload")
    if not isinstance(payload, Mapping):
        return []
    if op.get("op") == "upsert_statement":
        return [payload]
    if op.get("op") == "upsert_statements":
        listed = payload.get("statements")
        return listed if isinstance(listed, list) else []
    return []


def _edges(value: object) -> list[tuple[list[object], Mapping[str, Any]]]:
    if not isinstance(value, list):
        return []
    return [(value, e) for e in value if isinstance(e, Mapping)]


def read(ops: list[dict[str, Any]]) -> tuple[dict[str, Statement], list[Edge]]:
    """The statements `ops` create, keyed by their `@seq:index` reference, and
    every statement edge the ops propose, with references resolved."""
    statements: dict[str, Statement] = {}
    edges: list[Edge] = []
    for seq, op in enumerate(ops, start=1):

        def resolve(ref: object, seq: int = seq) -> str:
            text = str(ref)
            member = _BATCH_MEMBER.fullmatch(text)
            return f"@{seq}:{member[1]}" if member else text

        if op.get("op") == "add_links":
            payload = op.get("payload")
            links = payload.get("links") if isinstance(payload, Mapping) else None
            edges.extend(
                Edge(
                    str(e.get("from_id")),
                    str(e.get("to_id")),
                    str(e.get("link_type")),
                    holder,
                    e,
                )
                for holder, e in _edges(links)
            )
        for index, item in enumerate(_items(op)):
            if not isinstance(item, Mapping):
                continue
            ref = f"@{seq}:{index}"
            kind, text = item.get("kind"), item.get("text")
            if isinstance(kind, str) and isinstance(text, str) and text:
                statements[ref] = Statement(kind=kind, text=text)
            edges.extend(
                Edge(ref, resolve(e.get("to_id")), str(e.get("link_type")), holder, e)
                for holder, e in _edges(item.get("links"))
            )
            edges.extend(
                Edge(resolve(e.get("from_id")), ref, str(e.get("link_type")), holder, e)
                for holder, e in _edges(item.get("incoming_links"))
            )
    return statements, edges


def existing_ids(ops: list[dict[str, Any]]) -> list[str]:
    """The existing statements the proposed edges touch."""
    _, edges = read(ops)
    ends = (end for edge in edges for end in (edge.source, edge.target))
    return sorted({end for end in ends if end.startswith("stm_")})


EdgeCheck = Callable[[str, str, str], str | None]


def _flipped(
    statements: Mapping[str, Statement],
    edges: list[Edge],
    existing: Mapping[str, Statement],
    check: EdgeCheck,
) -> list[tuple[Edge, str]]:
    known = {**existing, **statements}
    found: list[tuple[Edge, str]] = []
    for edge in edges:
        source, target = known.get(edge.source), known.get(edge.target)
        if source is None or target is None:
            continue
        error = check(edge.link_type, source.kind, target.kind)
        if error is not None:
            found.append(
                (edge, f'"{source.text}" -{edge.link_type}-> "{target.text}": {error}')
            )
    return found


def without_flipped(
    ops: list[dict[str, Any]],
    existing: Mapping[str, Statement],
    check: EdgeCheck = link_rules.flip_error,
) -> tuple[list[dict[str, Any]], list[str]]:
    """`ops` minus the edges applying the draft would reject as flipped (or
    that `check` otherwise rejects), and a line per dropped edge. Ops
    themselves stay, so references keep their positions."""
    kept = copy.deepcopy(ops)
    statements, edges = read(kept)
    dropped = _flipped(statements, edges, existing, check)
    for edge, _ in dropped:
        edge.holder[:] = [e for e in edge.holder if e is not edge.raw]
    return kept, [message for _, message in dropped]
