"""Phrasing validation for statement text.

Catches authoring anti-patterns at the substrate boundary, dispatched
by the statement's `kind`. Each statement runs through a common
catalog plus a per-kind catalog.

Common (every kind):
  - compound              — two predicates joined into one statement
                            (semicolons, "and" between two VERB clauses)
  - precondition_in_text  — subordinating conjunctions ("when / before /
                            after / while / if / because") that signal a
                            precondition leaking into the text — these
                            belong on the link as a `when` expression
  - universal_claim       — quantifiers ("every / all / each / any",
                            "everyone / nobody / ...") describe a
                            population, not one instance
  - hedge                 — "usually / often / mostly / typically /
                            sometimes / generally / occasionally /
                            frequently / rarely / in most cases"
  - hidden_event_state    — "is set to / becomes / transitions to /
                            gets marked as" conceals an event + state
                            pair and should be split into two
                            statements

Event-only:
  - rule_shaped           — obligation/recommendation modals ("must",
                            "should", "shall", "ought"), prohibition
                            adverbs ("never", "always"), periphrastic
                            modals ("needs to", "has to"), copula-rule
                            constructs ("is required to")
  - sequencing            — "will" usually names a follow-up event that
                            belongs as its own statement + link
  - property_shaped       — "is a / has a / consists of / belongs to" —
                            structural relationships, not events

State-only:
  - rule_shaped           — modals describe rules, not the state
  - sequencing            — "will" describes a future event, not a
                            condition holding now
  - capability_in_state   — "can / may / could / might / is able to"
                            indicates a capability claim, not a state

Capability-only:
  - rule_shaped           — must/should describe obligations, not
                            capabilities
  - sequencing            — "will" describes a future event

Open kinds (anything outside event/state/capability) run the event
catalog as the default — same posture as link types, where unknown
kinds get the generic baseline.

Detection mixes grammatical analysis (spaCy) for structural categories
and literal regex passes for hedges and the hidden_event_state phrases.
All matching runs against a normalized form of the input — case-folded,
NFKC, with curly quotes / dash variants / non-breaking spaces folded
to ASCII equivalents — so callers can't slip past with fancy unicode.
Reported `position` and `matched_text` are mapped back to the original
text via a per-character position map.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from spacy.language import Language
    from spacy.tokens import Doc, Token


# ─── normalization ──────────────────────────────────────────────────────────

_DASH_CHARS = set("–—―‒−")
_QUOTE_MAP = {"‘": "'", "’": "'", "ʼ": "'", "“": '"', "”": '"'}
_EXTRA_SPACES = set("\xa0   ​　")  # NBSP, NNBSP, figure, thin, ZWSP, ideographic


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Returns (normalized_text, pos_map). pos_map[i] is the index in
    `text` that produced normalized_text[i]. NFKC-decomposed expansions
    (ligatures) and casefold expansions (ß → ss) all point back at the
    same source index. Whitespace runs collapse to a single space."""
    out_chars: list[str] = []
    pos_map: list[int] = []
    prev_was_space = False

    for src_i, ch in enumerate(text):
        for nfkc_ch in unicodedata.normalize("NFKC", ch):
            if nfkc_ch in _DASH_CHARS:
                folded_ch = "-"
            elif nfkc_ch in _QUOTE_MAP:
                folded_ch = _QUOTE_MAP[nfkc_ch]
            elif nfkc_ch in _EXTRA_SPACES or nfkc_ch.isspace():
                folded_ch = " "
            else:
                folded_ch = nfkc_ch

            for cf_ch in folded_ch.casefold():
                if cf_ch == " ":
                    if prev_was_space:
                        continue
                    prev_was_space = True
                else:
                    prev_was_space = False
                out_chars.append(cf_ch)
                pos_map.append(src_i)

    return ("".join(out_chars), pos_map)


def normalize(text: str) -> str:
    """Public wrapper: returns just the normalized form."""
    normalized, _ = _normalize_with_map(text)
    return normalized


# ─── violation type ─────────────────────────────────────────────────────────


