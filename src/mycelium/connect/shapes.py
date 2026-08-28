"""Classify statement kinds with positive phrasing-shape matches.

Passive participle lexicons are separate allow-lists because
``X is <participle>`` is shared by events, states, and rules. Unknown passive
participles must remain unmatched so precision degrades gracefully on
vocabulary the lexicons have never seen. Their entries must be lemmas the
parser actually emits in that shape's frame; lemmatizer quirks make some
vocabulary unreachable. Noun/verb homographs can also defeat a shape entirely:
"The nightly backup runs" parses "runs" as a noun and intentionally remains
unmatched rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from mycelium import phrasing

if TYPE_CHECKING:
    from spacy.tokens import Doc, Token


DESCRIPTIVE_KINDS = ("event", "state", "capability", "rule", "property")
# `cause` is deliberately absent: a cause is identified by what it explains,
# not by any phrasing of its own, so no shape can recognise one.
PRESCRIPTIVE_KINDS = ("procedure", "action", "check")

CAPABILITY_MODALS = frozenset({"can", "could", "may", "might"})

# These allow-lists must stay pairwise disjoint to control passive collisions.
STATE_PARTICIPLES = frozenset(
    {
        "activate",
        "associate",
        "bind",
        "configure",
        "deactivate",
        "disable",
        "enable",
        "expire",
        "find",
        "hide",
        "lock",
        "match",
        "populate",
        "register",
        "restrict",
        "set",
        "unlock",
    }
)
EVENT_PARTICIPLES = frozenset(
    {
        "abandon",
        "access",
        "acknowledge",
        "advance",
        "archive",
        "authenticate",
        "cancel",
        "create",
        "decode",
        "delete",
        "deliver",
        "dispatch",
        "download",
        "email",
        "emit",
        "enqueue",
        "escalate",
        "export",
        "forward",
        "generate",
        "insert",
        "invite",
        "invoke",
        "issue",
        "launch",
        "log",
        "migrate",
        "move",
        "notify",
        "open",
        "persist",
        "process",
        "provision",
        "publish",
        "purge",
        "queue",
        "receive",
        "record",
        "redirect",
        "refresh",
        "reject",
        "remove",
        "rename",
        "request",
        "reset",
        "restore",
        "retrieve",
        "retry",
        "return",
        "revoke",
        "save",
        "schedule",
        "send",
        "skip",
        "submit",
        "sync",
        "synchronize",
        "trigger",
        "update",
        "upload",
        "validate",
        "verify",
        "write",
    }
)
# Membership is keyed on the ADJ complement's lowercased surface form because
# spaCy's ADJ lemma equals its surface. Include a word only when spaCy actually
# tags it ADJ on this copula frame, its adjectival state reading is implausible,
# and an event reading was intended. Legitimate adjectival states such as
# "open", "empty", and "closed" must never be added, so this is curated rather
# than accepting any participle-looking ADJ. To extend it, add the word and
# confirm test_ambiguous_event_participle_entries_are_reachable_and_compete
# still passes. ``un``-prefixed participles such as "unlinked" stay out because
# their negative-state reading is plausible.
AMBIGUOUS_EVENT_PARTICIPLES = frozenset({"resent", "upserted"})
RULE_PARTICIPLES = frozenset(
    {
        "bound",
        "cap",
        "derive",
        "determine",
        "exclude",
        "express",
        "force",
        "limit",
        "normalize",
        "round",
        "weight",
    }
)

EVENT_VERBS = frozenset(
    {"arrive", "click", "enter", "fall", "occur", "press", "result", "run", "submit"}
)
STATE_VERBS = frozenset(
    {"belong", "carry", "contain", "exist", "lack", "list", "remain"}
)
RULE_VERBS = frozenset(
    {
        "apply",
        "contribute",
        "count",
        "default",
        "earn",
        "equal",
        "follow",
        "hold",
        "treat",
        "weigh",
        "yield",
    }
)

# Present-perfect participles that leave a condition behind rather than
# report an occurrence — the positive evidence `state-perfect` needs.
PERFECT_STATE_PARTICIPLES = frozenset(
    {"elapse", "end", "expire", "fail", "finish", "lapse", "stop"}
)

LEVEL_LEMMAS = frozenset({"low", "medium", "high"})
NEGATED_NP_OPENERS = frozenset({"no", "missing", "without"})

UI_ACTION_LEMMAS = frozenset(
    {
        "add",
        "choose",
        "click",
        "collapse",
        "copy",
        "create",
        "delete",
        "disable",
        "download",
        "drag",
        "drop",
        "enable",
        "enter",
        "expand",
        "fill",
        "go",
        "navigate",
        "open",
        "paste",
        "press",
        "remove",
        "save",
        "scroll",
        "select",
        "send",
        "set",
        "submit",
        "toggle",
        "type",
        "upload",
    }
)
CHECK_LEMMAS = frozenset(
    {
        "check",
        "compare",
        "confirm",
        "ensure",
        "inspect",
        "look",
        "review",
        "validate",
        "verify",
    }
)

SHAPE_NAMES = (
    "capability-modal",
    "event-passive",
    "event-active",
    "event-participle-adj",
    "state-passive",
    "state-perfect",
    "state-copula-condition",
    "state-possession",
    "state-stative-verb",
    "state-negated-np",
    "rule-passive",
    "rule-formula",
    "rule-band",
    "rule-measure",
    "property-noun-phrase",
    "action-imperative",
    "check-imperative",
    "procedure-how-to",
)

_PERFECT_STATE_LEMMAS = STATE_PARTICIPLES | PERFECT_STATE_PARTICIPLES
_PRESENT_TAGS = frozenset({"VBZ", "VBP"})
_OBJECT_DEPS = frozenset({"dobj", "obj", "dative", "attr", "oprd"})
_COMPLEMENT_DEPS = frozenset({"attr", "acomp", "oprd"})
_BAND_MARKERS = frozenset({"for", "when", "unless", "if"})
# "is able to" is the periphrastic capability modal, not a condition holding.
_PERIPHRASTIC_MODAL_ADJECTIVES = frozenset({"able", "unable"})
_DETERMINERS = frozenset({"a", "an", "the"})
_HOW_TO_RE = re.compile(r"how\s+to\b", re.IGNORECASE)
_ABLE_TO_RE = re.compile(r"(?:^|\s)able\s+to(?:\s|$)", re.IGNORECASE)
_RULE_FORMULA_RE = re.compile(
    r"\b(plus|minus|times)\b"
    r"|\b(multiplied|divided) by\b"
    r"|\bis (one of|either)\b"
    r"|\bdefaults? to\b"
    r"|\b(is|are) (bounded|capped|limited)\b"
    r"|\b(is|are) determined by\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ShapeMatch:
    """Describe one positive kind-shape match."""

    kind: str
    shape: str
    evidence: str


@dataclass(frozen=True)
class Classification:
    """Describe the result of distinct-kind shape classification."""

    kind: str | None
    status: str
    matches: tuple[ShapeMatch, ...]


def _root(doc: Doc) -> Token | None:
    """Return the dependency root when the parser produced one."""
    return next((token for token in doc if token.dep_ == "ROOT"), None)


def _auxpass_child(root: Token) -> Token | None:
    """Return the root's passive auxiliary when present."""
    return next((child for child in root.children if child.dep_ == "auxpass"), None)


