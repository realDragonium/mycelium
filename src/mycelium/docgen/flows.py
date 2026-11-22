"""Draws a flow: the steps that follow from one statement, read from its links.

A writer names a start statement; the drawing comes from stored links alone, so
a document cannot show a step or a condition that is not stored. No rule here
reads statement text.

The walker reads through a `FlowReader`, never the database, so the caller
decides what is visible: a reader scoped to an audience answers `None` for a
statement that audience may not see, and the walker then leaves out every link
that ends on it or names it in a condition.
"""

from __future__ import annotations

from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, Protocol

from pydantic import BaseModel, ConfigDict

from .. import when_expression

MAX_STEPS = 12
MAX_SIDE_OUTCOMES = 4
MAX_VISITED = 60
#: The most statements a step names that a limit left out of the drawing.
MAX_CUT = 3

WhenTree = dict[str, Any]

Role = Literal[
    "next",
    "part-of",
    "separate-process",
    "on-success",
    "on-failure",
    "otherwise",
    "result",
]

_ROLES: dict[str, Role] = {
    "proceeds": "next",
    "next": "next",
    "contains": "part-of",
    "triggers": "separate-process",
    "on-success": "on-success",
    "on-failure": "on-failure",
    "fallback-to": "otherwise",
    "establishes": "result",
}
STEP_LINK_TYPES = frozenset(_ROLES)

_PART_OF_KINDS = frozenset({("event", "event"), ("procedure", "action")})

_ARROW_LABELS: dict[Role, str] = {
    "next": "then",
    "part-of": "includes",
    "separate-process": "starts a separate process",
    "on-success": "on success",
    "on-failure": "on failure",
    "otherwise": "otherwise",
    "result": "result",
}
_SIDE_LABELS: dict[Role, str] = {
    **_ARROW_LABELS,
    "next": "outcome",
    "part-of": "outcome",
    "separate-process": "outcome",
}


class FlowStatement(NamedTuple):
    kind: str
    text: str


class FlowLink(NamedTuple):
    target: str
    link_type: str
    when: WhenTree | None


class FlowReader(Protocol):
    def statement(self, statement_id: str) -> FlowStatement | None:
        """The statement, or None when it is missing or may not be seen."""

    def links(self, statement_id: str) -> Sequence[FlowLink]:
        """The statement's outgoing links, in stored order."""


class DrawnLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_type: str
    role: Role
    when: WhenTree | None = None


class Arrow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: int
    joins: bool
    links: list[DrawnLink]


class SideOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement_id: str
    text: str
    kind: str
    links: list[DrawnLink]


class CutStatement(BaseModel):
    """A statement a step leads to that a limit left out of the drawing."""

    model_config = ConfigDict(extra="forbid")

    statement_id: str
    text: str


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    statement_id: str
    text: str
    kind: str
    reached_from: int | None = None
    reached_by: Role | None = None
    arrows: list[Arrow] = []
    outcomes: list[SideOutcome] = []
    more_outcomes: int = 0
    continues: bool = False
    #: What a limit left out, up to `MAX_CUT`, then how many more. Empty in a
    #: drawing stored before they were recorded, even where it `continues`.
    cut: list[CutStatement] = []
    more_cut: int = 0


class StepLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    link_type: str
    when_hash: str


class Drawing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    steps: list[Step]
    conditions: dict[str, str]
    truncated: bool
    statement_ids: list[str]
    link_set: list[StepLink]


class FlowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement_id: str
    text: str
    kind: str
    size: int


