"""Deterministically segment raw prose on the phrasing catalog's atomicity cues.

The segmenter preserves raw offsets while splitting blocks and spaCy sentences,
then recursively applies semicolon, compound-phrase, conditional or comma-splice,
and conservative verb-coordination cuts in that order. Conditional clauses become
condition fragments and propose a claim ``requires`` condition relation; causal
subordinators still cut but do not propose that relation. Final leaves are cleaned,
their newline-bearing whitespace is collapsed, and they are numbered in reading
order and checked again with the atomicity-only catalog so compound remnants are
marked rather than guessed.

Finite opener-less comma splices retain claim roles on both sides because the
comma states no relation. Rare inverted conditionals are therefore under-labelled
as claims rather than over-claimed as conditions.

Coordination may project a shared subject into a subject-less conjunct. That
fragment's span still covers only its original conjunct, so its surface text is
deliberately not an exact substring of the source. Newline-normalized fragments
similarly retain the envelope of their raw source material.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from mycelium import phrasing, phrasing_cues

if TYPE_CHECKING:
    from spacy.tokens import Doc

# Parses of the working texts seen in one `segment` call, keyed by text. The
# cutter chain re-runs at every recursion level, so without it a document-sized
# input pays the same spaCy parse many times over.
_Parses = dict[str, "Doc"]


@dataclass(frozen=True)
class Fragment:
    index: int
    text: str
    role: str
    span: tuple[int, int]
    sentence: int
    unsplit: bool
    subject_copied: bool


@dataclass(frozen=True)
class Cut:
    kind: str
    connective: str
    span: tuple[int, int]
    left: int
    right: int
    link_type: str | None = None
    #: The typing alias's direction, verbatim: "forward" links left to right,
    #: "reverse" names the relation from the far side and links right to left.
    link_direction: Literal["forward", "reverse"] = "forward"


@dataclass(frozen=True)
class ConditionProposal:
    claim: int
    condition: int
    cue: str
    link_type: str = "requires"


@dataclass(frozen=True)
class Segmentation:
    fragments: list[Fragment]
    cuts: list[Cut]
    proposals: list[ConditionProposal]


@dataclass(eq=False)
class _Piece:
    text: str
    origins: list[int | None]
    role: str
    sentence: int
    subject_copied: bool = False
    flagged: bool = False


@dataclass(frozen=True)
class _Split:
    kind: str
    connective: str
    span: tuple[int, int]
    left: _Piece
    right: _Piece
    claim_side: str | None = None
    condition_side: str | None = None
    cue: str | None = None


@dataclass(frozen=True)
class _PendingCut:
    kind: str
    connective: str
    span: tuple[int, int]
    left: _Piece
    right: _Piece


@dataclass(frozen=True)
class _PendingProposal:
    claim: _Piece
    condition: _Piece
    cue: str


_LIST_MARKER_RE = re.compile(r"^[ \t]*(?:[-*•–]|\d+[.)])[ \t]+")
_COMPOUND_PATTERNS = tuple(
    re.compile(pattern.pattern, pattern.flags | re.IGNORECASE)
    for pattern, _rule in phrasing_cues.COMPOUND_PHRASES
)
_SINGLE_WORD_SUBORDINATORS = frozenset(
    opener for opener in phrasing_cues.SUBORDINATOR_STRIP if " " not in opener
)
_TRAILING_MULTIWORD_SUBORDINATOR_RE = re.compile(
    r"(?<=\s)(?:"
    + "|".join(
        r"\s+".join(re.escape(word) for word in opener.split())
        for opener in phrasing_cues.SUBORDINATOR_STRIP
        if " " in opener
    )
    + r")(?=\s)",
    re.IGNORECASE,
)
_LEAF_WHITESPACE_RE = re.compile(r"\s+")
_MAX_CUT_DEPTH = 10


def _parse(text: str, parses: _Parses) -> "Doc":
    """Parse a working text, reusing this segmentation's earlier parse."""
    doc = parses.get(text)
    if doc is None:
        doc = phrasing.get_nlp()(text)
        parses[text] = doc
    return doc