def _modal(doc: Doc) -> Token | None:
    """Return the first capability modal in a document."""
    return next(
        (
            token
            for token in doc
            if token.pos_ == "AUX" and token.lemma_.lower() in CAPABILITY_MODALS
        ),
        None,
    )


def _is_negated(modal: Token) -> bool:
    """Report whether a negation particle attaches to the modal's head."""
    return any(child.dep_ == "neg" for child in modal.head.children)


def _has_negation(doc: Doc) -> bool:
    """Report whether the fragment carries a negation particle at all."""
    return any(token.dep_ == "neg" for token in doc)


def _coordinated_predicate(root: Token) -> Token | None:
    """Return a second predicate coordinated with the root, when there is one."""
    return next(
        (
            child
            for child in root.children
            if child.dep_ == "conj" and child.pos_ in {"VERB", "AUX"}
        ),
        None,
    )


def _complement(root: Token) -> Token | None:
    """Return the first copular complement in dependency order."""
    return next(
        (child for child in root.children if child.dep_ in _COMPLEMENT_DEPS), None
    )


def _band_marker(doc: Doc, root: Token) -> Token | None:
    """Return the first band marker that conditions the copula."""
    return next(
        (token for token in doc[root.i + 1 :] if token.text.lower() in _BAND_MARKERS),
        None,
    )