class Violation(TypedDict):
    category: str
    matched_text: str
    position: int
    rule: str
    recommendation: str


# ─── lemma sets driving spaCy-based detection ───────────────────────────────

# Modal auxiliaries that express obligation or recommendation — describe a
# rule that holds over a separate underlying statement, not an event itself.
# Excluded on purpose: can/could/may/might/would (capability, possibility,
# permission, hypothetical — these describe the statement itself, not a rule
# attached to one).
_MODAL_LEMMAS = {"must", "should", "shall", "ought"}

# "will" is its own case: it usually points at a follow-up statement rather
# than expressing a rule. Detected separately so the recommendation can
# point at split-and-link instead of upsert_annotation.
_SEQUENCING_MODAL_LEMMAS = {"will"}

# Adverbs of invariance/prohibition
_RULE_ADV_LEMMAS = {"never", "always"}

# Verbs whose "<lemma> to <verb>" form is a periphrastic modal
_PERIPHRASTIC_LEMMAS = {"need", "have"}

# Verbs whose passive "is/are <lemma>d to <verb>" form is rule-like
_COPULA_RULE_LEMMAS = {
    "require",
    "allow",
    "permit",
    "prohibit",
    "forbid",
    "oblige",
    "obligate",
}

# Verbs that describe structural relationships, not events
_PROPERTY_VERB_LEMMAS = {"consist", "belong", "comprise"}

# Modals that express capability/possibility/permission. Rejected when
# the statement is being framed as a state — capability text belongs in
# kind='capability', not kind='state'. Not flagged for events because
# events shouldn't carry these either, but the existing event catalog
# already catches the rule-modals (must/should), and "can/may" in event
# text is rare enough that the false-positive cost of flagging it
# outweighs the precision gain.
_CAPABILITY_MODAL_LEMMAS = {"can", "could", "may", "might"}

# Subordinating conjunctions that signal a precondition leaking into text
_PRECONDITION_SCONJ = {
    "when",
    "before",
    "after",
    "while",
    "until",
    "since",
    "if",
    "unless",
    "because",
    "though",
}

# Universal quantifiers — describe a population, not an instance event.
# Note: "no" is intentionally excluded — it routinely appears in legitimate
# atomic-event phrasing ("no flow is specified", "no email is provided")
# where the surrounding sentence is still describing one instance, not a
# universal claim. Pronoun forms ("no one", "nobody", "none") remain
# rejected because they always denote a population.
_UNIVERSAL_DET_LEMMAS = {"every", "all", "each", "any"}
_UNIVERSAL_PRON_LEMMAS = {
    "everyone",
    "everybody",
    "anyone",
    "anybody",
    "no one",
    "nobody",
    "none",
}


# ─── hedges (regex on normalized text) ──────────────────────────────────────

_HEDGE_WORDS = [
    "usually",
    "often",
    "mostly",
    "typically",
    "sometimes",
    "generally",
    "occasionally",
    "frequently",
    "rarely",
]
_HEDGE_RE = re.compile(r"\b(" + "|".join(_HEDGE_WORDS) + r")\b")
_HEDGE_PHRASE_RE = re.compile(r"\bin\s+most\s+cases\b")

# High-precision phrase markers for compound events. spaCy's clause-level
# detection misses these because the parser often mistags the head when
# the construction starts mid-clause; literal phrases catch the long tail.
_COMPOUND_PHRASES = [
    (re.compile(r"\band\s+then\b"), '"and then" joins two events into one statement'),
    (
        re.compile(r"\band\s+also\b"),
        '"and also" joins multiple actions into one statement',
    ),
    (re.compile(r",\s+then\b"), '", then" joins sequential events into one statement'),
]

