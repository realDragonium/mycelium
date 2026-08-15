"""Deterministically segment raw prose on the phrasing catalog's atomicity cues.

The segmenter preserves raw offsets while splitting blocks and spaCy sentences,
then recursively applies semicolon, compound-phrase, conditional, and conservative
verb-coordination cuts in that order. Conditional clauses become condition
fragments and propose a claim ``requires`` condition relation; causal
subordinators still cut but do not propose that relation. Final leaves are cleaned,
numbered in reading order, and checked again with the atomicity-only catalog so
compound remnants are marked rather than guessed.

Coordination may project a shared subject into a subject-less conjunct. That
fragment's span still covers only its original conjunct, so its surface text is
deliberately not an exact substring of the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mycelium import phrasing, phrasing_cues


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


@dataclass(frozen=True)
class ConditionProposal:
    claim: int
    condition: int
    cue: str


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
_MAX_CUT_DEPTH = 10


def _blocks(text: str) -> list[tuple[int, int]]:
    """Find paragraph and list-item slices without rewriting raw whitespace."""
    blocks: list[tuple[int, int]] = []
    plain_start: int | None = None
    plain_end = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        marker = _LIST_MARKER_RE.match(line)
        if not line.strip():
            if plain_start is not None:
                blocks.append((plain_start, plain_end))
                plain_start = None
        elif marker:
            if plain_start is not None:
                blocks.append((plain_start, plain_end))
                plain_start = None
            content_start = offset + marker.end()
            if text[content_start:line_end].strip():
                blocks.append((content_start, line_end))
        else:
            if plain_start is None:
                plain_start = offset
            plain_end = line_end
        offset = line_end
    if plain_start is not None:
        blocks.append((plain_start, plain_end))
    return blocks


def _sentences(text: str, blocks: list[tuple[int, int]]) -> list[_Piece]:
    """Parse raw blocks into globally numbered sentence pieces."""
    pieces: list[_Piece] = []
    sentence_index = 0
    nlp = phrasing._get_nlp()
    for block_start, block_end in blocks:
        block_text = text[block_start:block_end]
        for sentence in nlp(block_text).sents:
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


def _cut_semicolons(piece: _Piece) -> _Split | None:
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


def _compound_conjunct(piece: _Piece, connective_end: int):
    """Find a root verb's coordinated verb after a compound connective."""
    doc = phrasing._get_nlp()(piece.text)
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


def _cut_compound_phrases(piece: _Piece) -> _Split | None:
    """Cut at the earliest case-insensitive shared compound phrase."""
    matches = [
        match for pattern in _COMPOUND_PATTERNS if (match := pattern.search(piece.text))
    ]
    if not matches:
        return None
    match = min(matches, key=lambda item: item.start())
    left = _trim_piece(_subpiece(piece, 0, match.start()))
    right = _trim_piece(_subpiece(piece, match.end(), len(piece.text)))
    coordinated = _compound_conjunct(piece, match.end())
    if coordinated:
        head, conjunct = coordinated
        right = _project_subject(piece, head, conjunct, right)
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
    folded = piece.text.casefold()
    for opener in phrasing_cues.SUBORDINATOR_STRIP:
        end = start + len(opener)
        if folded[start:end] == opener.casefold() and end < len(piece.text):
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
        if child.lemma_ in phrasing_cues.PRECONDITION_SCONJ and child.pos_ in (
            "SCONJ",
            "ADP",
        ):
            return child
    return None


