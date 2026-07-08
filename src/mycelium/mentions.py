"""Deterministic lexical matcher for statement→entity mentions.

A statement *mentions* an entity when one of that entity's names or aliases
appears in the statement's text. This module derives those mentions purely
from the words — no embeddings, no model calls, no I/O. It is a pure function
of plain data (a name index + a string), so it is testable with lists and
dicts: no server, no database, no Ollama.

The wiring that reads names out of the substrate, calls this matcher on a
statement's text, and materializes the resulting rows lives elsewhere
(`server`/`store`). Keeping the logic here keeps the rules inspectable and
auditable in isolation — the whole point of deriving mentions instead of
letting them be asserted.

Matching rules
--------------
- **Tokenize on word boundaries, normalized.** Text and names are run through
  the same normalizer (`phrasing._normalize_with_map`: casefold + NFKC +
  dash/quote/space folding) and split into maximal runs of letters/digits.
  Matching is therefore exact at the *token* level — "result" never matches
  inside "resultant", because those are different tokens. No stemming, no
  match-time normalization beyond the shared fold.
- **Names match as token SEQUENCES.** A single-word name matches one token; a
  multi-word name matches a consecutive run of tokens.
- **Maximal munch resolves overlaps.** Across every candidate match, the
  longest token span wins; leftmost breaks a length tie; the tokens it covers
  are consumed; any shorter match overlapping a consumed span is dropped. So
  in "assessment part result", a name "assessment part result" suppresses both
  "assessment part" and "result" within that span. Two names that cover the
  *exact same* span (different entities whose names fold together — e.g.
  "Result" and "result") are co-mentions, not competitors: both survive, and
  dedup-to-entity keeps them distinct.
- **Dedup to entity.** One mention per entity, however many of its names hit.
- **Suspect names are held, not linked.** Short/common names (see
  `is_suspect_name`) are too ambiguous to auto-link — the same word can be a
  real reference in one statement and noise in another. A *surviving* suspect
  match (one that won its span under maximal munch) does not become a mention;
  it is reported as a suspect occurrence for per-occurrence human review. A
  suspect match that loses its span to a longer match is simply dropped.
  Suspect-ness never changes match priority — only span length does. Under the
  default rule suspect names are single short tokens, so in practice they never
  outrank a longer match; the algorithm does not depend on that, though — a
  suspect that does win its span is queued for review rather than linked.

Suspect-ness is treated as an *input* to the matcher: `build_index` stamps
each name via a pluggable predicate (default `is_suspect_name`), so the
detection rule can be tuned, or injected in tests, without touching the
matching algorithm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from . import survey
from .phrasing import _normalize_with_map

# A token is a maximal run of letters or digits (Unicode-aware, underscore is a
# separator). Punctuation and whitespace separate tokens, so apostrophes and
# hyphens split names the same way in text and in the stored name — what
# matters is that both sides tokenize identically, not how any single mark is
# handled.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: A single-token name whose normalized length is at most this is treated as
#: suspect (too short to safely auto-link). Tuned as a first pass — "flow" (4),
#: "result" (6) are suspect; "candidate" (9), "android" (7) are not. Adjust
#: here; the matcher reads suspect-ness as an input, so changing this never
#: touches the matching algorithm.
SUSPECT_MAX_LEN = 6


@dataclass(frozen=True)
class _Token:
    """A token of the source text and the original-text span it came from."""

    text: str
    start: int  # char offset into the ORIGINAL (pre-normalization) text
    end: int  # exclusive


@dataclass(frozen=True)
class IndexedName:
    """A name compiled into its normalized token sequence, ready to match."""

    tokens: tuple[str, ...]
    name_id: str
    entity_id: str
    text: str  # the stored name text, verbatim
    is_suspect: bool


@dataclass(frozen=True)
class Mention:
    """An auto-linked mention: this statement mentions `entity_id`, derived
    from the alias `name_id`/`name` matching at original-text [start, end)."""

    entity_id: str
    name_id: str
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class SuspectOccurrence:
    """A surviving suspect match held for human review. Not a link until a
    human approves this (statement, name) occurrence."""

    entity_id: str
    name_id: str
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class MatchResult:
    """The full outcome of matching one statement's text.

    `mentions` become stored edges directly. `suspects` are enqueued for
    per-occurrence review and only become edges once approved.
    """

    mentions: list[Mention]
    suspects: list[SuspectOccurrence]


@dataclass(frozen=True)
class _Candidate:
    """An in-progress match at a token position, before overlap resolution."""

    start: int  # token index where the match begins
    length: int  # number of tokens spanned
    char_start: int  # original-text char offset
    char_end: int
    indexed: IndexedName


# ─── tokenization ─────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[_Token]:
    """Normalize `text` and split into tokens carrying original-text spans.

    The original spans are recovered through the normalizer's position map, so
    a match's reported offsets point into the caller's untouched text even
    though matching happens on the folded form.
    """
    normalized, pos_map = _normalize_with_map(text)
    tokens: list[_Token] = []
    for m in _TOKEN_RE.finditer(normalized):
        n_start, n_end = m.start(), m.end()
        char_start = pos_map[n_start]
        char_end = pos_map[n_end - 1] + 1
        tokens.append(_Token(m.group(), char_start, char_end))
    return tokens


def _name_tokens(text: str) -> tuple[str, ...]:
    """The normalized token sequence of a name. Empty if the name has no
    word characters (it can then never match)."""
    normalized = _normalize_with_map(text)[0]
    return tuple(_TOKEN_RE.findall(normalized))


def text_contains_name(text: str, name_text: str) -> bool:
    """True if `name_text`'s token sequence appears as a contiguous run in
    `text` (same normalization + word-boundary rules as the matcher). Used
    by the recompute worker's scan pass to find statements that a new or
    renamed name newly matches — a cheap membership test, not full
    derivation."""
    name_toks = list(_name_tokens(name_text))
    if not name_toks:
        return False
    toks = [t.text for t in _tokenize(text)]
    n = len(name_toks)
    return any(toks[i : i + n] == name_toks for i in range(len(toks) - n + 1))


# ─── suspect detection (decision: short/common single words) ────────────────


def is_suspect_name(text: str) -> bool:
    """True if `text` is too ambiguous to safely auto-link.

    A single-token name is suspect when its token is:
      - a known function word (`survey._STOPWORDS`), or
      - at most `SUSPECT_MAX_LEN` characters (short, common), or
      - an English verb/past-participle form (length >= 5, ends in "-ed").

    Multi-word names are always distinctive — a two-word run is specific
    enough to trust.

    The "-ed" clause is length-independent and catches verb-form names that
    match the *verb*, not the entity: a hiring-status enum named "Rejected"
    matches "a webhook is rejected" / "the request was declined" all over a
    corpus. A semantic audit found such aliases ~96% wrong, so each occurrence
    is routed to human review instead of auto-linked. It is a deliberate
    heuristic — a genuine entity whose name happens to end in "-ed" is rare and
    is merely reviewed rather than silently auto-linked.

    Pure and computable from the name alone; no corpus scan. The matcher takes
    suspect-ness as an input, so a richer (e.g. frequency-based) refinement can
    be layered in later without changing this signature.
    """
    toks = _name_tokens(text)
    if len(toks) != 1:
        return False
    tok = toks[0]
    if tok in survey._STOPWORDS or len(tok) <= SUSPECT_MAX_LEN:
        return True
    return len(tok) >= 5 and tok.endswith("ed")


# ─── index construction ─────────────────────────────────────────────────────


def build_index(
    names: Iterable[tuple[str, str, str]],
    *,
    suspect: Callable[[str], bool] = is_suspect_name,
) -> dict[str, list[IndexedName]]:
    """Compile `(name_id, entity_id, text)` rows into a matcher index keyed by
    each name's first token.

    `suspect` stamps each name's suspect flag; the default is the standard
    rule, but tests (and a future tuned rule) can inject their own. Names with
    no word characters are skipped — they can never match.
    """
    index: dict[str, list[IndexedName]] = {}
    for name_id, entity_id, text in names:
        toks = _name_tokens(text)
        if not toks:
            continue
        index.setdefault(toks[0], []).append(
            IndexedName(
                tokens=toks,
                name_id=name_id,
                entity_id=entity_id,
                text=text,
                is_suspect=suspect(text),
            )
        )
    return index


# ─── matching ───────────────────────────────────────────────────────────────


def _find_candidates(
    tokens: Sequence[_Token], index: dict[str, list[IndexedName]]
) -> list[_Candidate]:
    """Every name match at every position, before overlap resolution."""
    candidates: list[_Candidate] = []
    n = len(tokens)
    for i, tok in enumerate(tokens):
        for indexed in index.get(tok.text, ()):
            seq = indexed.tokens
            length = len(seq)
            if i + length > n:
                continue
            if all(tokens[i + k].text == seq[k] for k in range(length)):
                candidates.append(
                    _Candidate(
                        start=i,
                        length=length,
                        char_start=tokens[i].start,
                        char_end=tokens[i + length - 1].end,
                        indexed=indexed,
                    )
                )
    return candidates


def _resolve_overlaps(candidates: list[_Candidate]) -> list[_Candidate]:
    """Apply maximal munch: longest span wins, leftmost breaks ties, consumed
    token positions block any overlapping shorter match.

    Candidates covering the *exact same* span (same start and length) are an
    exception: they are co-mentions of different entities whose names fold to
    the same tokens (`names.text` is unique but case-sensitive, and the shared
    fold collapses case/dash/quote variants). All of them are kept — dropping
    one by an arbitrary `name_id` tiebreak would leave that entity silently
    unlinkable with no review entry. `name_id` still orders the sort so output
    is deterministic.
    """
    ordered = sorted(candidates, key=lambda c: (-c.length, c.start, c.indexed.name_id))
    consumed: set[int] = set()
    accepted_spans: set[tuple[int, int]] = set()
    accepted: list[_Candidate] = []
    for c in ordered:
        span_key = (c.start, c.length)
        if span_key in accepted_spans:
            accepted.append(c)  # co-mention: same span already won
            continue
        positions = range(c.start, c.start + c.length)
        if any(pos in consumed for pos in positions):
            continue
        accepted.append(c)
        accepted_spans.add(span_key)
        consumed.update(positions)
    return accepted


def match_text(text: str, index: dict[str, list[IndexedName]]) -> MatchResult:
    """Derive the mentions and suspect occurrences for one statement's `text`.

    Distinctive matches become `mentions`, deduped to one per entity (the
    leftmost, then longest, match supplies the representative alias). An entity
    reached only through suspect matches contributes no mention; instead each
    distinct suspect (statement, name) is reported for review. An entity with
    even one distinctive hit is auto-linked, and its suspect hits are not
    queued — it is already mentioned.
    """
    tokens = _tokenize(text)
    accepted = _resolve_overlaps(_find_candidates(tokens, index))

    by_entity: dict[str, list[_Candidate]] = {}
    for c in accepted:
        by_entity.setdefault(c.indexed.entity_id, []).append(c)

    mentions: list[Mention] = []
    suspects: list[SuspectOccurrence] = []

    for entity_id, cands in by_entity.items():
        distinctive = [c for c in cands if not c.indexed.is_suspect]
        if distinctive:
            rep = min(
                distinctive, key=lambda c: (c.char_start, -c.length, c.indexed.name_id)
            )
            mentions.append(
                Mention(
                    entity_id=entity_id,
                    name_id=rep.indexed.name_id,
                    name=rep.indexed.text,
                    start=rep.char_start,
                    end=rep.char_end,
                )
            )
            continue
        # Entity reached only through suspect names → review, one per name.
        seen: set[str] = set()
        for c in sorted(cands, key=lambda c: (c.char_start, c.indexed.name_id)):
            if c.indexed.name_id in seen:
                continue
            seen.add(c.indexed.name_id)
            suspects.append(
                SuspectOccurrence(
                    entity_id=entity_id,
                    name_id=c.indexed.name_id,
                    name=c.indexed.text,
                    start=c.char_start,
                    end=c.char_end,
                )
            )

    mentions.sort(key=lambda m: (m.start, m.entity_id))
    suspects.sort(key=lambda s: (s.start, s.name_id))
    return MatchResult(mentions=mentions, suspects=suspects)
