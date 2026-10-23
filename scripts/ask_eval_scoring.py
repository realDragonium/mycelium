"""Scoring for the Ask evaluation harness (scripts/ask_eval.py).

Pure functions over plain data, so the scoring rules are unit-tested
without a model, a server or a data directory. The harness gathers what one
Ask run saw and said into an `Observed`, asks the judge for a `Judgement` on
it, and `score_case` turns the two into per-case metrics.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _CaseIn(_In):
    id: str
    question: str
    categories: list[str] = []
    facts: list[str] = []
    must_not: list[str] = []
    answerable: bool = True
    conflict: bool = False


class _CasesIn(_In):
    cases: list[_CaseIn]


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    categories: tuple[str, ...]
    #: Statement ids the answer must state.
    facts: tuple[str, ...]
    must_not: tuple[str, ...]
    answerable: bool
    conflict: bool


def parse_cases(
    data: Mapping[str, object], resolve: Callable[[str], str]
) -> list[Case]:
    """`resolve` turns a fact reference (a seed key, or a statement id in an
    external case directory) into a statement id."""
    cases = []
    for raw in _CasesIn.model_validate(data).cases:
        if not raw.answerable and (raw.facts or raw.conflict):
            raise ValueError(f"{raw.id}: an unanswerable case has no facts")
        if raw.answerable and not raw.facts:
            raise ValueError(f"{raw.id}: an answerable case needs facts")
        cases.append(
            Case(
                id=raw.id,
                question=raw.question,
                categories=tuple(raw.categories)
                + (() if raw.answerable else ("unanswerable",)),
                facts=tuple(resolve(f) for f in raw.facts),
                must_not=tuple(raw.must_not),
                answerable=raw.answerable,
                conflict=raw.conflict,
            )
        )
    return cases


# --------------------------------------------------------------------------- #
# What a run saw and said
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvidenceRecord:
    ref: str
    id: str
    text: str
    #: Rendered outgoing links, e.g. "contains -> s4 when s2".
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observed:
    outcome: str
    answer: str
    gaps: tuple[str, ...]
    #: Cited statement ids, in the order the answer gave them.
    provenance: tuple[str, ...]
    #: Every statement the run supplied to the model, by run-local ref.
    evidence: tuple[EvidenceRecord, ...]
    #: Text of each expected fact, by statement id.
    fact_texts: Mapping[str, str] = field(default_factory=dict)


def render_when(tree: object, label: Callable[[str], str]) -> str:
    """A `when` tree as compact infix text, statements named by `label`."""
    if not isinstance(tree, Mapping):
        return "?"
    sid = tree.get("statement_id")
    if isinstance(sid, str):
        return label(sid)
    op = tree.get("op")
    parts = tree.get("of")
    children = (
        [render_when(child, label) for child in parts]
        if isinstance(parts, list)
        else []
    )
    if op == "not" and len(children) == 1:
        return f"NOT {children[0]}"
    joined = f" {str(op).upper()} ".join(children)
    return f"({joined})" if len(children) > 1 else joined


def render_links(
    links: Sequence[Mapping[str, object]],
    label: Callable[[str], str],
) -> tuple[str, ...]:
    rendered = []
    for link in links:
        target = link.get("to_id")
        line = f"{link.get('link_type')} -> {label(target) if isinstance(target, str) else '?'}"
        if link.get("when") is not None:
            line += f" when {render_when(link['when'], label)}"
        rendered.append(line)
    return tuple(rendered)


# --------------------------------------------------------------------------- #
# Judge
# --------------------------------------------------------------------------- #

JUDGE_SYSTEM = """\
You grade one answer produced by a question-answering system over a \
knowledge base of short statements about a software product. You get the \
QUESTION, the ANSWER (with its listed gaps), the EVIDENCE statements the \
system retrieved (each with a ref like s3, its kind and its outgoing links; a \
link "contains -> s4 when s2" means the link only holds while s2 holds), the \
EXPECTED FACTS and the MUST-NOT claims.

