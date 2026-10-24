"""Curator confirmation of the AI's pending audience grants.

While "Confirm external grants" is on, an AI grant that would newly show a
statement to an external audience waits on the statement's label (see
`store.audience_labels.apply_ai_label`). Curators confirm or reject the
waiting grants per statement or per concept, or review a random sample
stratified by concept and accept the rest in one action, which records the
sample's precision on every grant it confirms.

An edit whose relabel keeps a confirmed external grant keeps it in force
and confirmed. Such statements wait in a spot-check list, with the text
the grant was confirmed for, until a curator confirms the grant for the new
text or withdraws it.
"""

from __future__ import annotations

import random
import sqlite3
from collections import Counter, defaultdict

from pydantic import BaseModel

from . import audiences, product_settings, store
from .audiences import Audience
from .store.audience_labels import Sample


class Concept(BaseModel):
    id: str
    name: str


class PendingStatement(BaseModel):
    id: str
    kind: str
    text: str
    reason: str
    model: str | None
    labelled_at: str
    concepts: list[Concept]


class PendingGroup(BaseModel):
    #: None groups the statements that name no concept.
    concept: Concept | None
    statements: list[PendingStatement]


def live_audience(audience_id: str) -> Audience:
    found = next((item for item in audiences.live() if item.id == audience_id), None)
    if found is None:
        raise ValueError(f"Audience {audience_id!r} is not live.")
    return found