def _blocks(text: str) -> list[tuple[int, int]]:
    """Find paragraph and list-item slices without rewriting raw whitespace."""
    blocks: list[tuple[int, int]] = []
    block_start: int | None = None
    block_end = 0
    list_item = False
    offset = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        marker = _LIST_MARKER_RE.match(line)
        if not line.strip():
            if block_start is not None:
                blocks.append((block_start, block_end))
                block_start = None
            list_item = False
        elif marker:
            if block_start is not None:
                blocks.append((block_start, block_end))
            content_start = offset + marker.end()
            if text[content_start:line_end].strip():
                block_start = content_start
                block_end = line_end
                list_item = True
            else:
                block_start = None
                list_item = False
        elif line[:1].isspace() and list_item and block_start is not None:
            block_end = line_end
        else:
            if list_item and block_start is not None:
                blocks.append((block_start, block_end))
                block_start = None
            if block_start is None:
                block_start = offset
            block_end = line_end
            list_item = False
        offset = line_end
    if block_start is not None:
        blocks.append((block_start, block_end))
    return blocks


def _sentences(
    text: str, blocks: list[tuple[int, int]], parses: _Parses
) -> list[_Piece]:
    """Parse raw blocks into globally numbered sentence pieces."""
    pieces: list[_Piece] = []
    sentence_index = 0
    for block_start, block_end in blocks:
        block_text = text[block_start:block_end]
        for sentence in _parse(block_text, parses).sents:
            if not sentence.text.strip():
                continue
            start = block_start + sentence.start_char
            end = block_start + sentence.end_char
            pieces.append(
                _Piece(
                    text[start:end], list(range(start, end)), "claim", sentence_index
                )
            )
            sentence_index += 1
    return pieces


def _subpiece(
    piece: _Piece, start: int, end: int, *, role: str | None = None
) -> _Piece:
    """Take a mapped slice from a working piece."""
    return _Piece(
        piece.text[start:end],
        piece.origins[start:end],
        role or piece.role,
        piece.sentence,
        piece.subject_copied,
        piece.flagged,
    )


def _join_pieces(parts: list[_Piece], *, role: str) -> _Piece:
    """Join mapped, potentially non-contiguous material into one piece."""
    if not parts:
        return _Piece("", [], role, 0)
    return _Piece(
        "".join(part.text for part in parts),
        [origin for part in parts for origin in part.origins],
        role,
        parts[0].sentence,
        any(part.subject_copied for part in parts),
        any(part.flagged for part in parts),
    )


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Advance a slice past the whitespace and commas at either end."""
    while start < end and _is_boundary(text[start]):
        start += 1
    while end > start and _is_boundary(text[end - 1]):
        end -= 1
    return start, end


def _is_boundary(char: str) -> bool:
    """Report whether a character is clause-boundary filler, not content."""
    return char.isspace() or char == ","


def _trim_piece(piece: _Piece) -> _Piece:
    """Remove whitespace and commas left at a clause boundary."""
    return _subpiece(piece, *_trim_bounds(piece.text, 0, len(piece.text)))


def _clean_piece(piece: _Piece) -> _Piece:
    """Trim a leaf's boundary filler and one sentence-final period.

    Text and origin map are trimmed together, so a fragment's span covers
    exactly the raw material its surface form came from.
    """
    start, end = _trim_bounds(piece.text, 0, len(piece.text))
    if end > start and piece.text[end - 1] == ".":
        start, end = _trim_bounds(piece.text, start, end - 1)
    return _subpiece(piece, start, end)


def _normalize_leaf_newlines(piece: _Piece) -> _Piece:
    """Collapse internal newline-bearing whitespace without drifting origins."""
    text_parts: list[str] = []
    origins: list[int | None] = []
    cursor = 0
    for match in _LEAF_WHITESPACE_RE.finditer(piece.text):
        if "\n" not in match.group() and "\r" not in match.group():
            continue
        text_parts.extend((piece.text[cursor : match.start()], " "))
        origins.extend(piece.origins[cursor : match.start()])
        origins.append(piece.origins[match.start()])
        cursor = match.end()
    if cursor == 0:
        return piece
    text_parts.append(piece.text[cursor:])
    origins.extend(piece.origins[cursor:])
    return replace(piece, text="".join(text_parts), origins=origins)


def _span(piece: _Piece) -> tuple[int, int] | None:
    """Return the original envelope of a piece's retained material."""
    origins = [origin for origin in piece.origins if origin is not None]
    if not origins:
        return None
    return (min(origins), max(origins) + 1)