def _passive_match(
    doc: Doc, *, kind: str, shape: str, participles: frozenset[str]
) -> ShapeMatch | None:
    """Match a present passive rooted in one kind's allow-list."""
    root = _root(doc)
    if root is None or root.pos_ != "VERB" or root.lemma_.lower() not in participles:
        return None
    auxiliary = _auxpass_child(root)
    if auxiliary is None or auxiliary.tag_ not in _PRESENT_TAGS or _modal(doc):
        return None
    return ShapeMatch(kind, shape, f"{auxiliary.text} {root.text}")


def _capability_modal(doc: Doc, text: str) -> ShapeMatch | None:
    """Match modal and able-to capability phrasing."""
    modal = _modal(doc)
    # A negated modal ("cannot", "may not") states a prohibition, which is rule
    # territory; spaCy tags the modal itself as an ordinary capability modal.
    if modal is not None and _is_negated(modal):
        return None
    if modal is not None:
        return ShapeMatch("capability", "capability-modal", modal.text)
    if _ABLE_TO_RE.search(text) and not _has_negation(doc):
        return ShapeMatch("capability", "capability-modal", "able to")
    return None


def _event_passive(doc: Doc, text: str) -> ShapeMatch | None:
    """Match an occurrence-shaped present passive."""
    return _passive_match(
        doc, kind="event", shape="event-passive", participles=EVENT_PARTICIPLES
    )


def _event_active(doc: Doc, text: str) -> ShapeMatch | None:
    """Match an occurrence-shaped active present verb."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "VERB"
        or root.tag_ not in _PRESENT_TAGS
        or _auxpass_child(root) is not None
        or _modal(doc) is not None
        or root.lemma_.lower() not in EVENT_VERBS
    ):
        return None
    return ShapeMatch("event", "event-active", root.text)


def _unconditional_present_copula_root(doc: Doc) -> Token | None:
    """Return the root of an unconditional present copula frame."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "AUX"
        or root.lemma_.lower() != "be"
        or root.tag_ not in _PRESENT_TAGS
        or _modal(doc) is not None
    ):
        return None
    if _band_marker(doc, root) is not None:
        # "is X for/when/if Y" makes the copula a conditional value band, which
        # is rule-shaped; a state holds unconditionally. A marker inside the
        # subject ("the list for a vacancy is empty") conditions nothing.
        return None
    return root


def _ambiguous_event_participle(doc: Doc, text: str) -> ShapeMatch | None:
    """Match an event participle parsed as an adjectival copula complement."""
    root = _unconditional_present_copula_root(doc)
    if root is None:
        return None
    complement = _complement(root)
    if (
        complement is None
        or complement.pos_ != "ADJ"
        or complement.text.lower() not in AMBIGUOUS_EVENT_PARTICIPLES
    ):
        return None
    return ShapeMatch("event", "event-participle-adj", complement.text)