class _Reads:
    def __init__(self, reader: FlowReader) -> None:
        self._reader = reader
        self._statements: dict[str, FlowStatement | None] = {}
        self._links: dict[str, list[FlowLink]] = {}

    def statement(self, statement_id: str) -> FlowStatement | None:
        if statement_id not in self._statements:
            self._statements[statement_id] = self._reader.statement(statement_id)
        return self._statements[statement_id]

    def step_links(self, statement_id: str) -> list[FlowLink]:
        """The links a drawing may use: a step type whose kinds fit, with the
        target and every condition statement readable."""
        if statement_id not in self._links:
            source = self.statement(statement_id)
            self._links[statement_id] = (
                []
                if source is None
                else [
                    link
                    for link in self._reader.links(statement_id)
                    if self._drawable(source, link)
                ]
            )
        return self._links[statement_id]

    def _drawable(self, source: FlowStatement, link: FlowLink) -> bool:
        target = self.statement(link.target)
        if target is None or link.link_type not in STEP_LINK_TYPES:
            return False
        if link.link_type == "establishes" and target.kind != "state":
            return False
        if (
            link.link_type == "contains"
            and (source.kind, target.kind) not in _PART_OF_KINDS
        ):
            return False
        if link.when is not None:
            # Stored trees exist that today's validation rejects, such as an
            # `and` with no children. Such a link cannot be drawn or hashed.
            try:
                when_expression.validate(link.when)
            except ValueError:
                return False
        return all(
            self.statement(leaf) is not None
            for leaf in when_expression.leaves(link.when)
        )


def _by_target(links: Sequence[FlowLink]) -> dict[str, list[DrawnLink]]:
    groups: dict[str, list[DrawnLink]] = {}
    for link in links:
        groups.setdefault(link.target, []).append(
            DrawnLink(
                link_type=link.link_type, role=_ROLES[link.link_type], when=link.when
            )
        )
    return groups


def _is_result(links: Sequence[DrawnLink]) -> bool:
    return all(link.role == "result" for link in links)


class _Walk:
    def __init__(self, reads: _Reads, start: str, stop: Collection[str]) -> None:
        self.reads = reads
        self.stop = frozenset(stop)
        self.steps: list[Step] = []
        self.numbers: dict[str, int] = {}
        self.visited = {start}
        self._add_step(start, None, None)

    def run(self) -> None:
        # The list grows while it is read, which makes it the breadth-first queue.
        for step in self.steps:
            if step.statement_id not in self.stop:
                self._expand(step)

    def _add_step(
        self, statement_id: str, reached_from: int | None, reached_by: Role | None
    ) -> int:
        statement = self.reads.statement(statement_id)
        assert statement is not None
        number = len(self.steps) + 1
        self.numbers[statement_id] = number
        self.steps.append(
            Step(
                number=number,
                statement_id=statement_id,
                text=statement.text,
                kind=statement.kind,
                reached_from=reached_from,
                reached_by=reached_by,
            )
        )
        return number

    def _leads_on(self, statement_id: str) -> bool:
        return statement_id not in self.stop and bool(
            self.reads.step_links(statement_id)
        )

    def _expand(self, step: Step) -> None:
        groups = _by_target(self.reads.step_links(step.statement_id))
        onward = {
            target
            for target, links in groups.items()
            if not _is_result(links)
            and (target in self.numbers or self._leads_on(target))
        }
        for target, links in groups.items():
            if target in self.numbers:
                step.arrows.append(
                    Arrow(to=self.numbers[target], joins=True, links=links)
                )
            elif target not in self.visited and len(self.visited) >= MAX_VISITED:
                self._cut(step, target)
            else:
                self.visited.add(target)
                self._place(step, target, links, bool(onward - {target}))

    def _place(
        self, step: Step, target: str, links: list[DrawnLink], continues: bool
    ) -> None:
        at_side = _is_result(links) or (
            not self._leads_on(target)
            and (continues or all(link.role == "otherwise" for link in links))
        )
        if at_side:
            self._add_outcome(step, target, links)
        elif len(self.steps) >= MAX_STEPS:
            self._cut(step, target)
        else:
            number = self._add_step(target, step.number, links[0].role)
            step.arrows.append(Arrow(to=number, joins=False, links=links))

    def _cut(self, step: Step, target: str) -> None:
        step.continues = True
        if len(step.cut) >= MAX_CUT:
            step.more_cut += 1
            return
        statement = self.reads.statement(target)
        assert statement is not None
        step.cut.append(CutStatement(statement_id=target, text=statement.text))

    def _add_outcome(self, step: Step, target: str, links: list[DrawnLink]) -> None:
        if len(step.outcomes) >= MAX_SIDE_OUTCOMES:
            step.more_outcomes += 1
            return
        statement = self.reads.statement(target)
        assert statement is not None
        step.outcomes.append(
            SideOutcome(
                statement_id=target,
                text=statement.text,
                kind=statement.kind,
                links=links,
            )
        )


