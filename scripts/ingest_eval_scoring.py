"""Pure scoring for the ingest evaluation (see `scripts/ingest_eval.py`).

Nothing here does I/O or calls a model. The runner hands over a case's
expectations, the ops of the draft ingest produced, and the judge's
statement mapping; this module turns those into metrics.

Identity model. A draft refers to statements two ways: an existing `stm_…`
id, or a statement the draft itself creates (`@seq:index` across ops, `@N`
between siblings of one `upsert_statements`). `extract_draft` resolves both
to `NodeRef`s, so links can be compared regardless of how they were written.
Expected statements are addressed by case-local keys; an expected statement
that already exists lists the ids that count as it (the knowledge base holds
some near-duplicates, so more than one can be acceptable).

Cases of the committed set run against an invented seed knowledge base and
refer to its records as `seed:<key>`; `parse_case` swaps those for the ids the
seed got when it was written (`parse_seed` turns the seed file into writes).

Statement matching is semantic and comes from the judge as
`{predicted index: expected key | None}`. Ties are broken here,
deterministically: when several predicted statements claim one expected key,
the earliest in draft order keeps it and the rest count as repeats.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from mycelium.server.specs import (
        BatchStatementSpec,
        IncomingLinkSpec,
        LinkSpec,
    )

# --------------------------------------------------------------------------- #
# Case expectations
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExpectedStatement:
    key: str
    text: str
    kinds: tuple[str, ...]
    #: ids of existing statements that count as this one; empty when new.
    existing: tuple[str, ...] = ()

    @property
    def is_new(self) -> bool:
        return not self.existing


@dataclass(frozen=True)
class Literal_:
    """One `when` leaf: a statement key, possibly negated."""

    key: str
    negated: bool = False


@dataclass(frozen=True)
class ExpectedLink:
    source: str
    target: str
    types: tuple[str, ...]
    #: AND of literals; empty when unconditional.
    when: frozenset[Literal_] = frozenset()
    #: Already in the knowledge base: re-proposing it is fine, omitting it too.
    preexisting: bool = False


@dataclass(frozen=True)
class ExpectedContradiction:
    key: str
    existing: tuple[str, ...]
    """Any of these flagged counts; several when the conflict is restated."""


@dataclass(frozen=True)
class ExpectedAlias:
    alias: str
    entity: str


@dataclass(frozen=True)
class Case:
    id: str
    categories: tuple[str, ...]
    prose: str
    statements: tuple[ExpectedStatement, ...]
    links: tuple[ExpectedLink, ...] = ()
    contradictions: tuple[ExpectedContradiction, ...] = ()
    aliases: tuple[ExpectedAlias, ...] = ()

    def statement(self, key: str) -> ExpectedStatement:
        for s in self.statements:
            if s.key == key:
                return s
        raise KeyError(key)


def _literal(raw: str) -> Literal_:
    return Literal_(raw[1:], True) if raw.startswith("!") else Literal_(raw)


def _strs(value: str | list[str]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(value)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _StatementIn(_In):
    key: str
    text: str
    kind: str | list[str]
    existing: list[str] = []


class _LinkIn(_In):
    source: str = Field(alias="from")
    to: str
    type: str | list[str]
    when: list[str] = []
    preexisting: bool = False


class _ContradictionIn(_In):
    key: str
    existing: str | list[str]


class _AliasIn(_In):
    alias: str
    entity: str


class _CaseIn(_In):
    id: str
    categories: list[str] = []
    prose: str
    statements: list[_StatementIn] = []
    links: list[_LinkIn] = []
    contradictions: list[_ContradictionIn] = []
    aliases: list[_AliasIn] = []


SEED_PREFIX = "seed:"
_NO_SEED: Mapping[str, str] = MappingProxyType({})


def parse_case(
    data: Mapping[str, object], seed_ids: Mapping[str, str] = _NO_SEED
) -> Case:
    """Build a `Case` from its TOML table, checking every key reference and
    replacing `seed:<key>` references with the ids in `seed_ids`."""
    raw = _CaseIn.model_validate(data)

    def resolve(ref: str) -> str:
        if not ref.startswith(SEED_PREFIX):
            return ref
        try:
            return seed_ids[ref.removeprefix(SEED_PREFIX)]
        except KeyError:
            raise ValueError(f"{raw.id}: unknown seed record {ref!r}") from None

    statements = tuple(
        ExpectedStatement(
            s.key, s.text, _strs(s.kind), tuple(resolve(e) for e in s.existing)
        )
        for s in raw.statements
    )
    keys = {s.key for s in statements}
    if len(keys) != len(statements):
        raise ValueError(f"{raw.id}: duplicate statement key")
    links = tuple(
        ExpectedLink(
            source=link.source,
            target=link.to,
            types=_strs(link.type),
            when=frozenset(_literal(w) for w in link.when),
            preexisting=link.preexisting,
        )
        for link in raw.links
    )
    contradictions = tuple(
        ExpectedContradiction(c.key, tuple(resolve(e) for e in _strs(c.existing)))
        for c in raw.contradictions
    )
    aliases = tuple(ExpectedAlias(a.alias, resolve(a.entity)) for a in raw.aliases)
    referenced = [k for link in links for k in (link.source, link.target)]
    referenced += [lit.key for link in links for lit in link.when]
    referenced += [c.key for c in contradictions]
    unknown = sorted(set(referenced) - keys)
    if unknown:
        raise ValueError(f"{raw.id}: unknown statement keys {unknown}")
    return Case(
        id=raw.id,
        categories=tuple(raw.categories),
        prose=raw.prose.strip(),
        statements=statements,
        links=links,
        contradictions=contradictions,
        aliases=aliases,
    )


# --------------------------------------------------------------------------- #
# Seed knowledge base
# --------------------------------------------------------------------------- #


class _SeedLinkIn(_In):
    to: str
    type: str
    when: list[str] = []


class _SeedIncomingIn(_In):
    source: str = Field(alias="from")
    type: str
    when: list[str] = []


class _SeedStatementIn(_In):
    key: str
    kind: str
    text: str
    links: list[_SeedLinkIn] = []
    incoming: list[_SeedIncomingIn] = []


class _SeedEntityIn(_In):
    key: str
    name: str
    description: str
    aliases: list[str] = []


class _SeedIn(_In):
    entities: list[_SeedEntityIn] = []
    statements: list[_SeedStatementIn] = []


@dataclass(frozen=True)
class SeedEntity:
    key: str
    name: str
    description: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Seed:
    entities: tuple[SeedEntity, ...]
    #: Statement keys, in the order of `batch`.
    statement_keys: tuple[str, ...]
    #: One `upsert_statements` batch; links between seed statements use `@N`.
    batch: list[BatchStatementSpec]


def parse_seed(data: Mapping[str, object]) -> Seed:
    raw = _SeedIn.model_validate(data)
    position = {s.key: i for i, s in enumerate(raw.statements)}
    if len(position) != len(raw.statements):
        raise ValueError("seed: duplicate statement key")
    entity_keys = {e.key for e in raw.entities}
    if len(entity_keys) != len(raw.entities) or entity_keys & position.keys():
        raise ValueError("seed: duplicate key")

    def ref(key: str) -> str:
        if key not in position:
            raise ValueError(f"seed: unknown statement key {key!r}")
        return f"@{position[key]}"

    def when(literals: list[str]) -> dict[str, object]:
        leaves: list[dict[str, object]] = []
        for lit in map(_literal, literals):
            leaf: dict[str, object] = {"statement_id": ref(lit.key)}
            leaves.append({"op": "not", "of": [leaf]} if lit.negated else leaf)
        return leaves[0] if len(leaves) == 1 else {"op": "and", "of": leaves}

    batch: list[BatchStatementSpec] = []
    for s in raw.statements:
        links: list[LinkSpec] = []
        for out in s.links:
            link: LinkSpec = {"to_id": ref(out.to), "link_type": out.type}
            if out.when:
                link["when"] = when(out.when)
            links.append(link)
        incoming: list[IncomingLinkSpec] = []
        for inc in s.incoming:
            edge: IncomingLinkSpec = {"from_id": ref(inc.source), "link_type": inc.type}
            if inc.when:
                edge["when"] = when(inc.when)
            incoming.append(edge)
        batch.append(
            {"kind": s.kind, "text": s.text, "links": links, "incoming_links": incoming}
        )
    entities = tuple(
        SeedEntity(e.key, e.name, e.description, tuple(e.aliases)) for e in raw.entities
    )
    return Seed(entities, tuple(position), batch)


# --------------------------------------------------------------------------- #
# The draft as a graph
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NodeRef:
    """A statement a draft refers to: an existing id, or one it creates."""

    existing: str | None = None
    seq: int | None = None
    index: int | None = None


@dataclass(frozen=True)
class DraftStatement:
    ref: NodeRef
    kind: str
    text: str
    phrasing_violation: bool


@dataclass(frozen=True)
class DraftLink:
    source: NodeRef
    target: NodeRef
    type: str
    #: AND of (ref, negated) literals; None when the condition is not a plain
    #: conjunction of (possibly negated) statements.
    when: frozenset[tuple[NodeRef, bool]] | None


@dataclass
class DraftGraph:
    statements: list[DraftStatement] = field(default_factory=list)
    links: list[DraftLink] = field(default_factory=list)
    #: existing statement ids whose text or links a refinement op changes.
    modified_existing: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)


_DRAFT_REF = re.compile(r"@(\d+):(\d+)")
_SIBLING_REF = re.compile(r"@(\d+)")


def _ref(value: object, seq: int) -> NodeRef | None:
    if not isinstance(value, str):
        return None
    if match := _DRAFT_REF.fullmatch(value):
        return NodeRef(seq=int(match[1]), index=int(match[2]))
    if match := _SIBLING_REF.fullmatch(value):
        return NodeRef(seq=seq, index=int(match[1]))
    if value.startswith("stm_"):
        return NodeRef(existing=value)
    return None


def _when(expr: object, seq: int) -> frozenset[tuple[NodeRef, bool]] | None:
    if not isinstance(expr, dict):
        return None
    if "statement_id" in expr:
        ref = _ref(expr["statement_id"], seq)
        return frozenset({(ref, False)}) if ref else None
    children = expr.get("of")
    if not isinstance(children, list):
        return None
    if expr.get("op") == "not" and len(children) == 1:
        inner = _when(children[0], seq)
        if inner is None or len(inner) != 1:
            return None
        ((ref, negated),) = inner
        return frozenset({(ref, not negated)})
    if expr.get("op") == "and":
        out: set[tuple[NodeRef, bool]] = set()
        for child in children:
            part = _when(child, seq)
            if part is None:
                return None
            out |= part
        return frozenset(out)
    return None


def _mappings(value: object) -> list[Mapping[str, object]]:
    """The object items of a payload list; anything malformed is skipped."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _edge(
    source: NodeRef | None, target: NodeRef | None, spec: Mapping[str, object], seq: int
) -> DraftLink | None:
    if source is None or target is None:
        return None
    return DraftLink(
        source=source,
        target=target,
        type=str(spec.get("link_type", "")),
        when=_when(spec["when"], seq) if "when" in spec else frozenset(),
    )