def _connective(
    piece: _Piece, start: int, end: int
) -> tuple[str, tuple[int, int]] | None:
    """Resolve a working connective to an exact contiguous raw span."""
    origins = piece.origins[start:end]
    if not origins or any(origin is None for origin in origins):
        return None
    raw_origins = [origin for origin in origins if origin is not None]
    if raw_origins != list(range(raw_origins[0], raw_origins[0] + len(origins))):
        return None
    return piece.text[start:end], (raw_origins[0], raw_origins[-1] + 1)


def _usable(piece: _Piece) -> bool:
    """Report whether a prospective side retains fragment text."""
    return bool(_clean_piece(piece).text)


def _split(
    piece: _Piece,
    *,
    kind: str,
    connective_start: int,
    connective_end: int,
    left: _Piece,
    right: _Piece,
    claim_side: str | None = None,
    condition_side: str | None = None,
    cue: str | None = None,
) -> _Split | None:
    """Build a split only when both sides and its raw connective survive."""
    raw_connective = _connective(piece, connective_start, connective_end)
    if not raw_connective or not _usable(left) or not _usable(right):
        return None
    connective, span = raw_connective
    return _Split(
        kind,
        connective,
        span,
        left,
        right,
        claim_side,
        condition_side,
        cue,
    )


def _cut_semicolons(piece: _Piece, parses: _Parses) -> _Split | None:
    """Cut at the first semicolon and include following whitespace in the cue."""
    semicolon = piece.text.find(";")
    if semicolon < 0:
        return None
    connective_end = semicolon + 1
    while connective_end < len(piece.text) and piece.text[connective_end].isspace():
        connective_end += 1
    return _split(
        piece,
        kind="semicolon",
        connective_start=semicolon,
        connective_end=connective_end,
        left=_trim_piece(_subpiece(piece, 0, semicolon)),
        right=_trim_piece(_subpiece(piece, connective_end, len(piece.text))),
    )


def _compound_conjunct(piece: _Piece, connective_end: int, parses: _Parses):
    """Find a root verb's coordinated verb after a compound connective."""
    doc = _parse(piece.text, parses)
    return next(
        (
            (token.head, token)
            for token in doc
            if token.idx >= connective_end
            and token.dep_ == "conj"
            and token.pos_ == "VERB"
            and token.head.dep_ == "ROOT"
            and token.head.pos_ == "VERB"
        ),
        None,
    )


def _cut_compound_phrases(piece: _Piece, parses: _Parses) -> _Split | None:
    """Cut at the earliest case-insensitive shared compound phrase."""
    matches = [
        match for pattern in _COMPOUND_PATTERNS if (match := pattern.search(piece.text))
    ]
    if not matches:
        return None
    match = min(matches, key=lambda item: item.start())
    left = _trim_piece(_subpiece(piece, 0, match.start()))
    right = _trim_piece(_subpiece(piece, match.end(), len(piece.text)))
    coordinated = _compound_conjunct(piece, match.end(), parses)
    if coordinated:
        head, conjunct = coordinated
        right = _project_subject(piece, head, conjunct, right)
    elif not _stands_alone(right, parses):
        # A parse miss is safe to lift only when the remnant independently
        # demonstrates that it is a whole statement.
        right = replace(right, flagged=True)
    return _split(
        piece,
        kind="compound-phrase",
        connective_start=match.start(),
        connective_end=match.end(),
        left=left,
        right=right,
    )


def _initial_opener(piece: _Piece) -> tuple[int, int] | None:
    """Locate a strip-table opener at the start of a piece."""
    start = len(piece.text) - len(piece.text.lstrip())
    for opener in phrasing_cues.SUBORDINATOR_STRIP:
        end = start + len(opener)
        # Fold the slice, not the whole text: casefolding can change length
        # ("ß" folds to "ss"), which would drift the returned raw span.
        if piece.text[start:end].casefold() == opener.casefold() and end < len(
            piece.text
        ):
            if piece.text[end].isspace():
                return start, end
    return None