def _drawn_links(steps: Sequence[Step]) -> Iterable[DrawnLink]:
    for step in steps:
        for arrow in step.arrows:
            yield from arrow.links
        for outcome in step.outcomes:
            yield from outcome.links


def _drawn_statements(steps: Sequence[Step]) -> list[str]:
    """Steps and side outcomes, without condition statements."""
    ids = [step.statement_id for step in steps]
    ids += [outcome.statement_id for step in steps for outcome in step.outcomes]
    return list(dict.fromkeys(ids))


def _cut_statements(steps: Sequence[Step]) -> list[str]:
    """Statements a limit left undrawn, whose text the drawing still shows."""
    return [item.statement_id for step in steps for item in step.cut]


def _link_set(reads: _Reads, statement_ids: Iterable[str]) -> list[StepLink]:
    found = {
        StepLink(
            source=source,
            target=link.target,
            link_type=link.link_type,
            when_hash=when_expression.hash_canonical(link.when),
        )
        for source in statement_ids
        for link in reads.step_links(source)
    }
    return sorted(found, key=lambda s: (s.source, s.target, s.link_type, s.when_hash))


def _draw(reads: _Reads, start: str, stop: Collection[str]) -> Drawing | None:
    if reads.statement(start) is None:
        return None
    walk = _Walk(reads, start, stop)
    walk.run()
    drawn = _drawn_statements(walk.steps)
    conditions: dict[str, str] = {}
    for link in _drawn_links(walk.steps):
        for leaf in sorted(when_expression.leaves(link.when)):
            statement = reads.statement(leaf)
            assert statement is not None
            conditions[leaf] = statement.text
    return Drawing(
        start=start,
        steps=walk.steps,
        conditions=conditions,
        truncated=any(step.continues for step in walk.steps),
        statement_ids=list(
            dict.fromkeys([*drawn, *conditions, *_cut_statements(walk.steps)])
        ),
        link_set=_link_set(reads, drawn),
    )


def draw_flow(
    reader: FlowReader, start: str, stop: Collection[str] = ()
) -> Drawing | None:
    """The flow drawn from `start`, or None when `start` cannot be read."""
    return _draw(_Reads(reader), start, stop)


def drawn_statements(drawing: Drawing) -> list[str]:
    """The drawing's steps and side outcomes: the statements whose step links
    `link_set` reads."""
    return _drawn_statements(drawing.steps)


def link_set(reader: FlowReader, drawing: Drawing) -> list[StepLink]:
    """The step links leaving the drawing's steps and side outcomes as they are
    now, to compare with `drawing.link_set`."""
    return _link_set(_Reads(reader), _drawn_statements(drawing.steps))


def flow_starts(
    reader: FlowReader, statement_ids: Iterable[str], limit: int = 15
) -> list[FlowStart]:
    """Where flows start among `statement_ids`: statements with an outgoing step
    link and none coming in from another of them, largest drawing first. Where a
    loop leaves no such statement, the one with the most outgoing step links."""
    reads = _Reads(reader)
    members = list(dict.fromkeys(statement_ids))
    outgoing = {member: reads.step_links(member) for member in members}
    reached = {
        link.target
        for member, links in outgoing.items()
        for link in links
        if link.target != member and link.target in outgoing
    }
    linked = [member for member in members if outgoing[member]]
    starts = [member for member in linked if member not in reached]
    if not starts and linked:
        starts = [max(linked, key=lambda member: len(outgoing[member]))]
    found: list[FlowStart] = []
    for start in starts:
        drawing = _draw(reads, start, ())
        assert drawing is not None
        first = drawing.steps[0]
        found.append(
            FlowStart(
                statement_id=start,
                text=first.text,
                kind=first.kind,
                size=len(_drawn_statements(drawing.steps)),
            )
        )
    found.sort(key=lambda start: -start.size)
    return found[:limit]


