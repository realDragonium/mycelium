"""Pure logic for `survey_statements` — query decomposition, sub-query
hygiene, and union ranking.

Everything here is a pure function of plain data: no embedding, no index,
no I/O. The side-effecting parts (embedding sub-queries, searching the
index, hydrating statements) live in `server.survey_statements`, which
wires these functions onto the substrate. Keeping the logic here means it
is testable with plain lists and dicts — no server, no Ollama, no hnswlib.

Decomposition is the one empirically-tuned knob (see `Decomposer`). The v1
default is a verb-preserving clause split; it only catches parts that are
lexically present in the query — a part expressed by a concept absent from
the words (e.g. "stop a reader seeing drafts" → *permissions*, with no
"permissions" token) will not surface here. That is expected: this is a
breadth primitive, not an intent interpreter.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

#: Sub-queries whose embedding vectors are at least this cosine-similar are
#: treated as the same angle and collapsed to one search. Tuned from data.
DEDUP_COSINE = 0.95

#: Function words that carry no retrieval signal on their own. A sub-query
#: made up entirely of these (or of single-char fragments) is dropped by
#: `usable` — it would only blur the search. Content words survive, so
#: "how are permissions assigned" keeps "permissions"/"assigned".
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "as",
        "than",
        "then",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "has",
        "have",
        "had",
        "having",
        "can",
        "could",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "this",
        "that",
        "these",
        "those",
        "how",
        "what",
        "why",
        "when",
        "where",
        "who",
        "whom",
        "whose",
        "which",
        "if",
        "whether",
        "not",
        "no",
        "yes",
        "vs",
        "versus",
    }
)

#: Clause boundaries for the default decomposer. Strong punctuation
#: (`; , ? & /` and newlines) plus coordinating conjunctions. Conjunctions
#: are matched with word boundaries so "android"/"corridor" are not split.
#: re.split drops the delimiters, leaving the surrounding clauses with their
#: verbs intact — important because statements are action-phrased, so a
#: verb-bearing clause embeds far better than a bare noun phrase.
_SPLIT_RE = re.compile(r"[;,?\n&/]|\band\b|\bor\b|\bvs\b|\bversus\b", re.IGNORECASE)

_WORD_RE = re.compile(r"[a-z0-9]+")


class Decomposer(Protocol):
    """The swap point for decomposition strategy.

    Any callable `str -> list[str]` satisfies it, so implementations are
    plain functions — no class hierarchy. `decompose` below is the v1
    default. A richer linguistic decomposer (e.g. spaCy noun-chunking via
    the `en_core_web_sm` model already loaded for phrasing validation in
    `phrasing._get_nlp`) can be swapped in later if traces show the cheap
    clause split misses parts — without touching `survey_statements`.
    """

    def __call__(self, query: str) -> list[str]: ...


def decompose(query: str) -> list[str]:
    """Split `query` into clause-level sub-queries on conjunctions and
    strong punctuation. Deterministic. Verb-preserving.

    A single-part query (no boundaries) comes back as a one-element list
    holding the whole query, so the caller searches it as-is.
    """
    return [piece.strip() for piece in _SPLIT_RE.split(query) if piece.strip()]


def usable(subquery: str) -> bool:
    """True if `subquery` carries retrieval signal — i.e. it is not a
    single-char fragment and not made up entirely of stopwords.
    """
    stripped = subquery.strip()
    if len(stripped) < 2:
        return False
    words = _WORD_RE.findall(stripped.lower())
    return any(word not in STOPWORDS for word in words)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors. 0.0 if either is a
    zero vector (undefined direction → treat as dissimilar)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def dedup_subqueries(
    subqueries: list[tuple[str, list[float]]],
    threshold: float = DEDUP_COSINE,
) -> list[tuple[str, list[float]]]:
    """Drop sub-queries whose vector is near-identical to one already kept,
    so the same angle is not searched twice.

    Order-preserving and keep-first: the earliest occurrence of an angle
    wins, which (with a deterministic decompose order) makes the output
    deterministic.
    """
    kept: list[tuple[str, list[float]]] = []
    for sub, vec in subqueries:
        if any(cosine(vec, kept_vec) >= threshold for _, kept_vec in kept):
            continue
        kept.append((sub, vec))
    return kept


def rank_statements(
    union: dict[str, tuple[int, float]],
) -> list[tuple[str, float]]:
    """Order the union of per-sub-query hits.

    `union` maps statement_id -> (count, best_cosine) where `count` is how
    many distinct sub-queries surfaced the statement and `best_cosine` is
    its closest match across them. Sorts by count desc (a statement central
    to a multi-part query is surfaced by several parts), then best_cosine
    desc, then statement_id asc as a stable final tiebreak so identical
    input always yields identical output.

    Returns `(statement_id, best_cosine)` pairs — the cosine becomes each
    hit's `score`. This count-driven ordering is the *only* trace of the
    multi-piece decomposition; it lives in ranking, never in the output
    shape.
    """
    return [
        (sid, best)
        for sid, (count, best) in sorted(
            union.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0])
        )
    ]