def _initial_clause_tokens(doc, opener: tuple[int, int]) -> list | None:
    """Derive an initial condition clause from its parsed opener."""
    opener_start, opener_end = opener
    opener_token = next((token for token in doc if token.idx == opener_start), None)
    if opener_token is None:
        return None
    if opener_token.dep_ in ("mark", "case", "advmod"):
        clause_tokens = sorted(opener_token.head.subtree, key=lambda item: item.idx)
    else:
        clause_tokens = sorted(opener_token.subtree, key=lambda item: item.idx)
    if not clause_tokens or clause_tokens[0].idx != opener_start:
        return None
    clause_ids = {token.i for token in clause_tokens}
    opener_tokens = [
        token
        for token in doc
        if token.idx < opener_end and token.idx + len(token.text) > opener_start
    ]
    if not opener_tokens or any(token.i not in clause_ids for token in opener_tokens):
        return None
    return clause_tokens


def _initial_subtree_sides(
    piece: _Piece, doc, opener: tuple[int, int]
) -> tuple[_Piece, _Piece] | None:
    """Build initial conditional sides from the opener's parsed clause."""
    clause_tokens = _initial_clause_tokens(doc, opener)
    if clause_tokens is None:
        return None
    opener_start, opener_end = opener
    clause_ids = {token.i for token in clause_tokens}
    condition_piece = _piece_from_tokens(piece, clause_tokens, role="condition")
    condition = _trim_piece(
        _subpiece(
            condition_piece,
            opener_end - opener_start,
            len(condition_piece.text),
        )
    )
    claim_tokens = [token for token in doc if token.i not in clause_ids]
    claim = _trim_piece(_piece_from_tokens(piece, claim_tokens, role="claim"))
    if not _usable(claim):
        return None
    return condition, claim


def _initial_comma_sides(
    piece: _Piece, opener_end: int
) -> tuple[_Piece, _Piece] | None:
    """Build initial conditional sides from the first comma fallback."""
    comma = piece.text.find(",", opener_end)
    if comma < 0:
        return None
    condition = _trim_piece(_subpiece(piece, opener_end, comma, role="condition"))
    claim = _trim_piece(_subpiece(piece, comma + 1, len(piece.text), role="claim"))
    return condition, claim


def _conditional_initial(piece: _Piece, doc) -> _Split | None:
    """Cut an initial strip-table condition at its parsed clause boundary."""
    opener = _initial_opener(piece)
    if not opener:
        return None
    opener_start, opener_end = opener
    sides = _initial_subtree_sides(piece, doc, opener)
    if sides is None:
        sides = _initial_comma_sides(piece, opener_end)
    if sides is None:
        return None
    condition, claim = sides
    cue = piece.text[opener_start:opener_end]
    return _split(
        piece,
        kind="conditional",
        connective_start=opener_start,
        connective_end=opener_end,
        left=condition,
        right=claim,
        claim_side="right",
        condition_side="left",
        cue=cue,
    )


def _advcl_cue(token):
    """Find the catalog subordinator child of an adverbial clause."""
    if token.dep_ != "advcl":
        return None
    for child in token.children:
        if child.dep_ not in ("mark", "case", "advmod"):
            continue
        catalogued = (
            child.lemma_ in phrasing_cues.PRECONDITION_SCONJ
            or child.text.lower() in _SINGLE_WORD_SUBORDINATORS
        )
        if child.pos_ in ("SCONJ", "ADP") and catalogued:
            return child
    return None


def _is_finite_clause_token(token) -> bool:
    """Report whether a token demonstrates a genuinely finite clause."""
    if token.pos_ not in ("VERB", "AUX"):
        return False
    return "Fin" in token.morph.get("VerbForm") or any(
        child.dep_ in ("nsubj", "nsubjpass") for child in token.children
    )


def _stands_alone(piece: _Piece, parses: _Parses) -> bool:
    """Require a finite, explicitly subject-bearing root clause.

    Verb/noun homographs such as "runs" can be mistagged beside a multiword
    opener. Requiring the stand-alone parse's root, rather than any embedded
    verb, prevents a relative clause inside a noun phrase from promoting the
    phrase as a whole statement.
    """
    cleaned = _clean_piece(piece)
    if not cleaned.text:
        return False
    root = next(
        (token for token in _parse(cleaned.text, parses) if token.dep_ == "ROOT"),
        None,
    )
    return (
        root is not None
        and root.pos_ in ("VERB", "AUX")
        and any(child.dep_ in ("nsubj", "nsubjpass") for child in root.children)
    )


