"""Suppress catalog matches whose scoped words deny the edge they would propose.

Bare-verb frames match under negation catalog-wide; subject-side negation is
deliberately outside this guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium import phrasing

if TYPE_CHECKING:
    from spacy.tokens import Doc, Token


def _token_negator(token: "Token") -> str | None:
    for child in token.children:
        if child.dep_ == "neg":
            return child.text
    for child in token.children:
        if child.dep_ != "advmod":
            continue
        for grandchild in child.children:
            if grandchild.dep_ == "neg":
                return f"{grandchild.text} {child.text}"
        if child.lemma_.casefold() == "never":
            return child.text
    return None


def negated_verb(doc: "Doc", span: tuple[int, int]) -> str | None:
    """Return the negator scoped to the cue's verb, if one exists."""
    cue_span = doc.char_span(*span, alignment_mode="expand")
    if cue_span is None:
        return None
    anchors = [token for token in cue_span if token.pos_ in {"VERB", "AUX"}]
    if not anchors:
        head = cue_span.root
        # spaCy builds a fresh Token per access, so root detection must
        # compare indices: the sentence root is its own head.
        while head.head.i != head.i:
            head = head.head
            if head.pos_ in {"VERB", "AUX"}:
                anchors = [head]
                break
        if not anchors:
            return None
    for anchor in anchors:
        negator = _token_negator(anchor)
        if negator is not None:
            return negator
        if anchor.dep_ in {"aux", "auxpass"}:
            negator = _token_negator(anchor.head)
            if negator is not None:
                return negator
        # Greedy phrase groups can swallow coordinated clauses, so a negated
        # conjunct contaminates resolution with the denied target. Prefer
        # under-proposal to emitting that edge.
        for child in anchor.children:
            if child.dep_ == "conj" and child.pos_ in {"VERB", "AUX"}:
                negator = _token_negator(child)
                if negator is not None:
                    return negator
    return None


def negated_phrase_root(doc: "Doc", span: tuple[int, int]) -> str | None:
    """Return nominal negation attached directly to a captured phrase root."""
    phrase_span = doc.char_span(*span, alignment_mode="expand")
    if phrase_span is None:
        return None
    root = phrase_span.root
    lemma = root.lemma_.casefold()
    if lemma in {"none", "nothing", "nobody"}:
        return lemma
    # Quantifiers such as "no more than ten uploads" attach "no" to the
    # numeral as quantmod, not to the phrase root as det, so they pass.
    for child in root.children:
        if child.dep_ == "det" and child.lemma_.casefold() == "no":
            return "no"
    return None


def negated_connective(cue: str) -> str | None:
    """Return a whole-token negator found inside connective text."""
    doc = phrasing.get_nlp()(cue)
    for index, token in enumerate(doc):
        lemma = token.lemma_.casefold()
        # "No more/fewer/less than" names a bound and "no matter" a concession,
        # not denial; bare "no more" stays denial, so the bound needs its "than".
        if lemma == "no" and index + 1 < len(doc):
            following = doc[index + 1].lemma_.casefold()
            if following == "matter":
                continue
            if (
                following in {"more", "few", "fewer", "less"}
                and index + 2 < len(doc)
                and doc[index + 2].lemma_.casefold() == "than"
            ):
                continue
        if (
            token.dep_ == "neg"
            or lemma in {"no", "not", "never"}
            or token.text.casefold() == "n't"
        ):
            return token.text
    return None