# Phrases that conceal an event + state pair into one statement.
# "is set to <X>" — set is the event, status=X is the state.
# "becomes <X>" — same shape.
# "transitions to <X>" — same.
# "gets marked as <X>" — same.
_HIDDEN_EVENT_STATE_PHRASES = [
    (
        re.compile(r"\bis\s+set\s+to\b"),
        '"is set to" hides the underlying event (something set the value) and the resulting state (the value now equals X)',
    ),
    (
        re.compile(r"\bare\s+set\s+to\b"),
        '"are set to" hides the underlying event (something set the value) and the resulting state (the value now equals X)',
    ),
    (
        re.compile(r"\bbecomes?\b"),
        '"become(s)" hides the underlying event (the transition) and the resulting state',
    ),
    (
        re.compile(r"\btransitions?\s+to\b"),
        '"transition(s) to" hides the underlying event (the transition) and the resulting state',
    ),
    (
        re.compile(r"\bgets?\s+marked\s+as\b"),
        '"gets marked as" hides the underlying event (the marking) and the resulting state',
    ),
]


# ─── lazy-loaded spaCy ──────────────────────────────────────────────────────

_MODEL_NAME = "en_core_web_sm"
_nlp: "Language | None" = None


def _get_nlp() -> "Language":
    global _nlp
    if _nlp is None:
        try:
            import spacy
        except ImportError as exc:
            raise RuntimeError(
                "spaCy is required for phrasing validation. Add `spacy` to "
                "the project dependencies."
            ) from exc
        try:
            _nlp = spacy.load(_MODEL_NAME)
        except OSError as exc:
            raise RuntimeError(
                f"spaCy model {_MODEL_NAME!r} is not installed. Run: "
                f"`uv run python -m spacy download {_MODEL_NAME}`"
            ) from exc
    return _nlp


# ─── canonical recommendations ──────────────────────────────────────────────
# One per category, used by every pattern in that category. Keeps the
# guidance consistent across detection functions and avoids prescribing
# specific link types — the right link_type depends on the substrate's
# vocabulary, which the caller can inspect via list_link_types.

_REC_COMPOUND = (
    "Split into separate atomic statements and connect them with add_links "
    "(use list_link_types to pick a fitting link_type for the relationship)."
)
_REC_RULE = (
    "Use upsert_annotation with kind='requirement', 'permission', or "
    "'invariant' and attach to the relevant statement or entity."
)
_REC_PROPERTY_BE = (
    "Use upsert_entity (description) or upsert_annotation with kind='property'."
)
_REC_PROPERTY_HAVE = (
    "Use upsert_annotation with kind='property', or model the relationship "
    "via add_entity_links."
)
_REC_PROPERTY_STRUCTURAL = (
    "Model with add_entity_links (use list_entity_link_types to pick a "
    "fitting link_type)."
)
_REC_PRECONDITION = (
    "Split into two statements (the precondition and the action) and connect "
    "them with add_links, setting `when` on the edge to a leaf "
    '({"statement_id": ...}) — or an AND/OR tree if multiple preconditions '
    "compose."
)
_REC_UNIVERSAL = (
    "Rephrase to describe one instance, then attach an upsert_annotation "
    "(kind='invariant' or 'property') for the universal claim — or annotate "
    "the entity directly."
)
_REC_HEDGE = (
    "Rephrase precisely, or split out the precondition into its own statement "
    "and set `when` on the link (a leaf, or an AND/OR tree) to express the "
    "conditioning."
)
_REC_SEQUENCING = (
    'Split into separate atomic statements — the action and what "will" follow — '
    "and connect them with add_links (use list_link_types to pick a fitting "
    "link_type for the relationship)."
)
_REC_HIDDEN_EVENT_STATE = (
    "This phrasing hides an event + state pair. Split into two atomic "
    "statements — one event (kind='event') describing what happened, and "
    "one state (kind='state') describing the resulting condition — and "
    "connect them with add_links (use list_link_types to pick a fitting "
    "link_type, e.g. `establishes`)."
)
_REC_CAPABILITY_IN_STATE = (
    'Modal verbs like "can", "may", "is able to" describe a '
    "capability, not a state. Either rephrase to describe the condition "
    "directly, or use kind='capability' for this statement."
)


# ─── violation construction ─────────────────────────────────────────────────