def condition_text(when: WhenTree, texts: Mapping[str, str]) -> str:
    """A condition in words, with `and`, `or`, `not` and brackets as stored."""
    if when_expression.is_leaf(when):
        statement_id: str = when["statement_id"]
        return f'"{texts.get(statement_id, statement_id)}"'
    parts = [
        f"({condition_text(child, texts)})"
        if when_expression.is_internal(child) and child["op"] != "not"
        else condition_text(child, texts)
        for child in when["of"]
    ]
    if when["op"] == "not":
        return f"not {parts[0]}"
    return f" {when['op']} ".join(parts)


@dataclass(frozen=True)
class Condition:
    """A stored condition as a reader sees it: a lead such as "when" or "none
    of:", then either one statement's text or a list of conditions."""

    lead: str
    text: str = ""
    items: tuple[Condition, ...] = ()


_GROUP_LEADS = {"and": "all of:", "or": "any of:"}
_NEGATED_GROUP_LEADS = {"and": "not all of:", "or": "none of:"}


def _joined(*words: str) -> str:
    return " ".join(word for word in words if word)


def _listed(
    children: Sequence[WhenTree], texts: Mapping[str, str]
) -> tuple[Condition, ...]:
    return tuple(_nested(child, texts) for child in children)


def _nested(when: WhenTree, texts: Mapping[str, str]) -> Condition:
    """A condition as an entry of a list: no "when" of its own."""
    if when_expression.is_leaf(when):
        statement_id: str = when["statement_id"]
        return Condition("", texts.get(statement_id, statement_id))
    op: str = when["op"]
    if op != "not":
        return Condition(_GROUP_LEADS[op], items=_listed(when["of"], texts))
    (child,) = when["of"]
    if when_expression.is_internal(child) and child["op"] != "not":
        return Condition(
            _NEGATED_GROUP_LEADS[child["op"]], items=_listed(child["of"], texts)
        )
    inner = _nested(child, texts)
    return Condition(_joined("not", inner.lead), inner.text, inner.items)


def condition_reading(when: WhenTree, texts: Mapping[str, str]) -> Condition:
    """A condition as it reads, exactly as stored: a statement is "when" and
    its text, a negated statement "unless"; `and` is "when all of:", `or`
    "when any of:", a negated `and` "when not all of:" and a negated `or`
    "when none of:", each with its list. Inside a list the same words stand
    without "when", and a negated statement is "not"."""
    if when_expression.is_internal(when) and when["op"] == "not":
        (child,) = when["of"]
        if when_expression.is_leaf(child) or child["op"] == "not":
            inner = _nested(child, texts)
            return Condition(_joined("unless", inner.lead), inner.text, inner.items)
    found = _nested(when, texts)
    return Condition(_joined("when", found.lead), found.text, found.items)


@dataclass(frozen=True)
class Meaning:
    """What one link says beside its line: its kind, unless the place it is
    drawn says it already, and its condition."""

    label: str
    condition: Condition | None = None


Said = tuple[Meaning, ...]