def _state_passive(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a condition-shaped present passive."""
    return _passive_match(
        doc, kind="state", shape="state-passive", participles=STATE_PARTICIPLES
    )


def _state_perfect(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a present-perfect persisting condition."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "VERB"
        or root.tag_ != "VBN"
        or _auxpass_child(root) is not None
        or _modal(doc) is not None
        # Positive evidence only: an unlisted participle ("has approved") is
        # novel event vocabulary, and must flag rather than read as a state.
        or root.lemma_.lower() not in _PERFECT_STATE_LEMMAS
    ):
        return None
    auxiliary = next(
        (
            child
            for child in root.children
            if child.dep_ == "aux"
            and child.lemma_.lower() == "have"
            and child.tag_ in _PRESENT_TAGS
        ),
        None,
    )
    if auxiliary is None:
        return None
    # "The administrator has enabled result sharing" takes an object: that is a
    # completed action, not a condition the subject is now in.
    if any(child.dep_ in _OBJECT_DEPS for child in root.children):
        return None
    return ShapeMatch("state", "state-perfect", f"{auxiliary.text} {root.text}")


def _state_copula_condition(doc: Doc, text: str) -> ShapeMatch | None:
    """Match adjective, determined noun, or prepositional conditions."""
    root = _unconditional_present_copula_root(doc)
    if root is None:
        return None
    complement = _complement(root)
    if (
        complement is not None
        and complement.pos_ == "ADJ"
        and complement.lemma_.lower() not in LEVEL_LEMMAS
        and complement.lemma_.lower() not in _PERIPHRASTIC_MODAL_ADJECTIVES
    ):
        return ShapeMatch(
            "state", "state-copula-condition", f"{root.text} {complement.text}"
        )
    if (
        complement is not None
        and complement.pos_ == "NOUN"
        and any(child.dep_ == "det" for child in complement.children)
    ):
        return ShapeMatch(
            "state", "state-copula-condition", f"{root.text} {complement.text}"
        )
    if complement is None:
        preposition = next(
            (child for child in root.children if child.dep_ == "prep"), None
        )
        if preposition is not None:
            return ShapeMatch(
                "state",
                "state-copula-condition",
                f"{root.text} {preposition.text}",
            )
    return None


def _state_possession(doc: Doc, text: str) -> ShapeMatch | None:
    """Match present-tense possession."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "VERB"
        or root.lemma_.lower() != "have"
        or root.tag_ not in _PRESENT_TAGS
        or any(child.dep_ == "xcomp" for child in root.children)
        or _modal(doc) is not None
    ):
        return None
    return ShapeMatch("state", "state-possession", root.text)


def _state_stative_verb(doc: Doc, text: str) -> ShapeMatch | None:
    """Match an allow-listed active stative verb."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "VERB"
        or root.tag_ not in _PRESENT_TAGS
        or _auxpass_child(root) is not None
        or _modal(doc) is not None
        or root.lemma_.lower() not in STATE_VERBS
    ):
        return None
    return ShapeMatch("state", "state-stative-verb", root.text)


def _state_negated_np(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a negated or absence-shaped noun phrase."""
    if any(token.pos_ in {"VERB", "AUX"} for token in doc):
        return None
    first = doc[0]
    if first.text.lower() not in NEGATED_NP_OPENERS:
        return None
    return ShapeMatch("state", "state-negated-np", first.text)