def _conditional_fronted(piece: _Piece, doc) -> _Split | None:
    """Cut an unlisted fronted clause without proposing a condition relation."""
    comma = piece.text.find(",")
    if comma < 0 or any(_advcl_cue(token) for token in doc):
        return None
    root = next((token for token in doc if token.dep_ == "ROOT"), None)
    has_finite_verb = any(
        token.idx < comma and token.pos_ in ("VERB", "AUX") for token in doc
    )
    if root is None or root.idx <= comma or not has_finite_verb:
        return None
    connective_end = comma + 1
    while connective_end < len(piece.text) and piece.text[connective_end].isspace():
        connective_end += 1
    condition = _trim_piece(_subpiece(piece, 0, comma, role="condition"))
    claim = _trim_piece(_subpiece(piece, connective_end, len(piece.text), role="claim"))
    return _split(
        piece,
        kind="conditional",
        connective_start=comma,
        connective_end=connective_end,
        left=condition,
        right=claim,
        claim_side="right",
        condition_side="left",
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


def _cut_conditional(piece: _Piece) -> _Split | None:
    """Apply initial, finite-fronted, then parsed advcl conditional rules."""
    doc = phrasing._get_nlp()(piece.text)
    initial = _conditional_initial(piece, doc)
    if initial:
        return initial
    fronted = _conditional_fronted(piece, doc)
    if fronted:
        return fronted
    return _conditional_advcl(piece, doc)


def _project_subject(piece: _Piece, head, conjunct, right: _Piece) -> _Piece:
    """Prefix a head verb's full subject subtree onto a subject-less conjunct."""
    subject_dependencies = ("nsubj", "nsubjpass")
    if any(child.dep_ in subject_dependencies for child in conjunct.children):
        return right
    subject = next(
        (child for child in head.children if child.dep_ in subject_dependencies), None
    )
    if subject is None:
        return right
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
    )


def _cut_coordination(piece: _Piece) -> _Split | None:
    """Reuse the catalog's conservative coordinated-verb rule verbatim."""
    doc = phrasing._get_nlp()(piece.text)
    for token in doc:
        if token.pos_ != "CCONJ" or token.lemma_ != "and":
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


def _descend(
    piece: _Piece,
    cuts: list[_PendingCut],
    proposals: list[_PendingProposal],
    depth: int = 0,
) -> list[_Piece]:
    """Recursively apply the first available cut rule to a piece."""
    if depth >= _MAX_CUT_DEPTH:
        return [piece]
    split = None
    for cutter in (
        _cut_semicolons,
        _cut_compound_phrases,
        _cut_conditional,
        _cut_coordination,
    ):
        split = cutter(piece)
        if split:
            break
    if split is None:
        return [piece]
    left_leaves = _descend(split.left, cuts, proposals, depth + 1)
    right_leaves = _descend(split.right, cuts, proposals, depth + 1)
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


def _mark_unsplit(text: str) -> bool:
    """Mark a leaf mechanically when any atomicity detector still fires."""
    return bool(phrasing.atomicity_violations(text))


def _fragments(leaves: list[_Piece]) -> tuple[list[Fragment], dict[int, int]]:
    """Clean, drop, number, and mark final leaf fragments."""
    fragments: list[Fragment] = []
    indices: dict[int, int] = {}
    for piece in leaves:
        cleaned = _clean_piece(piece)
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
                _mark_unsplit(cleaned.text),
                piece.subject_copied,
            )
        )
    return fragments, indices


def _resolve_cuts(pending: list[_PendingCut], indices: dict[int, int]) -> list[Cut]:
    """Resolve surviving pending cut references to public fragment indices."""
    cuts = [
        Cut(
            item.kind,
            item.connective,
            item.span,
            indices[id(item.left)],
            indices[id(item.right)],
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


def segment(text: str) -> Segmentation:
    """Segment raw text into atomic claims, conditions, cuts, and proposals.

    Preserve original offsets through block and sentence splitting, recursively
    cut each sentence in catalog order, assign conditional roles, re-check final
    leaves for unsplit atomicity cues, and number retained fragments in reading
    order. Causal clauses are cut without ``requires`` proposals. A projected
    subject is copied only into surface text; its fragment span remains the raw
    conjunct's source material.
    """
    if not text.strip():
        return Segmentation([], [], [])
    leaves: list[_Piece] = []
    pending_cuts: list[_PendingCut] = []
    pending_proposals: list[_PendingProposal] = []
    for sentence in _sentences(text, _blocks(text)):
        leaves.extend(_descend(sentence, pending_cuts, pending_proposals))
    leaves.sort(key=lambda piece: _span(piece) or (len(text), len(text)))
    fragments, indices = _fragments(leaves)
    return Segmentation(
        fragments,
        _resolve_cuts(pending_cuts, indices),
        _resolve_proposals(pending_proposals, indices),
    )