def meanings(
    links: Sequence[DrawnLink],
    texts: Mapping[str, str],
    *,
    side: bool = False,
    own: Role | None = None,
) -> Said:
    """`links_text` as parts: each condition once, with the kinds of the
    links under it, and each kind once, before the first of its conditions. A
    single link of the role `own` leaves its label out. Empty where nothing
    needs saying."""
    if not side and len(links) == 1 and links[0].role == "next" and not links[0].when:
        return ()
    labels = _SIDE_LABELS if side else _ARROW_LABELS
    # Links under one condition say it once, their kinds joined by "or".
    kinds: dict[Condition | None, list[str]] = {}
    for link in links:
        label = "" if len(links) == 1 and link.role == own else labels[link.role]
        said = kinds.setdefault(
            None if not link.when else condition_reading(link.when, texts), []
        )
        if label not in said:
            said.append(label)
    # One kind under several conditions says the kind once, before the first.
    by_kind: dict[tuple[str, bool], list[Condition | None]] = {}
    for condition, said in kinds.items():
        by_kind.setdefault((" or ".join(said), condition is None), []).append(condition)
    found = tuple(
        Meaning("" if at else label, condition)
        for (label, _plain), conditions in by_kind.items()
        for at, condition in enumerate(conditions)
    )
    return () if found == (Meaning(""),) else found


def side_label(links: Sequence[DrawnLink]) -> str:
    """What a side outcome is to its step, from its first link."""
    return _SIDE_LABELS[links[0].role]


def links_text(
    links: Sequence[DrawnLink], texts: Mapping[str, str], *, side: bool = False
) -> str:
    """Each link's meaning and condition, parallel links joined by "or". Empty
    for the plain case: one unconditional next step."""
    if not side and len(links) == 1 and links[0].role == "next" and not links[0].when:
        return ""
    labels = _SIDE_LABELS if side else _ARROW_LABELS
    return "; or ".join(
        labels[link.role]
        + (f", when {condition_text(link.when, texts)}" if link.when else "")
        for link in links
    )


def reached_text(step: Step) -> str:
    """How a step relates to the step it was reached from, where the link says
    more than "next"."""
    if step.reached_by == "part-of":
        return f"part of step {step.reached_from}"
    if step.reached_by == "separate-process":
        return f"a separate process started by step {step.reached_from}"
    return ""


CONTINUES = "continues beyond this drawing"


def more_text(count: int) -> str:
    return f"and {count} more"


def continues_text(step: Step, statement: Callable[[str], str] = str) -> str:
    """Where a limit cut the drawing at `step`: the statements left out, each
    written by `statement`, or, for a drawing stored without them, that it
    continues."""
    if not step.cut:
        return CONTINUES
    named = "; ".join(statement(item.text) for item in step.cut)
    more = f", {more_text(step.more_cut)}" if step.more_cut else ""
    return f"continues: {named} (not drawn){more}"


_ARTICLES = frozenset({"A", "An", "The"})
_PLURAL = ("", "s", "es")


def condition_case(text: str, names: Collection[str] = ()) -> str:
    """A condition's text as it reads after a word such as "when": its first
    letter lower case, unless its first word is an acronym or an identifier
    (all capitals, or another capital inside it) or the text starts with one
    of `names` written with a capital. "A", "An" and "The" are always lowered."""
    first = text.split(maxsplit=1)[0] if text.strip() else ""
    if not first or not first[0].isupper():
        return text
    lowered = text[0].lower() + text[1:]
    if first in _ARTICLES:
        return lowered
    letters = [char for char in first if char.isalpha()]
    if all(char.isupper() for char in letters) or any(
        char.isupper() for char in letters[1:]
    ):
        return text
    for name in names:
        if not name[:1].isupper():
            continue
        for ending in _PLURAL:
            whole = name + ending
            after = text[len(whole) : len(whole) + 1]
            if text.startswith(whole) and not after.isalnum():
                return text
    return lowered


def flow_lines(drawing: Drawing, *, with_ids: bool = False) -> list[str]:
    """The drawing as plain text, one step per block."""
    lines: list[str] = []
    for step in drawing.steps:
        label = f"[{step.statement_id}] " if with_ids else ""
        reached = reached_text(step)
        lines.append(
            f"{step.number}. {label}{step.text} ({step.kind})"
            + (f" - {reached}" if reached else "")
        )
        for arrow in step.arrows:
            text = links_text(arrow.links, drawing.conditions)
            lines.append(
                f"   -> {'joins ' if arrow.joins else ''}step {arrow.to}"
                + (f": {text}" if text else "")
            )
        for outcome in step.outcomes:
            label = f"[{outcome.statement_id}] " if with_ids else ""
            text = links_text(outcome.links, drawing.conditions, side=True)
            lines.append(f"   {text}: {label}{outcome.text}")
        if step.more_outcomes:
            lines.append(f"   {more_text(step.more_outcomes)}")
        if step.continues:
            lines.append(f"   -> {continues_text(step)}")
    return lines