def _rule_passive(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a definition-shaped present passive."""
    return _passive_match(
        doc, kind="rule", shape="rule-passive", participles=RULE_PARTICIPLES
    )


def _rule_formula(doc: Doc, text: str) -> ShapeMatch | None:
    """Match active formula verbs or literal formula phrases."""
    root = _root(doc)
    if (
        root is not None
        and root.pos_ == "VERB"
        and root.tag_ in _PRESENT_TAGS
        and _auxpass_child(root) is None
        and _modal(doc) is None
        and root.lemma_.lower() in RULE_VERBS
    ):
        return ShapeMatch("rule", "rule-formula", root.text)
    match = _RULE_FORMULA_RE.search(text)
    if match is not None:
        return ShapeMatch("rule", "rule-formula", match.group(0))
    return None


def _rule_band(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a named or ordinal value conditioned by a band marker."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "AUX"
        or root.lemma_.lower() != "be"
        or root.tag_ not in _PRESENT_TAGS
        or _modal(doc) is not None
    ):
        return None
    complement = _complement(root)
    marker = _band_marker(doc, root)
    if complement is None or marker is None:
        return None
    value_shaped = (
        complement.lemma_.lower() in LEVEL_LEMMAS
        or complement.pos_ == "PROPN"
        or (
            complement.i != 0
            and complement.text.startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        )
    )
    if not value_shaped:
        return None
    return ShapeMatch("rule", "rule-band", f"{complement.text} {marker.text}")


def _rule_measure(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a copular numeric measure."""
    root = _root(doc)
    if (
        root is None
        or root.pos_ != "AUX"
        or root.lemma_.lower() != "be"
        or root.tag_ not in _PRESENT_TAGS
        or _modal(doc) is not None
    ):
        return None
    complement = _complement(root)
    if complement is None or not (
        complement.pos_ == "NUM"
        or any(child.pos_ == "NUM" for child in complement.children)
    ):
        return None
    return ShapeMatch("rule", "rule-measure", f"{root.text} {complement.text}")


def _property_noun_phrase(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a short bare noun phrase."""
    root = _root(doc)
    first = doc[0]
    if (
        any(token.pos_ in {"VERB", "AUX"} for token in doc)
        or len(doc) > 6
        or root is None
        or root.pos_ not in {"NOUN", "PROPN"}
        or first.pos_ == "DET"
        or first.text.lower() in _DETERMINERS
        or first.text.lower() in NEGATED_NP_OPENERS
    ):
        return None
    return ShapeMatch("property", "property-noun-phrase", root.text)


def _imperative_guard(doc: Doc) -> tuple[Token, Token] | None:
    """Return the first token and root for a subjectless base-form command."""
    first = doc[0]
    root = _root(doc)
    if (
        root is None
        or first.tag_ != "VB"
        or first.pos_ not in {"VERB", "AUX"}
        or any(child.dep_ in {"nsubj", "nsubjpass"} for child in root.children)
    ):
        return None
    return first, root


def _action_imperative(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a subjectless UI action command."""
    tokens = _imperative_guard(doc)
    if tokens is None or tokens[0].lemma_.lower() not in UI_ACTION_LEMMAS:
        return None
    return ShapeMatch("action", "action-imperative", tokens[0].text)


def _check_imperative(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a subjectless verification command."""
    tokens = _imperative_guard(doc)
    if tokens is None or tokens[0].lemma_.lower() not in CHECK_LEMMAS:
        return None
    return ShapeMatch("check", "check-imperative", tokens[0].text)


def _procedure_how_to(doc: Doc, text: str) -> ShapeMatch | None:
    """Match a how-to procedure heading."""
    if _HOW_TO_RE.match(text) is None:
        return None
    evidence = " ".join(token.text for token in doc[:2])
    return ShapeMatch("procedure", "procedure-how-to", evidence)


_DETECTORS: tuple[Callable[[Doc, str], ShapeMatch | None], ...] = (
    _capability_modal,
    _event_passive,
    _event_active,
    _ambiguous_event_participle,
    _state_passive,
    _state_perfect,
    _state_copula_condition,
    _state_possession,
    _state_stative_verb,
    _state_negated_np,
    _rule_passive,
    _rule_formula,
    _rule_band,
    _rule_measure,
    _property_noun_phrase,
    _action_imperative,
    _check_imperative,
    _procedure_how_to,
)


def match_shapes(text: str) -> list[ShapeMatch]:
    """Return every positive phrasing shape found in text."""
    stripped = text.strip()
    if not stripped:
        return []
    # A semicolon joins two predicates: a compound remnant the segmenter should
    # have split. Classifying half of one would assign a kind to neither half.
    if ";" in stripped:
        return []

    # Do not normalize: original capitalization distinguishes imperatives and values.
    doc = phrasing.get_nlp()(stripped)
    root = _root(doc)
    # Every detector reads the root, so a second coordinated predicate ("… is
    # sent and … is enabled") would be classified by its first clause alone.
    # That is the same compound the phrasing catalog rejects: flag, don't guess.
    # A how-to heading is exempt — it names one procedure however many verbs
    # its title mentions.
    if (
        root is not None
        and _coordinated_predicate(root) is not None
        and _HOW_TO_RE.match(stripped) is None
    ):
        return []
    matches = [detector(doc, stripped) for detector in _DETECTORS]
    return [match for match in matches if match is not None]


def classify(text: str) -> Classification:
    """Assign a kind only when all matching shapes agree."""
    matches = tuple(match_shapes(text))
    kinds = {match.kind for match in matches}
    if len(kinds) == 1:
        return Classification(next(iter(kinds)), "assigned", matches)
    if kinds:
        return Classification(None, "ambiguous", matches)
    return Classification(None, "unmatched", ())