def _cut_comma_splice(piece: _Piece, doc) -> _Split | None:
    """Cut a finite opener-less comma splice without inferring clause roles.

    A rare inverted conditional is deliberately under-labelled as two claims:
    a bare comma is not enough evidence to assert a condition.
    """
    comma = piece.text.find(",")
    if comma < 0 or any(_advcl_cue(token) for token in doc):
        return None
    root = next((token for token in doc if token.dep_ == "ROOT"), None)
    has_finite_verb = any(
        token.idx < comma and _is_finite_clause_token(token) for token in doc
    )
    if root is None or root.idx <= comma or not has_finite_verb:
        return None
    connective_end = comma + 1
    while connective_end < len(piece.text) and piece.text[connective_end].isspace():
        connective_end += 1
    left = _trim_piece(_subpiece(piece, 0, comma, role="claim"))
    right = _trim_piece(_subpiece(piece, connective_end, len(piece.text), role="claim"))
    return _split(
        piece,
        kind="comma-splice",
        connective_start=comma,
        connective_end=connective_end,
        left=left,
        right=right,
    )


def _piece_from_tokens(piece: _Piece, tokens: list, *, role: str) -> _Piece:
    """Rebuild mapped text from a possibly non-contiguous token set."""
    parts = [
        _subpiece(piece, token.idx, token.idx + len(token.text_with_ws), role=role)
        for token in sorted(tokens, key=lambda item: item.idx)
    ]
    return _join_pieces(parts, role=role)


def _condition_without_opener(piece: _Piece, clause_tokens: list) -> _Piece:
    """Remove only a strip-table opener from a parsed condition."""
    condition = _piece_from_tokens(piece, clause_tokens, role="condition")
    opener = _initial_opener(condition)
    if opener:
        return _trim_piece(_subpiece(condition, opener[1], len(condition.text)))
    return _trim_piece(condition)


def _is_contiguous(tokens: list) -> bool:
    """Report whether tokens form one unbroken run, trailing filler aside."""
    indices = [token.i for token in tokens]
    # A list item's block keeps its trailing newline, which spaCy tokenizes as a
    # SPACE token after the final period — without dropping it the run looks
    # broken and the cut is refused for text that splits fine on its own.
    while indices and (
        tokens[len(indices) - 1].is_punct or tokens[len(indices) - 1].is_space
    ):
        indices.pop()
    return bool(indices) and indices == list(
        range(indices[0], indices[0] + len(indices))
    )


def _conditional_advcl(piece: _Piece, doc) -> _Split | None:
    """Cut a parsed adverbial clause and suppress causal proposals."""
    for token in doc:
        cue_token = _advcl_cue(token)
        if cue_token is None:
            continue
        clause_tokens = sorted(token.subtree, key=lambda item: item.idx)
        clause_ids = {item.i for item in clause_tokens}
        condition = _condition_without_opener(piece, clause_tokens)
        claim_tokens = [item for item in doc if item.i not in clause_ids]
        # A medial clause leaves material on both sides: splicing it would
        # invent a surface form and stretch the span over the removed clause.
        if not _is_contiguous(claim_tokens):
            continue
        claim = _trim_piece(_piece_from_tokens(piece, claim_tokens, role="claim"))
        if not _usable(claim):
            continue
        condition_span = _span(condition)
        claim_span = _span(claim)
        if condition_span is None or claim_span is None:
            continue
        condition_first = condition_span[0] < claim_span[0]
        left, right = (condition, claim) if condition_first else (claim, condition)
        cue = cue_token.text
        proposal_cue = None if cue_token.lemma_ in phrasing_cues.CAUSAL_SCONJ else cue
        # Unstripped cue spans deliberately overlap the condition: 5.1 still
        # needs the cue's exact source location.
        return _split(
            piece,
            kind="conditional",
            connective_start=cue_token.idx,
            connective_end=cue_token.idx + len(cue_token.text),
            left=left,
            right=right,
            claim_side="right" if condition_first else "left",
            condition_side="left" if condition_first else "right",
            cue=proposal_cue,
        )
    return None