EdgeKind = Literal["then", "part", "separate", "branch"]
"""How a drawn line between two steps reads: a plain next step, a part of the
step above, a separate process it starts, or a way that depends on a condition
or an outcome."""

_GROUP_LABELS: dict[EdgeKind, str] = {
    "then": "Then",
    "part": "Includes",
    "separate": "Starts separately",
    "branch": "Then, depending on the condition",
}
_Bucket = Literal["part", "next", "separate"]
_GROUP_ORDER: tuple[_Bucket, ...] = (
    "part",
    "next",
    "separate",
)
_OWN_ROLE: dict[_Bucket, Role] = {
    "part": "part-of",
    "next": "next",
    "separate": "separate-process",
}


def edge_kind(links: Sequence[DrawnLink]) -> EdgeKind:
    role = links[0].role
    if role == "part-of":
        return "part"
    if role == "separate-process":
        return "separate"
    if all(link.role == "next" and not link.when for link in links):
        return "then"
    return "branch"


@dataclass(frozen=True)
class Join:
    """Arrows from one step back to steps drawn elsewhere that say the same."""

    to: tuple[int, ...]
    said: Said


@dataclass(frozen=True)
class Branch:
    """One way out of a group: what it needs beyond the group's own meaning,
    and the steps it goes through."""

    said: Said
    chain: tuple[Placed, ...]


@dataclass(frozen=True)
class Group:
    """The steps one step leads to that are not simply the next one."""

    kind: EdgeKind
    label: str
    branches: tuple[Branch, ...]

    @property
    def numbers(self) -> list[int]:
        """Every step the group holds, nested ones included."""
        return sorted(
            number for branch in self.branches for number in drawn_order(branch.chain)
        )


@dataclass(frozen=True)
class Placed:
    """A step where it is drawn: its joins, the groups that hang off it, and
    the line to the step drawn under it in the same chain, if any."""

    step: Step
    joins: tuple[Join, ...]
    groups: tuple[Group, ...]
    onward: EdgeKind | None
    onward_said: Said


def _onward(tree: Sequence[Arrow]) -> Arrow | None:
    """The arrow drawn as the line to the step under this one: the only one,
    or the only plain next step beside parts and separate processes."""
    if len(tree) == 1:
        return tree[0]
    following = [arrow for arrow in tree if _bucket(arrow) == "next"]
    if len(following) == 1 and edge_kind(following[0].links) == "then":
        return following[0]
    return None


def _bucket(arrow: Arrow) -> _Bucket:
    kind = edge_kind(arrow.links)
    if kind == "part":
        return "part"
    if kind == "separate":
        return "separate"
    return "next"


def _joins(step: Step, texts: Mapping[str, str]) -> tuple[Join, ...]:
    found: dict[Said, list[int]] = {}
    for arrow in step.arrows:
        if arrow.joins:
            found.setdefault(meanings(arrow.links, texts), []).append(arrow.to)
    return tuple(Join(tuple(numbers), said) for said, numbers in found.items())