Report:
- facts: for every expected fact, whether the answer states it. Stated means \
the answer makes that claim with the same values and conditions; wording may \
differ. A fact the answer mentions only as uncertain or as one side of a \
conflict it reports still counts as stated.
- must_not: for every must-not claim, whether the answer makes it.
- claims: split the answer (not the gaps) into its atomic factual claims about \
the product. For each, list the evidence refs that support it: the statement \
text, or a link between evidence statements, says it. Leave support empty \
when no evidence says it — including claims from general knowledge, guesses, \
consequences and conditions the evidence does not state. Skip sentences \
about the knowledge base itself ("the knowledge base does not say X", "no \
other role is documented"): they are not claims about the product.
- declines: true when the answer says the knowledge base does not answer the \
core of the question.
- flags_conflict: true when the answer reports that the knowledge base holds \
conflicting statements on the question."""


class FactVerdict(BaseModel):
    fact: str = Field(description="The expected fact's id, such as f0")
    stated: bool


class MustNotVerdict(BaseModel):
    index: int = Field(description="The must-not claim's number, such as 0")
    claimed: bool


class Claim(BaseModel):
    claim: str
    support: list[str] = Field(
        description="Evidence refs such as s3, empty when unsupported"
    )


class Judgement(BaseModel):
    facts: list[FactVerdict]
    must_not: list[MustNotVerdict]
    claims: list[Claim]
    declines: bool
    flags_conflict: bool


def judge_prompt(case: Case, seen: Observed) -> str:
    evidence = "\n".join(
        f"{e.ref}: {e.text}" + "".join(f"\n    {line}" for line in e.links)
        for e in seen.evidence
    )
    facts = "\n".join(
        f"f{i}: {seen.fact_texts.get(sid, sid)}" for i, sid in enumerate(case.facts)
    )
    must_not = "\n".join(f"{i}: {claim}" for i, claim in enumerate(case.must_not))
    gaps = "\n".join(f"- {gap}" for gap in seen.gaps)
    return (
        f"QUESTION: {case.question}\n\n"
        f"ANSWER:\n{seen.answer}\n\nGAPS:\n{gaps or '(none)'}\n\n"
        f"EVIDENCE:\n{evidence or '(none)'}\n\n"
        f"EXPECTED FACTS:\n{facts or '(none)'}\n\n"
        f"MUST-NOT CLAIMS:\n{must_not or '(none)'}"
    )


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CaseScore:
    #: Expected facts the answer states, over expected facts.
    fact_recall: float | None
    #: Expected facts cited in provenance, over expected facts.
    cited_recall: float | None
    claims: int
    unsupported_claims: int
    #: Cited statements that support at least one claim, over cited statements.
    citation_precision: float | None
    must_not_violations: int
    #: Unanswerable: declined without a must-not claim. Answerable: None.
    correct_refusal: bool | None
    #: Answerable but declined or asked for clarification.
    false_refusal: bool | None
    #: Conflict cases: the answer reports the conflict.
    conflict_flagged: bool | None
    #: The answer text shows run-local evidence refs (s1, s2, ...) to the reader.
    refs_in_answer: bool


_REF = re.compile(r"\bs\d+\b")


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_case(case: Case, seen: Observed, verdict: Judgement | None) -> CaseScore:
    """`verdict` is None for a clarification, which has no answer to judge."""
    cited = set(seen.provenance)
    refs_in_answer = bool(_REF.search(seen.answer))
    cited_recall = _rate(sum(f in cited for f in case.facts), len(case.facts))
    if verdict is None:
        return CaseScore(
            fact_recall=0.0 if case.answerable else None,
            cited_recall=cited_recall if case.answerable else None,
            claims=0,
            unsupported_claims=0,
            citation_precision=None,
            must_not_violations=0,
            correct_refusal=None if case.answerable else False,
            false_refusal=True if case.answerable else None,
            conflict_flagged=False if case.conflict else None,
            refs_in_answer=refs_in_answer,
        )
    # A judge that names a fact by its text instead of its id still counts.
    fact_id = {
        seen.fact_texts.get(sid, sid): f"f{i}" for i, sid in enumerate(case.facts)
    }
    stated = {f"f{i}" for i, _ in enumerate(case.facts)} & {
        fact_id.get(v.fact, v.fact) for v in verdict.facts if v.stated
    }
    ref_of = {e.id: e.ref for e in seen.evidence}
    used = {ref for claim in verdict.claims for ref in claim.support}
    cited_refs = {ref_of.get(sid, sid) for sid in cited}
    violations = sum(
        v.claimed for v in verdict.must_not if 0 <= v.index < len(case.must_not)
    )
    return CaseScore(
        fact_recall=_rate(len(stated), len(case.facts)) if case.answerable else None,
        cited_recall=cited_recall if case.answerable else None,
        claims=len(verdict.claims),
        unsupported_claims=sum(not claim.support for claim in verdict.claims),
        citation_precision=_rate(len(cited_refs & used), len(cited_refs)),
        must_not_violations=violations,
        correct_refusal=None
        if case.answerable
        else verdict.declines and violations == 0,
        false_refusal=verdict.declines and not stated if case.answerable else None,
        conflict_flagged=verdict.flags_conflict if case.conflict else None,
        refs_in_answer=refs_in_answer,
    )


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _share(values: Sequence[bool | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def aggregate(scores: Sequence[CaseScore]) -> dict[str, float | None]:
    claims = sum(s.claims for s in scores)
    return {
        "fact_recall": _mean([s.fact_recall for s in scores]),
        "cited_recall": _mean([s.cited_recall for s in scores]),
        "unsupported_claim_rate": _rate(
            sum(s.unsupported_claims for s in scores), claims
        ),
        "citation_precision": _mean([s.citation_precision for s in scores]),
        "must_not_violations": float(sum(s.must_not_violations for s in scores)),
        "correct_refusal": _share([s.correct_refusal for s in scores]),
        "false_refusal": _share([s.false_refusal for s in scores]),
        "conflict_flagged": _share([s.conflict_flagged for s in scores]),
        "refs_in_answer": _share([s.refs_in_answer for s in scores]),
    }