def pending_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many grants wait per audience id."""
    return {
        str(row["audience"]): int(row["n"])
        for row in conn.execute(
            "SELECT p.value AS audience, COUNT(*) AS n "
            "FROM statement_audience_labels l, json_each(l.pending) p GROUP BY p.value"
        )
    }


def _pending(conn: sqlite3.Connection, audience_id: str) -> list[PendingStatement]:
    concepts: dict[str, list[Concept]] = defaultdict(list)
    for row in conn.execute(
        "SELECT m.statement_id, e.id, "
        "COALESCE((SELECT text FROM names WHERE id = e.preferred_name_id), "
        "MIN(n.text)) AS name "
        "FROM statement_mentions m JOIN names n ON n.id = m.name_id "
        "JOIN entities e ON e.id = n.entity_id "
        "WHERE m.statement_id IN (SELECT l.statement_id "
        "FROM statement_audience_labels l, json_each(l.pending) p WHERE p.value = ?) "
        "GROUP BY m.statement_id, e.id ORDER BY name",
        (audience_id,),
    ):
        concepts[str(row["statement_id"])].append(
            Concept(id=str(row["id"]), name=str(row["name"]))
        )
    return [
        PendingStatement(
            id=str(row["id"]),
            kind=str(row["kind"]),
            text=str(row["text"]),
            reason=str(row["reason"]),
            model=row["model"],
            labelled_at=str(row["labelled_at"]),
            concepts=concepts.get(str(row["id"]), []),
        )
        for row in conn.execute(
            "SELECT s.id, s.kind, s.text, l.reason, l.model, l.labelled_at "
            "FROM statement_audience_labels l JOIN statements s ON s.id = l.statement_id "
            "WHERE EXISTS (SELECT 1 FROM json_each(l.pending) WHERE value = ?) "
            "ORDER BY s.created_at DESC, s.id",
            (audience_id,),
        )
    ]


def _grouped(statements: list[PendingStatement]) -> list[PendingGroup]:
    """Each statement under the concept it names that has the most pending
    statements, so a statement appears once and groups stay large."""
    sizes = Counter(concept.id for item in statements for concept in item.concepts)
    groups: dict[str | None, PendingGroup] = {}
    for item in statements:
        concept = min(
            item.concepts,
            key=lambda concept: (-sizes[concept.id], concept.name.casefold()),
            default=None,
        )
        key = concept.id if concept is not None else None
        groups.setdefault(key, PendingGroup(concept=concept, statements=[]))
        groups[key].statements.append(item)
    return sorted(
        groups.values(),
        key=lambda group: (
            group.concept is None,
            -len(group.statements),
            group.concept.name.casefold() if group.concept is not None else "",
        ),
    )


def groups(conn: sqlite3.Connection, audience_id: str) -> list[PendingGroup]:
    return _grouped(_pending(conn, audience_id))


def _allocate(sizes: list[int], total: int) -> list[int]:
    """Split `total` across strata in proportion to their sizes, by largest
    remainder."""
    population = sum(sizes)
    if population <= total:
        return list(sizes)
    quotas = [size * total / population for size in sizes]
    counts = [int(quota) for quota in quotas]
    order = sorted(range(len(sizes)), key=lambda index: counts[index] - quotas[index])
    for index in order[: total - sum(counts)]:
        counts[index] += 1
    return counts


def sample(
    conn: sqlite3.Connection,
    audience_id: str,
    size: int,
    rng: random.Random | None = None,
) -> list[PendingGroup]:
    """A random sample of the audience's pending grants, stratified by the
    concept groups the list shows."""
    draw = rng or random.Random()
    strata = groups(conn, audience_id)
    counts = _allocate([len(group.statements) for group in strata], size)
    return [
        PendingGroup(
            concept=group.concept, statements=draw.sample(group.statements, count)
        )
        for group, count in zip(strata, counts, strict=True)
        if count
    ]


def _reject_reason(audience: Audience, row: sqlite3.Row) -> str:
    return f"A curator rejected the AI's grant to {audience.name}. The AI said: {row['reason']}"


def decide(
    audience_id: str, statement_ids: list[str], *, confirm: bool, curator: str | None
) -> int:
    """Confirm or reject the audience's pending grant on each statement.
    Returns how many were pending."""
    audience = live_audience(audience_id)
    graph = audiences.graph()
    conn = store.substrate_connection()
    decided = 0
    with store.transaction(conn):
        for statement_id in dict.fromkeys(statement_ids):
            row = store.audience_labels.get_label(conn, statement_id)
            if row is None:
                continue
            decided += store.audience_labels.decide_pending(
                conn,
                statement_id,
                audience.id,
                confirm=confirm,
                by=curator,
                reason="" if confirm else _reject_reason(audience, row),
                graph=graph,
            )
    return decided


class SamplePrecision(BaseModel):
    confirmed: int
    rejected: int

    @property
    def decided(self) -> int:
        return self.confirmed + self.rejected


def sample_precision(
    conn: sqlite3.Connection, audience_id: str, statement_ids: list[str]
) -> SamplePrecision:
    """How the sampled grants were decided, from the decisions on their labels."""
    outcomes: Counter[str] = Counter()
    for statement_id in dict.fromkeys(statement_ids):
        row = store.audience_labels.get_label(conn, statement_id)
        decision = (
            store.audience_labels.label_decisions(row).get(audience_id)
            if row is not None
            else None
        )
        if decision is not None:
            outcomes[decision.get("decision", "")] += 1
    return SamplePrecision(
        confirmed=outcomes["confirmed"], rejected=outcomes["rejected"]
    )


class Accepted(BaseModel):
    accepted: int
    sample_size: int
    precision: float
    below_threshold: bool


def accept_rest(
    audience_id: str, sample_ids: list[str], *, curator: str | None
) -> Accepted:
    """Confirm every grant still pending for the audience, recording the
    reviewed sample's size and precision on each. Rejections stand."""
    audience = live_audience(audience_id)
    limits = product_settings.get(product_settings.AudienceLabellingSettings)
    graph = audiences.graph()
    conn = store.substrate_connection()
    with store.transaction(conn):
        reviewed = sample_precision(conn, audience.id, sample_ids)
        if not reviewed.decided:
            raise ValueError(
                "Confirm or reject at least one grant in the sample before "
                "accepting the rest."
            )
        precision = round(reviewed.confirmed / reviewed.decided, 4)
        record: Sample = {"size": reviewed.decided, "precision": precision}
        remaining = [
            str(row["statement_id"])
            for row in conn.execute(
                "SELECT l.statement_id FROM statement_audience_labels l "
                "WHERE EXISTS (SELECT 1 FROM json_each(l.pending) WHERE value = ?)",
                (audience.id,),
            )
        ]
        for statement_id in remaining:
            store.audience_labels.decide_pending(
                conn,
                statement_id,
                audience.id,
                confirm=True,
                by=curator,
                sample=record,
                graph=graph,
            )
    return Accepted(
        accepted=len(remaining),
        sample_size=reviewed.decided,
        precision=precision,
        below_threshold=precision * 100 < limits.min_sample_precision_percent,
    )


class SpotCheck(BaseModel):
    id: str
    kind: str
    text: str
    old_text: str
    audiences: list[str]
    at: str


def spot_checks(conn: sqlite3.Connection) -> list[SpotCheck]:
    found: list[SpotCheck] = []
    for row in store.audience_labels.spot_checks(conn):
        checking = store.audience_labels.label_spot_check(row)
        if checking is not None:
            found.append(
                SpotCheck(
                    id=str(row["id"]),
                    kind=str(row["kind"]),
                    text=str(row["text"]),
                    old_text=checking["old_text"],
                    audiences=checking["audiences"],
                    at=checking["at"],
                )
            )
    return found


def decide_spot_check(statement_id: str, *, confirm: bool, curator: str | None) -> bool:
    """Confirm the kept grants for the new text, or withdraw them. False when
    the statement waits for no spot check."""
    conn = store.substrate_connection()
    with store.transaction(conn):
        if confirm:
            return store.audience_labels.confirm_spot_check(
                conn, statement_id, by=curator
            )
        return store.audience_labels.narrow_spot_check(
            conn,
            statement_id,
            by=curator,
            reason="A curator withdrew the external grants an edit had kept.",
            graph=audiences.graph(),
        )