def _statement_edges(
    this: NodeRef, payload: Mapping[str, object], seq: int
) -> list[DraftLink]:
    outgoing = [
        _edge(this, _ref(spec.get("to_id"), seq), spec, seq)
        for spec in _mappings(payload.get("links"))
    ]
    incoming = [
        _edge(_ref(spec.get("from_id"), seq), this, spec, seq)
        for spec in _mappings(payload.get("incoming_links"))
    ]
    return [edge for edge in outgoing + incoming if edge]


def _add_statement(
    graph: DraftGraph, payload: Mapping[str, object], seq: int, index: int
) -> None:
    existing = payload.get("id")
    if isinstance(existing, str) and existing:
        ref = NodeRef(existing=existing)
        graph.modified_existing.append(existing)
    else:
        ref = NodeRef(seq=seq, index=index)
        graph.statements.append(
            DraftStatement(
                ref=ref,
                kind=str(payload.get("kind", "")),
                text=str(payload.get("text", "")),
                phrasing_violation=bool(payload.get("allow_phrasing_violations")),
            )
        )
    graph.links.extend(_statement_edges(ref, payload, seq))


def extract_draft(
    ops: Sequence[tuple[int, str, Mapping[str, object]]],
) -> DraftGraph:
    """Turn `(seq, kind, payload)` draft ops into a graph of statements/links."""
    graph = DraftGraph()
    for seq, kind, payload in ops:
        if kind == "upsert_statement":
            _add_statement(graph, payload, seq, 0)
        elif kind == "upsert_statements":
            items = payload.get("statements")
            # Positions must survive a malformed item: `@N` counts them all.
            for i, item in enumerate(items if isinstance(items, list) else []):
                if isinstance(item, Mapping):
                    _add_statement(graph, item, seq, i)
        elif kind == "add_links":
            for spec in _mappings(payload.get("links")):
                edge = _edge(
                    _ref(spec.get("from_id"), seq),
                    _ref(spec.get("to_id"), seq),
                    spec,
                    seq,
                )
                if edge:
                    graph.links.append(edge)
        elif kind in ("replace_text", "patch_statement"):
            target = payload.get("id")
            if isinstance(target, str):
                graph.modified_existing.append(target)
        elif kind == "upsert_entity":
            graph.entities.append(str(payload.get("name", "")))
        elif kind == "alias_suggestion":
            # The draft store wraps the model's proposal with its prompt.
            proposal = payload.get("proposal", payload)
            if isinstance(proposal, Mapping):
                graph.aliases.append(
                    (str(proposal.get("entity_id", "")), str(proposal.get("alias", "")))
                )
    return graph


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