def _conditional_trailing_multiword(
    piece: _Piece, doc, parses: _Parses
) -> _Split | None:
    """Cut a trailing catalog opener when spaCy misses its clause shape."""
    for match in _TRAILING_MULTIWORD_SUBORDINATOR_RE.finditer(piece.text):
        opener_token = next(
            (token for token in doc if token.idx == match.start()), None
        )
        # Veto only: a parse mistake here may prevent a cut, but must never let
        # a degree comparison invent a condition relation.
        if opener_token is not None and opener_token.head.dep_ == "acomp":
            continue
        left = _trim_piece(_subpiece(piece, 0, match.start(), role="claim"))
        right = _trim_piece(
            _subpiece(piece, match.end(), len(piece.text), role="condition")
        )
        has_left_clause = any(
            token.idx < match.start() and _is_finite_clause_token(token)
            for token in doc
        ) or _stands_alone(left, parses)
        has_right_clause = any(
            token.idx >= match.end() and _is_finite_clause_token(token) for token in doc
        ) or _stands_alone(right, parses)
        if not has_left_clause or not has_right_clause:
            continue
        return _split(
            piece,
            kind="conditional",
            connective_start=match.start(),
            connective_end=match.end(),
            left=left,
            right=right,
            claim_side="left",
            condition_side="right",
            cue=match.group(),
        )
    return None


def _cut_conditional(piece: _Piece, parses: _Parses) -> _Split | None:
    """Apply initial, comma-splice, parsed, then textual conditional rules."""
    doc = _parse(piece.text, parses)
    initial = _conditional_initial(piece, doc)
    if initial:
        return initial
    comma_splice = _cut_comma_splice(piece, doc)
    if comma_splice:
        return comma_splice
    advcl = _conditional_advcl(piece, doc)
    if advcl:
        return advcl
    return _conditional_trailing_multiword(piece, doc, parses)


def _project_subject(piece: _Piece, head, conjunct, right: _Piece) -> _Piece:
    """Prefix a head verb's full subject subtree onto a subject-less conjunct."""
    subject_dependencies = ("nsubj", "nsubjpass")
    if any(child.dep_ in subject_dependencies for child in conjunct.children):
        return right
    subject = next(
        (child for child in head.children if child.dep_ in subject_dependencies), None
    )
    if subject is None:
        # No shared subject to project: the conjunct stays as-is and flags.
        return replace(right, flagged=True)
    subject_piece = _piece_from_tokens(piece, list(subject.subtree), role=right.role)
    subject_text = subject_piece.text.strip()
    right_start = len(right.text) - len(right.text.lstrip())
    right = _subpiece(right, right_start, len(right.text))
    prefix = f"{subject_text} "
    return _Piece(
        prefix + right.text,
        [None] * len(prefix) + right.origins,
        right.role,
        right.sentence,
        True,
        right.flagged,
    )


def _cut_coordination(piece: _Piece, parses: _Parses) -> _Split | None:
    """Reuse the catalog's conservative coordinated-verb rule verbatim."""
    doc = _parse(piece.text, parses)
    for token in doc:
        if (
            token.pos_ != "CCONJ"
            or token.lemma_ not in phrasing_cues.COORDINATING_CONJUNCTIONS
        ):
            continue
        head = token.head
        if head.pos_ != "VERB":
            continue
        # Only top-level coordination is safe: embedded heads omit material
        # outside their subtree, so leave them intact for the catalog to flag.
        if head.dep_ != "ROOT":
            continue
        conjuncts = [
            child
            for child in head.children
            if child.dep_ == "conj" and child.pos_ == "VERB"
        ]
        if not conjuncts:
            continue
        conjunct = min(conjuncts, key=lambda item: (item.idx <= token.idx, item.idx))
        right_tokens = list(conjunct.subtree)
        right_ids = {item.i for item in right_tokens}
        left_tokens = [
            item
            for item in head.subtree
            if item.i not in right_ids and item.i != token.i
        ]
        # Material on both sides of the conjunct: splicing it would invent a
        # surface form and stretch its span across the removed conjunct.
        if not _is_contiguous(left_tokens):
            continue
        left = _trim_piece(_piece_from_tokens(piece, left_tokens, role=piece.role))
        right = _trim_piece(_piece_from_tokens(piece, right_tokens, role=piece.role))
        right = _project_subject(piece, head, conjunct, right)
        split = _split(
            piece,
            kind="coordination",
            connective_start=token.idx,
            connective_end=token.idx + len(token.text),
            left=left,
            right=right,
        )
        if split:
            return split
    return None


