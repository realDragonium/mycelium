"""Bounded connection search over stored edges, including condition participation.

Routes describe relationships, not execution or satisfied conditions. The reader
is injected so search and endpoint selection can be tested without I/O.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

Direction = Literal["both", "forward"]
StopReason = Literal[
    "max_routes", "max_expansions", "max_edge_reads", "output_limit", "condition_limit"
]
MAX_OUTPUT_CHARS = 64_000
MAX_TEXT_CHARS = 2_000
MAX_CONDITION_NODES = 128


class ConditionLeaf(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    statement_id: str


class ConditionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["and", "or", "not"]
    of: list[ConditionLeaf | ConditionGroup] = Field(min_length=1)


Condition = ConditionLeaf | ConditionGroup


def condition_ids(condition: Condition | None) -> set[str]:
    if condition is None:
        return set()
    if isinstance(condition, ConditionLeaf):
        return {condition.statement_id}
    return {sid for child in condition.of for sid in condition_ids(child)}


class Statement(BaseModel):
    id: str
    kind: str
    text: str
    text_truncated: bool = False


class Candidate(Statement):
    score: float | None = None


class Endpoint(BaseModel):
    input: str
    status: Literal["id", "matched", "ambiguous", "missing"]
    selected_id: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)


def resolve_endpoint(
    value: str,
    get_statement: Callable[[str], Statement | None],
    search: Callable[[str], list[Candidate]],
) -> Endpoint:
    value = value.strip()
    if not value:
        raise ValueError("connection endpoints must not be blank")
    if value.startswith("stm_"):
        statement = get_statement(value)
        return Endpoint(
            input=value,
            status="id" if statement else "missing",
            selected_id=statement.id if statement else None,
            candidates=[Candidate(**statement.model_dump())] if statement else [],
        )
    candidates = sorted(search(value), key=lambda c: (-(c.score or 0), c.id))[:3]
    if not candidates:
        return Endpoint(input=value, status="missing")
    # Scores include alias boosts, so this is a ranking margin, not confidence.
    ambiguous = len(candidates) > 1 and (
        (candidates[0].score or 0) - (candidates[1].score or 0) < 0.05
    )
    return Endpoint(
        input=value,
        status="ambiguous" if ambiguous else "matched",
        selected_id=None if ambiguous else candidates[0].id,
        candidates=candidates,
    )


class Edge(BaseModel):
    id: int
    from_id: str
    to_id: str
    link_type: str
    when: Condition | None = None

    def statement_ids(self) -> set[str]:
        return {self.from_id, self.to_id} | condition_ids(self.when)


class Step(BaseModel):
    edge_id: int
    from_id: str
    to_id: str
    traversal: Literal["forward", "reverse", "condition"]


class Route(BaseModel):
    statement_ids: list[str]
    steps: list[Step] = Field(default_factory=list)


class Limits(BaseModel):
    max_hops: int = Field(default=4, ge=0, le=8, strict=True)
    max_routes: int = Field(default=5, ge=1, le=20, strict=True)
    max_expansions: int = Field(default=2000, ge=1, le=10000, strict=True)


class Result(BaseModel):
    source: Endpoint
    target: Endpoint
    required: list[Endpoint] = Field(default_factory=list)
    status: Literal[
        "needs_resolution", "found", "partial", "not_found_within_limits", "incomplete"
    ]
    direction: Direction
    link_types: list[str] | None
    limits: Limits
    routes: list[Route] = Field(default_factory=list)
    statements: list[Statement] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    truncated: bool = False
    stop_reasons: list[StopReason] = Field(default_factory=list)
    expansions: int = 0
    edge_reads: int = 0

    @property
    def endpoints(self) -> list[Endpoint]:
        return [self.source, self.target, *self.required]

    @property
    def requested_ids(self) -> set[str]:
        return {e.selected_id for e in self.endpoints if e.selected_id is not None}

    @computed_field
    @property
    def connected_ids(self) -> list[str]:
        if any(e.selected_id is None for e in self.endpoints):
            return []
        reached = {sid for route in self.routes for sid in route.statement_ids}
        if self.source.selected_id is not None:
            reached.add(self.source.selected_id)
        return sorted(self.requested_ids & reached)

    @computed_field
    @property
    def unconnected_ids(self) -> list[str]:
        if any(e.selected_id is None for e in self.endpoints):
            return []
        return sorted(self.requested_ids - set(self.connected_ids))


@dataclass(frozen=True)
class EdgeBatch:
    edges: tuple[Edge, ...]
    rows_read: int
    has_more: bool = False
    condition_limited: bool = False


def steps_from(edge: Edge, statement_id: str, direction: Direction) -> Iterator[Step]:
    if statement_id == edge.from_id:
        yield Step(
            edge_id=edge.id, from_id=statement_id, to_id=edge.to_id, traversal="forward"
        )
    if direction == "forward":
        return
    if statement_id == edge.to_id and edge.from_id != edge.to_id:
        yield Step(
            edge_id=edge.id,
            from_id=statement_id,
            to_id=edge.from_id,
            traversal="reverse",
        )
    leaves = condition_ids(edge.when)
    others = edge.statement_ids() if statement_id in leaves else leaves
    for other in sorted(others - {statement_id}):
        # Endpoint-to-endpoint traversal already has its stored arrow above.
        if {statement_id, other} == {edge.from_id, edge.to_id}:
            continue
        yield Step(
            edge_id=edge.id, from_id=statement_id, to_id=other, traversal="condition"
        )


@dataclass
class Search:
    read_edges: Callable[[str, int], EdgeBatch]
    get_statement: Callable[[str], Statement | None]
    result: Result
    adjacency: dict[str, tuple[Edge, ...]] = field(default_factory=dict)
    edges: dict[int, Edge] = field(default_factory=dict)

    def stop(self, reason: StopReason) -> None:
        self.result.truncated = True
        if reason not in self.result.stop_reasons:
            self.result.stop_reasons.append(reason)

    def neighbors(self, statement_id: str) -> tuple[Edge, ...]:
        if statement_id in self.adjacency:
            return self.adjacency[statement_id]
        remaining = self.result.limits.max_expansions - self.result.edge_reads
        if remaining <= 0:
            self.stop("max_edge_reads")
            return ()
        batch = self.read_edges(statement_id, remaining)
        self.result.edge_reads += batch.rows_read
        if batch.has_more:
            self.stop("max_edge_reads")
        if batch.condition_limited:
            self.stop("condition_limit")
        self.adjacency[statement_id] = batch.edges
        self.edges.update((edge.id, edge) for edge in batch.edges)
        return batch.edges

    def add_route(self, route: Route) -> bool:
        retained = self.result.routes
        if self.result.required:
            # A longer branch subsumes its earlier prefix, without consuming
            # another route slot or leaving duplicate branch fragments.
            retained = [
                existing
                for existing in retained
                if route.steps[: len(existing.steps)] != existing.steps
            ]
        if len(retained) == self.result.limits.max_routes:
            self.stop("max_routes")
            return False
        selected = {edge.id: edge for edge in self.result.edges}
        selected.update(
            (step.edge_id, self.edges[step.edge_id]) for step in route.steps
        )
        ids = set(route.statement_ids)
        for edge in selected.values():
            ids.update(edge.statement_ids())
        statements = {s.id: s for s in self.result.statements}
        for sid in sorted(ids - statements.keys()):
            statement = self.get_statement(sid)
            if statement is None:
                raise ValueError(
                    f"statement disappeared during connection search: {sid}"
                )
            statements[sid] = statement
        candidate = self.result.model_copy(
            update={
                "routes": [*retained, route],
                "edges": sorted(selected.values(), key=lambda edge: edge.id),
                "statements": sorted(statements.values(), key=lambda s: s.id),
            }
        )
        # Leave room for the final status, counters and stop reasons.
        if len(candidate.model_dump_json()) > MAX_OUTPUT_CHARS - 2048:
            self.stop("output_limit")
            return False
        self.result.routes = candidate.routes
        self.result.edges = candidate.edges
        self.result.statements = candidate.statements
        return True

    def run(self) -> Result:
        source = self.result.source.selected_id
        target = self.result.target.selected_id
        if (
            source is None
            or target is None
            or any(e.selected_id is None for e in self.result.required)
        ):
            return self.result
        pending = deque([Route(statement_ids=[source])])
        visited = {source} if self.result.required else None
        uncovered = self.result.requested_ids - {source}
        can_expand = True
        while pending:
            route = pending.popleft()
            current = route.statement_ids[-1]
            reached = (
                current in uncovered or not uncovered
                if self.result.required
                else current == target
            )
            if reached:
                if not self.add_route(route):
                    break
                uncovered.difference_update(route.statement_ids)
                if self.result.required:
                    if not uncovered:
                        break
                else:
                    continue
            if not can_expand or len(route.steps) >= self.result.limits.max_hops:
                continue
            if not self.expand(route, pending, visited):
                # Keep already discovered terminal routes when the work runs out.
                can_expand = False
        self.result.status = (
            "partial"
            if self.result.required and self.result.routes and uncovered
            else "found"
            if self.result.routes
            else "incomplete"
            if self.result.truncated
            else "not_found_within_limits"
        )
        return self.result

    def expand(
        self,
        route: Route,
        pending: deque[Route],
        visited: set[str] | None = None,
    ) -> bool:
        used_edges = {step.edge_id for step in route.steps}
        for edge in self.neighbors(route.statement_ids[-1]):
            for step in steps_from(
                edge, route.statement_ids[-1], self.result.direction
            ):
                if self.result.expansions == self.result.limits.max_expansions:
                    self.stop("max_expansions")
                    return False
                self.result.expansions += 1
                if step.to_id in route.statement_ids or step.edge_id in used_edges:
                    continue
                if visited is not None:
                    if step.to_id in visited:
                        continue
                    visited.add(step.to_id)
                pending.append(
                    Route(
                        statement_ids=[*route.statement_ids, step.to_id],
                        steps=[*route.steps, step],
                    )
                )
        return True