StatementOutcome = Literal["match", "duplicate_of_existing", "repeat", "extra"]


@dataclass(frozen=True)
class Ledger:
    """What the run's trace said, reduced to what scoring needs."""

    flagged: tuple[str, ...] = ()
    #: (classification, matched_against ids) per ledger row.
    rows: tuple[tuple[str, tuple[str, ...]], ...] = ()


def resolve_mapping(
    graph: DraftGraph, case: Case, judged: Mapping[int, str | None]
) -> tuple[dict[NodeRef, str], list[StatementOutcome]]:
    """Apply the judge's mapping with deterministic tie-breaks.

    Returns the node→key map used for links and one outcome per predicted
    statement. A predicted statement that restates an existing expected
    statement is a duplicate even though it maps to a key: reusing would have
    meant linking the existing id instead.
    """
    keys = {s.key for s in case.statements}
    node_keys: dict[NodeRef, str] = {}
    outcomes: list[StatementOutcome] = []
    claimed: set[str] = set()
    for i, stmt in enumerate(graph.statements):
        key = judged.get(i)
        if key is None or key not in keys:
            outcomes.append("extra")
            continue
        if not case.statement(key).is_new:
            outcomes.append("duplicate_of_existing")
            node_keys[stmt.ref] = key
            continue
        if key in claimed:
            outcomes.append("repeat")
            continue
        claimed.add(key)
        node_keys[stmt.ref] = key
        outcomes.append("match")
    for s in case.statements:
        for existing in s.existing:
            node_keys.setdefault(NodeRef(existing=existing), s.key)
    return node_keys, outcomes