def _violation(
    *,
    category: str,
    n_start: int,
    n_end: int,
    rule: str,
    recommendation: str,
    original_text: str,
    pos_map: list[int],
) -> Violation:
    """Build a Violation by mapping a normalized [n_start, n_end) span
    back to the original text. Out-of-range indices clamp to the end
    of `original_text`."""
    o_start = pos_map[n_start] if n_start < len(pos_map) else len(original_text)
    o_end = pos_map[n_end - 1] + 1 if 0 < n_end <= len(pos_map) else len(original_text)
    return Violation(
        category=category,
        matched_text=original_text[o_start:o_end],
        position=o_start,
        rule=rule,
        recommendation=recommendation,
    )


def _token_span(tok: "Token") -> tuple[int, int]:
    return (tok.idx, tok.idx + len(tok.text))


def _phrase_span(tokens: list["Token"]) -> tuple[int, int]:
    return (tokens[0].idx, tokens[-1].idx + len(tokens[-1].text))


# ─── per-category detection ─────────────────────────────────────────────────


def _check_modals(doc: "Doc", original: str, pos_map: list[int]) -> list[Violation]:
    """Modal AUX → rule_shaped (obligation/recommendation) or sequencing
    (the "will" case: usually points at a follow-up statement)."""
    out: list[Violation] = []
    for tok in doc:
        if tok.pos_ != "AUX":
            continue
        if tok.lemma_ in _MODAL_LEMMAS:
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="rule_shaped",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text}" is a modal verb describing a rule, not an event',
                    recommendation=_REC_RULE,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
        elif tok.lemma_ in _SEQUENCING_MODAL_LEMMAS:
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="sequencing",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text}" usually names a follow-up statement; that follow-up belongs as its own statement connected by a link',
                    recommendation=_REC_SEQUENCING,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_rule_adverbs(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """ADV "never" / "always" → rule_shaped."""
    out: list[Violation] = []
    for tok in doc:
        if tok.pos_ == "ADV" and tok.lemma_ in _RULE_ADV_LEMMAS:
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="rule_shaped",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text}" describes an invariant or prohibition, not an event',
                    recommendation=_REC_RULE,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_periphrastic_modals(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """need to + verb / have to + verb → rule_shaped.

    Detection: token with lemma in {need, have}, POS=VERB (not AUX —
    excludes perfect-tense uses like "has logged in"), and an xcomp
    child that is itself a verb."""
    out: list[Violation] = []
    for tok in doc:
        if tok.lemma_ not in _PERIPHRASTIC_LEMMAS or tok.pos_ != "VERB":
            continue
        if any(c.dep_ == "xcomp" and c.pos_ == "VERB" for c in tok.children):
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="rule_shaped",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text} to" describes an obligation, not an event',
                    recommendation=_REC_RULE,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_copula_rules(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """is/are required/allowed/prohibited/... to + verb → rule_shaped.

    Detection: VERB token with lemma in COPULA_RULE_LEMMAS, an auxpass
    child (the "is/are/was"), and an xcomp verb child (the "to <verb>")."""
    out: list[Violation] = []
    for tok in doc:
        if tok.lemma_ not in _COPULA_RULE_LEMMAS or tok.pos_ != "VERB":
            continue
        has_auxpass = any(c.dep_ == "auxpass" for c in tok.children)
        has_xcomp = any(c.dep_ == "xcomp" and c.pos_ == "VERB" for c in tok.children)
        if has_auxpass and has_xcomp:
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="rule_shaped",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"is {tok.text} to" describes an obligation or permission, not an event',
                    recommendation=_REC_RULE,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_copula_property(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """is/are/was a/an <noun> → property_shaped (entity description).

    Detection: AUX with lemma=be, attr child whose own children include
    a det with lemma a/an. Excludes passive constructions ("is invalidated"
    has acomp/auxpass, not attr+det)."""
    out: list[Violation] = []
    for tok in doc:
        if tok.lemma_ != "be" or tok.pos_ != "AUX":
            continue
        for attr in tok.children:
            if attr.dep_ != "attr":
                continue
            if any(c.dep_ == "det" and c.lemma_ in ("a", "an") for c in attr.children):
                n_start, n_end = _token_span(tok)
                out.append(
                    _violation(
                        category="property_shaped",
                        n_start=n_start,
                        n_end=n_end,
                        rule='"is a / is an" describes what something IS — an entity description or property annotation',
                        recommendation=_REC_PROPERTY_BE,
                        original_text=original,
                        pos_map=pos_map,
                    )
                )
                break
    return out


def _check_have_property(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """has/have a/an <noun> → property_shaped.

    Detection: VERB lemma=have (not AUX, which excludes "has logged"),
    with a dobj child whose own children include det a/an."""
    out: list[Violation] = []
    for tok in doc:
        if tok.lemma_ != "have" or tok.pos_ != "VERB":
            continue
        for dobj in tok.children:
            if dobj.dep_ != "dobj":
                continue
            if any(c.dep_ == "det" and c.lemma_ in ("a", "an") for c in dobj.children):
                n_start, n_end = _token_span(tok)
                out.append(
                    _violation(
                        category="property_shaped",
                        n_start=n_start,
                        n_end=n_end,
                        rule='"has a / has an" describes a property, not an event',
                        recommendation=_REC_PROPERTY_HAVE,
                        original_text=original,
                        pos_map=pos_map,
                    )
                )
                break
    return out


def _check_structural_verbs(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """consists of / belongs to / comprises → property_shaped."""
    out: list[Violation] = []
    for tok in doc:
        if tok.pos_ == "VERB" and tok.lemma_ in _PROPERTY_VERB_LEMMAS:
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="property_shaped",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text}" describes a structural relationship, not an event',
                    recommendation=_REC_PROPERTY_STRUCTURAL,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_compound_clauses(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """CCONJ "and" joining two VERB heads → compound.

    Detection: CCONJ with head.pos_=VERB and the head has a conj child
    that is also VERB. Conservative: skips coordinated noun lists
    ("apples and oranges") because both heads are NOUN, not VERB."""
    out: list[Violation] = []
    for tok in doc:
        if tok.pos_ != "CCONJ" or tok.lemma_ != "and":
            continue
        head = tok.head
        if head.pos_ != "VERB":
            continue
        if any(c.dep_ == "conj" and c.pos_ == "VERB" for c in head.children):
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="compound",
                    n_start=n_start,
                    n_end=n_end,
                    rule='"and" joining two events makes the statement compound',
                    recommendation=_REC_COMPOUND,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_semicolons(doc: "Doc", original: str, pos_map: list[int]) -> list[Violation]:
    """Any semicolon → compound."""
    out: list[Violation] = []
    for tok in doc:
        if tok.text == ";":
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="compound",
                    n_start=n_start,
                    n_end=n_end,
                    rule="Statements must be atomic — no semicolons joining clauses",
                    recommendation=_REC_COMPOUND,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_precondition_sconj(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """when/before/after/while/until/if/... → precondition_in_text.

    Preconditions belong on the link as `when_statement_id`, not in the
    statement text. spaCy tags some of these as SCONJ (when/while/until/if)
    and others as ADP (before/after) depending on usage; both readings
    signal a precondition in this domain."""
    out: list[Violation] = []
    for tok in doc:
        if tok.lemma_ in _PRECONDITION_SCONJ and tok.pos_ in ("SCONJ", "ADP"):
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="precondition_in_text",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text}" introduces a precondition; preconditions belong on the link as when_statement_id, not in the statement text',
                    recommendation=_REC_PRECONDITION,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


# ─── hedge detection (regex on normalized text) ─────────────────────────────


def _check_universal_quantifier(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """every/all/each/any <noun> or everyone/nobody/... → universal_claim.

    These describe a population or invariant ("every user must verify"),
    not an event for a single instance. The statement should either be
    rephrased to describe one instance ("user verifies email" + an
    invariant annotation that this applies to all users), or modeled as
    an annotation directly on the entity."""
    out: list[Violation] = []
    for tok in doc:
        is_det = tok.pos_ == "DET" and tok.lemma_ in _UNIVERSAL_DET_LEMMAS
        is_pron = tok.pos_ == "PRON" and tok.lemma_ in _UNIVERSAL_PRON_LEMMAS
        if not (is_det or is_pron):
            continue
        n_start, n_end = _token_span(tok)
        out.append(
            _violation(
                category="universal_claim",
                n_start=n_start,
                n_end=n_end,
                rule=f'"{tok.text}" describes a population or invariant, not an event for a single instance',
                recommendation=_REC_UNIVERSAL,
                original_text=original,
                pos_map=pos_map,
            )
        )
    return out


def _check_compound_phrases(
    normalized: str, original: str, pos_map: list[int]
) -> list[Violation]:
    """Literal phrase patterns that always indicate compound events,
    regardless of how spaCy parses the surrounding clause."""
    out: list[Violation] = []
    for pattern, rule in _COMPOUND_PHRASES:
        for match in pattern.finditer(normalized):
            out.append(
                _violation(
                    category="compound",
                    n_start=match.start(),
                    n_end=match.end(),
                    rule=rule,
                    recommendation=_REC_COMPOUND,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_hidden_event_state(
    normalized: str, original: str, pos_map: list[int]
) -> list[Violation]:
    """ "is set to / becomes / transitions to / gets marked as" — these
    phrases conceal an event (the change) and a state (the new value)
    into a single statement. Reject regardless of kind so the writer
    splits them."""
    out: list[Violation] = []
    for pattern, rule in _HIDDEN_EVENT_STATE_PHRASES:
        for match in pattern.finditer(normalized):
            out.append(
                _violation(
                    category="hidden_event_state",
                    n_start=match.start(),
                    n_end=match.end(),
                    rule=rule,
                    recommendation=_REC_HIDDEN_EVENT_STATE,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    return out


def _check_capability_modals_in_state(
    doc: "Doc", original: str, pos_map: list[int]
) -> list[Violation]:
    """can / may / could / might / is able to → capability_in_state.

    Detected when validating a kind='state' statement: capability text
    belongs in kind='capability', not as a state."""
    out: list[Violation] = []
    for tok in doc:
        if tok.pos_ == "AUX" and tok.lemma_ in _CAPABILITY_MODAL_LEMMAS:
            n_start, n_end = _token_span(tok)
            out.append(
                _violation(
                    category="capability_in_state",
                    n_start=n_start,
                    n_end=n_end,
                    rule=f'"{tok.text}" expresses capability or possibility, not a state',
                    recommendation=_REC_CAPABILITY_IN_STATE,
                    original_text=original,
                    pos_map=pos_map,
                )
            )
    # Detect "is able to <verb>" via dependency: ADJ "able" with head
    # being an AUX "be" and an xcomp child verb. spaCy parses
    # "user is able to leave" as: is(AUX, ROOT) → able(ADJ, acomp) →
    # leave(VERB, xcomp).
    for tok in doc:
        if tok.lemma_ == "able" and tok.pos_ == "ADJ":
            head_is_be = tok.head.lemma_ == "be" and tok.head.pos_ == "AUX"
            has_xcomp = any(
                c.dep_ == "xcomp" and c.pos_ == "VERB" for c in tok.children
            )
            if head_is_be and has_xcomp:
                n_start, n_end = _token_span(tok)
                out.append(
                    _violation(
                        category="capability_in_state",
                        n_start=n_start,
                        n_end=n_end,
                        rule='"is able to" expresses capability, not a state',
                        recommendation=_REC_CAPABILITY_IN_STATE,
                        original_text=original,
                        pos_map=pos_map,
                    )
                )
    return out


def _check_hedges(
    normalized: str, original: str, pos_map: list[int]
) -> list[Violation]:
    """Hedges are a literal word list. Regex against normalized text."""
    out: list[Violation] = []
    for match in _HEDGE_RE.finditer(normalized):
        word = match.group(1)
        out.append(
            _violation(
                category="hedge",
                n_start=match.start(),
                n_end=match.end(),
                rule=f'"{word}" hedges the statement; if it is conditional, name the precondition',
                recommendation=_REC_HEDGE,
                original_text=original,
                pos_map=pos_map,
            )
        )
    for match in _HEDGE_PHRASE_RE.finditer(normalized):
        out.append(
            _violation(
                category="hedge",
                n_start=match.start(),
                n_end=match.end(),
                rule='"in most cases" hedges the statement; the conditional shape belongs in the model',
                recommendation=_REC_HEDGE,
                original_text=original,
                pos_map=pos_map,
            )
        )
    return out


# ─── public entry point ─────────────────────────────────────────────────────


def check(text: str, kind: str = "event") -> list[Violation]:
    """Run every check against `text` and return all violations.

    Dispatched by `kind`. The common catalog (compound, hedge,
    precondition_in_text, universal_claim, hidden_event_state) runs
    for every kind. Per-kind catalogs add the structural rules that
    are inappropriate for that kind:

      - event       — full event catalog (rejects rule-shaped,
                      property-shaped, structural verbs, sequencing).
      - state       — rejects rule modals, sequencing, and capability
                      modals (capability text belongs in kind='capability').
                      Allows "is a / has a" — states ARE conditions.
      - capability  — rejects rule modals and sequencing. Allows
                      capability modals (can / may / is able to).

    Open kinds (anything outside the three above) run the event
    catalog as the default — same posture as link types, where
    unknown kinds inherit the generic baseline.

    Multiple checks can fire on the same text — each is reported
    independently so the caller fixes everything in one pass instead
    of resubmitting and hitting the next violation. Results are
    ordered by position. Empty list means clean.
    """
    normalized, pos_map = _normalize_with_map(text)
    if not normalized.strip():
        return []

    nlp = _get_nlp()
    doc = nlp(normalized)

    violations: list[Violation] = []

    # --- Common catalog: every kind runs these ---
    violations.extend(_check_compound_clauses(doc, text, pos_map))
    violations.extend(_check_semicolons(doc, text, pos_map))
    violations.extend(_check_compound_phrases(normalized, text, pos_map))
    violations.extend(_check_precondition_sconj(doc, text, pos_map))
    violations.extend(_check_universal_quantifier(doc, text, pos_map))
    violations.extend(_check_hedges(normalized, text, pos_map))
    violations.extend(_check_hidden_event_state(normalized, text, pos_map))

    # --- Per-kind catalog ---
    if kind == "state":
        # States are conditions holding. Reject rule-shape (must/should),
        # sequencing (will), and capability modals (can/may/is able to).
        # Allow copula property ("is a"), possession ("has a"), structural
        # verbs — those describe states.
        violations.extend(_check_modals(doc, text, pos_map))
        violations.extend(_check_rule_adverbs(doc, text, pos_map))
        violations.extend(_check_periphrastic_modals(doc, text, pos_map))
        violations.extend(_check_copula_rules(doc, text, pos_map))
        violations.extend(_check_capability_modals_in_state(doc, text, pos_map))
    elif kind == "capability":
        # Capabilities are modal claims. Reject obligation modals
        # (must/should), sequencing (will), and structural verbs.
        # Allow capability modals (can/may/could/might) and "is able to".
        violations.extend(_check_modals(doc, text, pos_map))
        violations.extend(_check_rule_adverbs(doc, text, pos_map))
        violations.extend(_check_periphrastic_modals(doc, text, pos_map))
        violations.extend(_check_copula_rules(doc, text, pos_map))
    else:
        # `event` and any open kind: full event catalog.
        violations.extend(_check_modals(doc, text, pos_map))
        violations.extend(_check_rule_adverbs(doc, text, pos_map))
        violations.extend(_check_periphrastic_modals(doc, text, pos_map))
        violations.extend(_check_copula_rules(doc, text, pos_map))
        violations.extend(_check_copula_property(doc, text, pos_map))
        violations.extend(_check_have_property(doc, text, pos_map))
        violations.extend(_check_structural_verbs(doc, text, pos_map))

    violations.sort(key=lambda v: v["position"])
    return violations