def _chain(
    first: Step, steps: Mapping[int, Step], texts: Mapping[str, str]
) -> tuple[Placed, ...]:
    chain: list[Placed] = []
    step: Step | None = first
    while step is not None:
        tree = [arrow for arrow in step.arrows if not arrow.joins]
        onward = _onward(tree)
        buckets: dict[_Bucket, list[Arrow]] = {}
        for arrow in tree:
            if arrow is not onward:
                buckets.setdefault(_bucket(arrow), []).append(arrow)
        groups: list[Group] = []
        for bucket in _GROUP_ORDER:
            arrows = buckets.get(bucket, [])
            if not arrows:
                continue
            kind: EdgeKind = (
                (
                    "branch"
                    if any(edge_kind(a.links) == "branch" for a in arrows)
                    else "then"
                )
                if bucket == "next"
                else bucket
            )
            groups.append(
                Group(
                    kind=kind,
                    label=_GROUP_LABELS[kind],
                    branches=tuple(
                        Branch(
                            meanings(arrow.links, texts, own=_OWN_ROLE[bucket]),
                            _chain(steps[arrow.to], steps, texts),
                        )
                        for arrow in arrows
                    ),
                )
            )
        chain.append(
            Placed(
                step=step,
                joins=_joins(step, texts),
                groups=tuple(groups),
                onward=None if onward is None else edge_kind(onward.links),
                onward_said=() if onward is None else meanings(onward.links, texts),
            )
        )
        step = None if onward is None else steps[onward.to]
    return tuple(chain)


def drawn_order(chain: Sequence[Placed]) -> Iterator[int]:
    """The step numbers of a laid-out chain as they are drawn down the page:
    a step, the groups hanging off it, then the step under it."""
    for placed in chain:
        yield placed.step.number
        for group in placed.groups:
            for branch in group.branches:
                yield from drawn_order(branch.chain)


def _renumbered(chain: Sequence[Placed], new: Mapping[int, int]) -> tuple[Placed, ...]:
    def step(old: Step) -> Step:
        return old.model_copy(
            update={
                "number": new[old.number],
                "reached_from": None
                if old.reached_from is None
                else new[old.reached_from],
                "arrows": [
                    arrow.model_copy(update={"to": new[arrow.to]})
                    for arrow in old.arrows
                ],
            }
        )

    return tuple(
        Placed(
            step=step(placed.step),
            joins=tuple(
                Join(tuple(sorted(new[to] for to in join.to)), join.said)
                for join in placed.joins
            ),
            groups=tuple(
                Group(
                    group.kind,
                    group.label,
                    tuple(
                        Branch(branch.said, _renumbered(branch.chain, new))
                        for branch in group.branches
                    ),
                )
                for group in placed.groups
            ),
            onward=placed.onward,
            onward_said=placed.onward_said,
        )
        for placed in chain
    )


def layout(drawing: Drawing) -> tuple[Placed, ...]:
    """The drawing as a chain of steps from its start. A step's single way on
    is the line to the step under it; where it leads to several steps, they
    hang off it in groups, each target with the chain that follows it. Every
    step is placed once, under the step it was reached from.

    Steps are numbered as they are drawn, so numbers rise down the page; the
    walk's own numbers are breadth first."""
    steps = {step.number: step for step in drawing.steps}
    chain = _chain(drawing.steps[0], steps, drawing.conditions)
    new = {old: number for number, old in enumerate(drawn_order(chain), start=1)}
    return _renumbered(chain, new)


def line_kinds(chain: Sequence[Placed]) -> set[EdgeKind]:
    """The kinds of line a laid-out drawing uses, between steps and as group
    rails."""
    found: set[EdgeKind] = set()
    for placed in chain:
        if placed.onward is not None:
            found.add(placed.onward)
        for group in placed.groups:
            found.add(group.kind)
            for branch in group.branches:
                found |= line_kinds(branch.chain)
    return found


def numbers_text(numbers: Sequence[int], number: Callable[[int], str] = str) -> str:
    """ "step 2", "steps 2 and 4", "steps 2–6" or "steps 2, 4 and 7", each
    number written by `number`."""
    if len(numbers) == 1:
        return f"step {number(numbers[0])}"
    consecutive = all(b == a + 1 for a, b in zip(numbers, numbers[1:], strict=False))
    if consecutive and len(numbers) > 2:
        return f"steps {number(numbers[0])}–{number(numbers[-1])}"
    written = [number(item) for item in numbers]
    return f"steps {', '.join(written[:-1])} and {written[-1]}"