def _link_key(
    link: DraftLink, node_keys: Mapping[NodeRef, str]
) -> tuple[str, str] | None:
    source, target = node_keys.get(link.source), node_keys.get(link.target)
    if source is None or target is None:
        return None
    return source, target


def _when_keys(
    link: DraftLink, node_keys: Mapping[NodeRef, str]
) -> frozenset[Literal_] | None:
    if link.when is None:
        return None
    out: set[Literal_] = set()
    for ref, negated in link.when:
        key = node_keys.get(ref)
        if key is None:
            return None
        out.add(Literal_(key, negated))
    return frozenset(out)


@dataclass
class Counts:
    """Additive tallies; rates are computed after summing over cases."""

    expected_new: int = 0
    matched_new: int = 0
    predicted_new: int = 0
    true_positive: int = 0
    kind_correct: int = 0
    expected_existing: int = 0
    reused: int = 0
    referenced_existing: int = 0
    duplicates_of_existing: int = 0
    repeats: int = 0
    extras: int = 0
    expected_links: int = 0
    links_typed: int = 0
    links_any_type: int = 0
    links_reversed: int = 0
    predicted_links: int = 0
    scorable_links: int = 0
    correct_links: int = 0
    conditional_links: int = 0
    conditional_correct: int = 0
    expected_contradictions: int = 0
    contradictions_flagged: int = 0
    spurious_contradictions: int = 0
    expected_aliases: int = 0
    aliases_suggested: int = 0
    entities_proposed: int = 0
    phrasing_violations: int = 0
    modified_existing: int = 0

    def add(self, other: Counts) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def _mentions(texts: Sequence[str], statement_id: str) -> bool:
    return any(statement_id in t for t in texts)


def _score_statements(
    counts: Counts,
    graph: DraftGraph,
    case: Case,
    node_keys: Mapping[NodeRef, str],
    outcomes: Sequence[StatementOutcome],
) -> None:
    counts.expected_new = sum(1 for s in case.statements if s.is_new)
    counts.predicted_new = len(graph.statements)
    counts.phrasing_violations = sum(
        1 for s in graph.statements if s.phrasing_violation
    )
    counts.modified_existing = len(graph.modified_existing)
    for stmt, outcome in zip(graph.statements, outcomes, strict=True):
        if outcome == "match":
            counts.true_positive += 1
            if stmt.kind in case.statement(node_keys[stmt.ref]).kinds:
                counts.kind_correct += 1
        elif outcome == "duplicate_of_existing":
            counts.duplicates_of_existing += 1
        elif outcome == "repeat":
            counts.repeats += 1
        else:
            counts.extras += 1
    counts.matched_new = counts.true_positive


