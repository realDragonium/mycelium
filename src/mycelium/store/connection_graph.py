"""Read only the bounded adjacency needed for a statement connection search."""

from __future__ import annotations

import sqlite3

from pydantic import TypeAdapter

from ..statement_connections import (
    MAX_CONDITION_NODES,
    MAX_TEXT_CHARS,
    ConditionGroup,
    ConditionLeaf,
    Direction,
    Edge,
    EdgeBatch,
    Statement,
)
from ..when_expression import validate
from .kernel import _load_when_tree
from .statements import get_statement

_CONDITION = TypeAdapter(ConditionLeaf | ConditionGroup)


class ConnectionGraph:
    def __init__(
        self,
        conn: sqlite3.Connection,
        direction: Direction,
        link_types: list[str] | None,
    ) -> None:
        self.conn = conn
        self.direction = direction
        self.link_types = link_types
        self.edges: dict[int, Edge | None] = {}

    def statement(self, statement_id: str) -> Statement | None:
        row = get_statement(self.conn, statement_id)
        if row is None:
            return None
        text = str(row["text"])
        return Statement(
            id=str(row["id"]),
            kind=str(row["kind"]),
            text=text[:MAX_TEXT_CHARS],
            text_truncated=len(text) > MAX_TEXT_CHARS,
        )

    def neighbors(self, statement_id: str, limit: int) -> EdgeBatch:
        if self.link_types == []:
            return EdgeBatch((), 0)
        # Limit each indexed branch before merging; an OR plus ORDER BY can
        # scan the whole link table or sort an entire convergence hub.
        branches = [
            ("sl.link_id", "statement_links sl", "sl.from_statement_id = ?"),
        ]
        if self.direction == "both":
            branches.extend(
                [
                    ("sl.link_id", "statement_links sl", "sl.to_statement_id = ?"),
                    (
                        "wn.link_id",
                        "when_nodes wn JOIN statement_links sl ON sl.link_id = wn.link_id",
                        "wn.statement_id = ?",
                    ),
                ]
            )
        filter_sql = ""
        if self.link_types is not None:
            filter_sql = (
                " AND sl.link_type IN (" + ",".join("?" for _ in self.link_types) + ")"
            )
        args: list[str | int] = [statement_id, *(self.link_types or []), limit + 1]
        ids: set[int] = set()
        for column, tables, predicate in branches:
            rows = self.conn.execute(
                f"SELECT DISTINCT {column} FROM {tables} WHERE {predicate}"
                f"{filter_sql} ORDER BY {column} LIMIT ?",
                args,
            ).fetchall()
            ids.update(int(row[0]) for row in rows)
        edges: list[Edge] = []
        condition_limited = False
        for edge_id in sorted(ids)[:limit]:
            edge = self._edge(edge_id)
            if edge is None:
                condition_limited = True
            else:
                edges.append(edge)
        return EdgeBatch(
            edges=tuple(edges),
            rows_read=min(len(ids), limit),
            has_more=len(ids) > limit,
            condition_limited=condition_limited,
        )

    def _edge(self, edge_id: int) -> Edge | None:
        if edge_id in self.edges:
            return self.edges[edge_id]
        row = self.conn.execute(
            "SELECT from_statement_id, to_statement_id, link_type, when_hash "
            "FROM statement_links WHERE link_id = ?",
            (edge_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"edge disappeared during connection search: {edge_id}")
        condition = None
        if row["when_hash"] != "NONE":
            nodes = self.conn.execute(
                "SELECT node_id FROM when_nodes WHERE link_id = ? LIMIT ?",
                (edge_id, MAX_CONDITION_NODES + 1),
            ).fetchall()
            if len(nodes) > MAX_CONDITION_NODES:
                self.edges[edge_id] = None
                return None
            tree = _load_when_tree(self.conn, edge_id)
            if tree is None:
                raise ValueError(
                    f"conditional edge {edge_id} has no readable condition"
                )
            validate(tree)
            condition = _CONDITION.validate_python(tree)
        edge = Edge(
            id=edge_id,
            from_id=str(row["from_statement_id"]),
            to_id=str(row["to_statement_id"]),
            link_type=str(row["link_type"]),
            when=condition,
        )
        self.edges[edge_id] = edge
        return edge