def _boundary(leaves: list[_Piece], side: str) -> _Piece:
    """Select the leaf adjacent to a cut boundary."""
    return leaves[-1] if side == "left" else leaves[0]


def _role_boundary(leaves: list[_Piece], side: str, role: str) -> _Piece:
    """Select the nearest boundary leaf with the expected semantic role."""
    candidates = [piece for piece in leaves if piece.role == role]
    return _boundary(candidates or leaves, side)


def _record_proposal(
    split: _Split,
    left_leaves: list[_Piece],
    right_leaves: list[_Piece],
    proposals: list[_PendingProposal],
) -> None:
    """Record a conditional proposal against the leaves bordering its cut."""
    if not split.cue or not split.claim_side or not split.condition_side:
        return
    leaves = {"left": left_leaves, "right": right_leaves}
    claim = _role_boundary(leaves[split.claim_side], split.claim_side, "claim")
    condition = _role_boundary(
        leaves[split.condition_side], split.condition_side, "condition"
    )
    proposals.append(_PendingProposal(claim, condition, split.cue))


def _cut_boundaries(
    split: _Split, left_leaves: list[_Piece], right_leaves: list[_Piece]
) -> tuple[_Piece, _Piece]:
    """Select reading-order leaves immediately represented by a split."""
    if split.claim_side == "left":
        return (
            _role_boundary(left_leaves, "left", "claim"),
            _role_boundary(right_leaves, "right", "condition"),
        )
    if split.condition_side == "left":
        return (
            _role_boundary(left_leaves, "left", "condition"),
            _role_boundary(right_leaves, "right", "claim"),
        )
    return left_leaves[-1], right_leaves[0]


def _cutters(piece: _Piece) -> tuple:
    """Order the cut rules; an initial conditional opener outranks a phrase cut.

    "If X, then Y" carries both cues, and the conditional is the one that
    yields a condition fragment and a requires proposal.
    """
    if _initial_opener(piece):
        return (
            _cut_semicolons,
            _cut_conditional,
            _cut_compound_phrases,
            _cut_coordination,
        )
    return (
        _cut_semicolons,
        _cut_compound_phrases,
        _cut_conditional,
        _cut_coordination,
    )


def _descend(
    piece: _Piece,
    cuts: list[_PendingCut],
    proposals: list[_PendingProposal],
    parses: _Parses,
    depth: int = 0,
) -> list[_Piece]:
    """Recursively apply the first available cut rule to a piece."""
    if depth >= _MAX_CUT_DEPTH:
        return [piece]
    split = None
    for cutter in _cutters(piece):
        split = cutter(piece, parses)
        if split:
            break
    if split is None:
        return [piece]
    left_leaves = _descend(split.left, cuts, proposals, parses, depth + 1)
    right_leaves = _descend(split.right, cuts, proposals, parses, depth + 1)
    left_boundary, right_boundary = _cut_boundaries(split, left_leaves, right_leaves)
    cuts.append(
        _PendingCut(
            split.kind,
            split.connective,
            split.span,
            left_boundary,
            right_boundary,
        )
    )
    _record_proposal(split, left_leaves, right_leaves, proposals)
    return left_leaves + right_leaves


def _mark_unsplit(text: str, parses: _Parses) -> bool:
    """Mark a leaf mechanically when any atomicity detector still fires."""
    return bool(
        phrasing.atomicity_violations(
            text, parse=lambda normalized: _parse(normalized, parses)
        )
    )


def _fragments(
    leaves: list[_Piece], parses: _Parses
) -> tuple[list[Fragment], dict[int, int]]:
    """Clean, drop, number, and mark final leaf fragments."""
    fragments: list[Fragment] = []
    indices: dict[int, int] = {}
    for piece in leaves:
        cleaned = _normalize_leaf_newlines(_clean_piece(piece))
        raw_span = _span(cleaned)
        if not cleaned.text or raw_span is None:
            continue
        index = len(fragments)
        indices[id(piece)] = index
        fragments.append(
            Fragment(
                index,
                cleaned.text,
                piece.role,
                raw_span,
                piece.sentence,
                piece.flagged or _mark_unsplit(cleaned.text, parses),
                piece.subject_copied,
            )
        )
    return fragments, indices