def _score_reuse(
    counts: Counts,
    graph: DraftGraph,
    case: Case,
    node_keys: Mapping[NodeRef, str],
    outcomes: Sequence[StatementOutcome],
    ledger: Ledger,
) -> None:
    duplicated = {
        node_keys[s.ref]
        for s, o in zip(graph.statements, outcomes, strict=True)
        if o == "duplicate_of_existing"
    }
    evidence = [
        *ledger.flagged,
        *(i for _, ids in ledger.rows for i in ids),
        *(r.existing or "" for link in graph.links for r in (link.source, link.target)),
        *graph.modified_existing,
    ]
    for s in case.statements:
        if s.is_new:
            continue
        counts.expected_existing += 1
        if s.key not in duplicated:
            counts.reused += 1
        if any(_mentions(evidence, i) for i in s.existing):
            counts.referenced_existing += 1


def _score_links(
    counts: Counts, graph: DraftGraph, case: Case, node_keys: Mapping[NodeRef, str]
) -> None:
    predicted = [(link, _link_key(link, node_keys)) for link in graph.links]
    counts.predicted_links = len(predicted)
    expected_by_pair = {(e.source, e.target): e for e in case.links}
    for link, pair in predicted:
        if pair is None or pair[0] == pair[1]:
            continue
        counts.scorable_links += 1
        exp = expected_by_pair.get(pair)
        if exp is not None and link.type in exp.types:
            counts.correct_links += 1
    wanted = [e for e in case.links if not e.preexisting]
    counts.expected_links = len(wanted)
    for exp in wanted:
        forward = [link for link, pair in predicted if pair == (exp.source, exp.target)]
        typed = [link for link in forward if link.type in exp.types]
        if forward:
            counts.links_any_type += 1
        elif any(pair == (exp.target, exp.source) for _, pair in predicted):
            counts.links_reversed += 1
        if typed:
            counts.links_typed += 1
        if exp.when:
            counts.conditional_links += 1
            if any(_when_keys(link, node_keys) == exp.when for link in typed):
                counts.conditional_correct += 1


def _score_flags(counts: Counts, graph: DraftGraph, case: Case, ledger: Ledger) -> None:
    contradiction_rows = [ids for cls, ids in ledger.rows if cls == "contradiction"]
    counts.expected_contradictions = len(case.contradictions)
    expected_ids = {e for c in case.contradictions for e in c.existing}
    for c in case.contradictions:
        if any(
            _mentions(ledger.flagged, e) or any(e in ids for ids in contradiction_rows)
            for e in c.existing
        ):
            counts.contradictions_flagged += 1
    counts.spurious_contradictions = sum(
        1 for ids in contradiction_rows if not expected_ids & set(ids)
    )
    counts.expected_aliases = len(case.aliases)
    suggested = {(e, a.casefold()) for e, a in graph.aliases}
    counts.aliases_suggested = sum(
        1 for a in case.aliases if (a.entity, a.alias.casefold()) in suggested
    )
    counts.entities_proposed = len(graph.entities)


def score_case(
    case: Case, graph: DraftGraph, judged: Mapping[int, str | None], ledger: Ledger
) -> tuple[Counts, list[StatementOutcome]]:
    node_keys, outcomes = resolve_mapping(graph, case, judged)
    counts = Counts()
    _score_statements(counts, graph, case, node_keys, outcomes)
    _score_reuse(counts, graph, case, node_keys, outcomes, ledger)
    _score_links(counts, graph, case, node_keys)
    _score_flags(counts, graph, case, ledger)
    return counts, outcomes


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def metrics(c: Counts) -> dict[str, float | None]:
    """The headline rates from summed counts (micro-averaged)."""
    return {
        "statement_recall": _rate(c.matched_new, c.expected_new),
        "statement_precision": _rate(c.true_positive, c.predicted_new),
        "kind_accuracy": _rate(c.kind_correct, c.true_positive),
        "reuse_accuracy": _rate(c.reused, c.expected_existing),
        "existing_referenced": _rate(c.referenced_existing, c.expected_existing),
        "link_recall_typed": _rate(c.links_typed, c.expected_links),
        "link_recall_any_type": _rate(c.links_any_type, c.expected_links),
        "link_reversed": _rate(c.links_reversed, c.expected_links),
        "link_precision": _rate(c.correct_links, c.scorable_links),
        "condition_accuracy": _rate(c.conditional_correct, c.conditional_links),
        "contradiction_recall": _rate(
            c.contradictions_flagged, c.expected_contradictions
        ),
        "alias_recall": _rate(c.aliases_suggested, c.expected_aliases),
        "phrasing_violation_rate": _rate(c.phrasing_violations, c.predicted_new),
    }