#: Boundary filler a raw connective slice carries that an alias never does —
#: a cut records `", then"` or `";"`, the alias table stores `"then"`.
_CONNECTIVE_EDGE_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def connective_cue(connective: str) -> str:
    """Reduce a raw connective slice to the alias-shaped cue it carries."""
    stripped = _CONNECTIVE_EDGE_RE.sub("", connective)
    return " ".join(stripped.casefold().split())


def _connective_link_type(
    connective: str, aliases: Mapping[str, frozenset[tuple[str, str]]]
) -> tuple[str, str] | None:
    """Resolve a normalized connective only when one link type carries it.

    Returns the (link type, direction) pair; an alias carried by multiple
    types is real ambiguity, not grounds to guess.
    """
    pairs = aliases.get(connective_cue(connective), frozenset())
    # More than one pair is real ambiguity either way: several types, or one
    # type claimed in both directions by a hand-built mapping (the store's
    # primary key makes that impossible, but this layer takes any Mapping).
    if len(pairs) != 1:
        return None
    return next(iter(pairs))


#: Cut kinds whose connective is never a left→right relation, whatever alias a
#: curator registers for it. A conditional runs the other way and its relation
#: is already proposed with the right orientation; coordination is not a
#: relation at all. A comma splice's bare comma expresses no typed relation.
UNTYPED_CUT_KINDS = frozenset({"conditional", "coordination", "comma-splice"})


def _cut_link_type(
    cut: _PendingCut, aliases: Mapping[str, frozenset[tuple[str, str]]]
) -> tuple[str, str] | None:
    """Resolve a cut's connective to the one typed pair its aliases name."""
    if cut.kind in UNTYPED_CUT_KINDS:
        return None
    return _connective_link_type(cut.connective, aliases)


def _resolve_cuts(
    pending: list[_PendingCut],
    indices: dict[int, int],
    aliases: Mapping[str, frozenset[tuple[str, str]]] | None,
) -> list[Cut]:
    """Resolve surviving pending cut references to public fragment indices."""
    aliases = aliases or {}
    cuts = [
        Cut(
            item.kind,
            item.connective,
            item.span,
            indices[id(item.left)],
            indices[id(item.right)],
            *(_cut_link_type(item, aliases) or (None, "forward")),
        )
        for item in pending
        if id(item.left) in indices and id(item.right) in indices
    ]
    return sorted(cuts, key=lambda item: item.span)


def _resolve_proposals(
    pending: list[_PendingProposal], indices: dict[int, int]
) -> list[ConditionProposal]:
    """Resolve surviving conditional references to public fragment indices."""
    proposals = [
        ConditionProposal(
            indices[id(item.claim)], indices[id(item.condition)], item.cue
        )
        for item in pending
        if id(item.claim) in indices and id(item.condition) in indices
    ]
    return proposals


def segment(
    text: str, *, aliases: Mapping[str, frozenset[tuple[str, str]]] | None = None
) -> Segmentation:
    """Segment raw text into atomic claims, conditions, cuts, and proposals.

    Preserve original offsets through block and sentence splitting, recursively
    cut each sentence in catalog order, assign conditional roles, re-check final
    leaves for unsplit atomicity cues, and number retained fragments in reading
    order. Conditional proposals carry their relation type, which defaults to
    ``requires``; causal clauses are cut without proposals. A projected
    subject is copied only into surface text; its fragment span remains the raw
    conjunct's source material. Resolve cut connectives carried by exactly one
    supplied alias to that link type.
    """
    if not text.strip():
        return Segmentation([], [], [])
    leaves: list[_Piece] = []
    pending_cuts: list[_PendingCut] = []
    pending_proposals: list[_PendingProposal] = []
    parses: _Parses = {}
    for sentence in _sentences(text, _blocks(text), parses):
        leaves.extend(_descend(sentence, pending_cuts, pending_proposals, parses))
    leaves.sort(key=lambda piece: _span(piece) or (len(text), len(text)))
    fragments, indices = _fragments(leaves, parses)
    return Segmentation(
        fragments,
        _resolve_cuts(pending_cuts, indices, aliases),
        _resolve_proposals(pending_proposals, indices),
    )
