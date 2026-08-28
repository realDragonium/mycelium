"""Lexical link patterns shared by auto-linking and offline evaluation.

Unknown statement kinds deliberately receive only the common pattern catalog. Forward
aliases belong to a link type and ride every shipped cue slot of that type, so an alias
registered for one frame can fire in another. This cross-frame reach is the accepted
cost of typing aliases rather than patterns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

PhraseRole = Literal["from", "to"]


@dataclass(frozen=True)
class Pattern:
    """Describe one stable lexical cue for a proposed link type.

    Each frame names its geometry in the regex itself: the captured phrase
    group is called `to` or `from` after the edge slot it fills, and the
    statement carrying the cue takes the other slot. "X contains Y" captures
    Y as `to`; "X is a part of Y" captures Y as `from`. The words decide the
    direction, not which statement happens to be new.
    """

    name: str
    link_type: str
    regex: re.Pattern[str]
    template: str | None = None
    default_cues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Both factories funnel through here, so a template with a stale or
        # typo'd group name fails at import instead of silently never firing.
        groups = self.regex.groupindex
        if "cue" not in groups or ("from" in groups) == ("to" in groups):
            raise ValueError(
                f"pattern {self.name} must capture `cue` and one of from/to"
            )

    @property
    def phrase_role(self) -> PhraseRole:
        """The edge slot the captured phrase fills: "from" or "to"."""
        return "from" if "from" in self.regex.groupindex else "to"


@dataclass(frozen=True)
class CueMatch:
    """Describe one pattern match and its source-text offsets.

    `phrase_role` names the edge slot the captured phrase fills; the cue
    carrier fills the other one.
    """

    pattern: str
    link_type: str
    cue: str
    phrase: str | None
    start: int
    end: int
    phrase_role: PhraseRole = "to"
    cue_span: tuple[int, int] | None = None
    phrase_span: tuple[int, int] | None = None


def _pattern(name: str, link_type: str, regex: str) -> Pattern:
    """Compile one case-insensitive pattern definition."""
    return Pattern(name, link_type, re.compile(regex, re.IGNORECASE))


def _alternation(cues: tuple[str, ...]) -> str:
    """Build a deterministic escaped alternation with longer cues first."""
    ordered = sorted(set(cues), key=lambda cue: (-len(cue), cue))
    return "(?:" + "|".join(re.escape(cue) for cue in ordered) + ")"


def _templated(
    name: str, link_type: str, template: str, cues: tuple[str, ...]
) -> Pattern:
    """Compile and retain one alias-aware pattern definition."""
    regex = re.compile(template.format(cue=_alternation(cues)), re.IGNORECASE)
    return Pattern(name, link_type, regex, template, cues)


_TEMPLATED_REGEXES: dict[tuple[str, tuple[str, ...]], re.Pattern[str]] = {}


COMMON_PATTERNS: tuple[Pattern, ...] = (
    _pattern("requires-verb", "requires", r"\b(?P<cue>requires?)\b\s*(?P<to>.+)"),
    # "A is required for B" names the relation from the far side: B requires
    # A, so the captured phrase is the edge's source.
    _pattern(
        "requires-required",
        "requires",
        r"\b(?P<cue>(?:is|are) required (?:for|to|by))\b\s*(?P<from>.+)",
    ),
    _pattern("requires-needs", "requires", r"\b(?P<cue>needs?)\b\s*(?P<to>.+)"),
    _pattern(
        "requires-must-have",
        "requires",
        r"\b(?P<cue>must have)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "requires-only-when",
        "requires",
        r"\b(?P<cue>only (?:when|if|while|once))\b\s*(?P<to>.+)",
    ),
    _pattern("accepts-verb", "accepts", r"\b(?P<cue>accepts?)\b\s*(?P<to>.+)"),
    _pattern(
        "accepts-optional",
        "accepts",
        r"\b(?P<cue>optional(?:ly)?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "accepts-may-provide",
        "accepts",
        r"\b(?P<cue>(?:may|can) (?:include|specify|provide|supply|be given))\b\s*(?P<to>.+)",
    ),
    _pattern(
        "configures-verb",
        "configures",
        r"\b(?P<cue>configures?)\b\s*(?P<to>.+)",
    ),
    _templated(
        "configures-configured-on",
        "configures",
        r"\b(?P<cue>(?:is|are|can be) {cue} (?:on|for|via|in|per|at))\b\s*(?P<to>.+)",
        ("configured",),
    ),
    _pattern(
        "configures-parameterises",
        "configures",
        r"\b(?P<cue>parameteri[sz]es?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "restricts-verb",
        "restricts",
        r"\b(?P<cue>restricts?)\b\s*(?P<to>.+)",
    ),
    _templated(
        "restricts-limits",
        "restricts",
        r"\b(?P<cue>{cue})\b\s*(?P<to>.+)",
        ("limit", "limits"),
    ),
    _pattern(
        "restricts-limited-to",
        "restricts",
        r"\b(?P<cue>(?:is|are) (?:limited|capped|bounded) (?:to|at|between))\b\s*(?P<to>.+)",
    ),
    # The passive agent is the restrictor, so it fills the `from` slot.
    _pattern(
        "restricts-limited-by",
        "restricts",
        r"\b(?P<cue>(?:is|are) (?:limited|capped|bounded) by)\b\s*(?P<from>.+)",
    ),
    _pattern(
        "restricts-blocks",
        "restricts",
        r"\b(?P<cue>blocks?|prevents?|disables?|suppresses?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "enables-verb",
        "enables",
        r"\b(?P<cue>enables?|unlocks?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "enables-allows",
        "enables",
        r"\b(?P<cue>allows?|permits?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "enables-makes-available",
        "enables",
        r"\b(?P<cue>makes?)\b\s*(?P<to>.+?)\s+available\b",
    ),
    _pattern(
        "triggers-verb",
        "triggers",
        r"\b(?P<cue>triggers?|fires?|kicks? off|initiates?|starts?|launches?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "triggers-causes",
        "triggers",
        r"\b(?P<cue>causes?|results? in|leads? to)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "triggers-queues",
        "triggers",
        r"\b(?P<cue>queues?|schedules?|dispatches?|enqueues?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "establishes-verb",
        "establishes",
        r"\b(?P<cue>establishes?)\b\s*(?P<to>.+)",
    ),
    # The first standalone delimiter wins; attachment ambiguity is unresolved,
    # so this frame stays unshipped until measured.
    _pattern(
        "establishes-marks",
        "establishes",
        r"\b(?P<cue>marks?|flags?)\b\s+.+?\s+\bas\b\s*(?P<to>.+)",
    ),
    # The first standalone delimiter wins; attachment ambiguity is unresolved,
    # so this frame stays unshipped until measured.
    _pattern(
        "establishes-moves-into",
        "establishes",
        r"\b(?P<cue>moves?|puts?|places?)\b\s+.+?\s+\b(?:in|into|to)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "establishes-becomes",
        "establishes",
        r"\b(?P<cue>becomes?|transitions? to|is set to|are set to)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "contains-verb",
        "contains",
        r"\b(?P<cue>contains?|includes?|comprises?|involves?|encompasses?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "contains-composed-of",
        "contains",
        r"\b(?P<cue>(?:is|are) (?:composed|made up) of)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "contains-consists-of",
        "contains",
        r"\b(?P<cue>consists? of)\b\s*(?P<to>.+)",
    ),
    # The captured phrase is the container, so it fills the `from` slot and
    # the cue carrier is contained.
    _pattern(
        "contains-part-of",
        "contains",
        r"\b(?P<cue>(?:is|are) (?:a )?part of)\b\s*(?P<from>.+)",
    ),
    # The captured phrase is the owner/container, so it fills the `from` slot.
    _pattern(
        "contains-belongs-to",
        "contains",
        r"\b(?P<cue>belongs? to|(?:is|are) owned by)\b\s*(?P<from>.+)",
    ),
    _pattern(
        "proceeds-verb",
        "proceeds",
        r"\b(?P<cue>proceeds? to|advances? to|continues? (?:to|with)|moves? on to|hands? off to)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "proceeds-followed-by",
        "proceeds",
        r"\b(?P<cue>(?:is|are) followed by)\b\s*(?P<to>.+)",
    ),
    _templated(
        "proceeds-redirected",
        "proceeds",
        r"\b(?P<cue>(?:is|are) {cue} (?:to|through))\b\s*(?P<to>.+)",
        ("redirected", "routed", "forwarded", "returned"),
    ),
    _pattern(
        "replaces-verb",
        "replaces",
        r"\b(?P<cue>replaces?|overrides?|takes? precedence over|wins over)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "replaces-instead-of",
        "replaces",
        r"\b(?P<cue>instead of|in place of)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "supersedes-verb",
        "supersedes",
        r"\b(?P<cue>supersedes?|deprecates?)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "governed-by-phrase",
        "governed-by",
        r"\b(?P<cue>(?:is|are) governed by|according to|subject to|as defined by|per the)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "varies-by-verb",
        "varies-by",
        r"\b(?P<cue>varies (?:by|with|per|across))\b\s*(?P<to>.+)",
    ),
    _pattern(
        "varies-by-depends",
        "varies-by",
        r"\b(?P<cue>depends? on|depending on|based on)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "fallback-to-verb",
        "fallback-to",
        r"\b(?P<cue>falls? back to|fallback to|otherwise)\b\s*(?P<to>.+)",
    ),
    _pattern(
        "fallback-to-none-apply",
        "fallback-to",
        r"\b(?P<cue>(?:if|when) (?:none|no other|nothing) .{0,40}?(?:appl\w*|match\w*))\b\s*(?P<to>.+)",
    ),
)


KIND_PATTERNS: dict[str, tuple[Pattern, ...]] = {
    "event": (
        _pattern(
            "requires-on-condition",
            "requires",
            r"\b(?P<cue>(?:is|are) (?:rejected|skipped|blocked|refused|denied|ignored) (?:on|for|due to|because of))\b\s*(?P<to>.+)",
        ),
        _pattern(
            "triggers-produces",
            "triggers",
            r"\b(?P<cue>produces?|generates?|emits?|creates?)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "triggers-notifies",
            "triggers",
            r"\b(?P<cue>notifies|notify|alerts?)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "proceeds-then",
            "proceeds",
            r"\b(?P<cue>then|and then|afterwards|next)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "establishes-event-state",
            "establishes",
            r"\b(?P<cue>(?:is|are) marked as|(?:is|are) marked)\b\s*(?P<to>.+)",
        ),
    ),
    "state": (
        _pattern(
            "valued-by-state",
            "valued-by",
            r"\b(?P<cue>(?:is|are) (?:derived|computed|calculated) (?:from|by|as))\b\s*(?P<to>.+)",
        ),
        # Commit a boundary-valid alias so it cannot be retried around the `by` guard.
        _templated(
            "restricts-state",
            "restricts",
            r"\b(?P<cue>(?:is|are) (?>{cue}\b))(?!\s+by\b)\s*(?P<to>.+)?",
            ("disabled", "locked", "frozen", "suspended", "read-only"),
        ),
        # The passive agent is the restrictor, so it fills the `from` slot.
        _templated(
            "restricts-state-by",
            "restricts",
            r"\b(?P<cue>(?:is|are) {cue} by)\b\s*(?P<from>.+)",
            ("disabled", "locked", "frozen", "suspended", "read-only"),
        ),
        _pattern(
            "enables-state",
            "enables",
            r"\b(?P<cue>(?:is|are) (?:enabled|active|unlocked|available))\b(?!\s+by\b)\s*(?P<to>.+)?",
        ),
        # "active by" and "available by" do not name passive agents.
        _pattern(
            "enables-state-by",
            "enables",
            r"\b(?P<cue>(?:is|are) (?:enabled|unlocked) by)\b\s*(?P<from>.+)",
        ),
    ),
    "capability": (
        _pattern(
            "governed-by-capability",
            "governed-by",
            r"\b(?P<cue>according to|as defined by|following the|under the)\b\s*(?P<to>.+)",
        ),
        _templated(
            "configures-capability",
            "configures",
            r"\b(?P<cue>can be {cue} (?:on|for|via|per|at|in))\b\s*(?P<to>.+)",
            ("configured", "set", "adjusted", "customised", "customized", "toggled"),
        ),
        _pattern(
            "varies-by-capability",
            "varies-by",
            r"\b(?P<cue>per|for each|by)\b\s*(?P<to>(?:company|user|locale|language|role|participant|selection flow|job profile)\b.*)",
        ),
        _pattern(
            "requires-capability",
            "requires",
            r"\b(?P<cue>only (?:for|by|when|if|with))\b\s*(?P<to>.+)",
        ),
        _pattern(
            "restricts-capability",
            "restricts",
            r"\b(?P<cue>cannot|can not|can no longer|is not allowed to|are not allowed to)\b\s*(?P<to>.+)",
        ),
    ),
    "rule": (
        _templated(
            "composes-formula",
            "composes",
            r"\b(?P<cue>{cue})\b\s*(?P<to>.+)",
            (
                "equal",
                "equals",
                "plus",
                "minus",
                "multiplied by",
                "divided by",
                "times",
                "sum of",
                "product of",
                "difference of",
                "difference between",
            ),
        ),
        _pattern(
            "composes-determined-by",
            "composes",
            r"\b(?P<cue>(?:is|are) determined by)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "composes-combines",
            "composes",
            r"\b(?P<cue>combines?|aggregates?|weights?)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "valued-by-derived",
            "valued-by",
            r"\b(?P<cue>(?:is|are) (?:derived|computed|calculated|obtained) (?:from|as|by))\b\s*(?P<to>.+)",
        ),
        _pattern(
            "valued-by-determined",
            "valued-by",
            r"\b(?P<cue>(?:is|are) determined by)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "valued-by-equals",
            "valued-by",
            r"\b(?P<cue>equals?)\b\s*(?P<to>.+)",
        ),
        # "A is one of B": the enumerating parent B is the edge's source.
        _pattern(
            "cases-one-of",
            "cases",
            r"\b(?P<cue>(?:is|are) one of|one of:)\s*(?P<from>.+)",
        ),
        # "A is either X or Y": the carrier enumerates its own values.
        _pattern(
            "cases-either",
            "cases",
            r"\b(?P<cue>(?:is|are) (?:either|any of))\b\s*(?P<to>.+)",
        ),
        _pattern(
            "cases-level-for",
            "cases",
            r"\b(?P<cue>(?:is|are) (?:low|medium|high|extra high|none|positive|negative) (?:for|when|if))\b\s*(?P<to>.+)",
        ),
        _pattern(
            "cases-enumeration",
            "cases",
            r"\b(?P<cue>has (?:\d+|two|three|four|five|six) (?:levels|values|types|modes|kinds|options|branches))\b\s*(?P<to>.+)",
        ),
        _pattern(
            "fallback-to-defaults",
            "fallback-to",
            r"\b(?P<cue>defaults? to)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "restricts-bounds",
            "restricts",
            r"\b(?P<cue>at most|at least|no more than|no fewer than|(?:is|are) bounded between|(?:is|are) capped at)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "requires-applies-when",
            "requires",
            r"\b(?P<cue>applies (?:only )?(?:when|if|to))\b\s*(?P<to>.+)",
        ),
    ),
    "property": (),
    "procedure": (
        _pattern(
            "teaches-how-to",
            "teaches",
            r"\b(?P<cue>how to)\b\s*(?P<to>.+)",
        ),
    ),
    "action": (
        _pattern(
            "performs-verb",
            "performs",
            r"^(?P<cue>click|open|select|enter|type|submit|send|navigate to|go to|press|choose|save|upload|delete|remove|add|create|enable|disable|toggle)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "resolves-fix",
            "resolves",
            r"\b(?P<cue>to (?:fix|resolve|clear|recover from))\b\s*(?P<to>.+)",
        ),
    ),
    "check": (
        _pattern(
            "verifies-verb",
            "verifies",
            r"^(?P<cue>verify|check|confirm|inspect|ensure|make sure|look (?:at|for)|compare)\b\s*(?P<to>.+)",
        ),
        _pattern(
            "confirms-if",
            "confirms",
            r"\b(?P<cue>indicates?|means?|shows? that)\b\s*(?P<to>.+)",
        ),
    ),
    "cause": (
        _pattern(
            "violates-missing",
            "violates",
            r"\b(?P<cue>(?:is|are) (?:missing|not set|absent|unset|not configured|expired|invalid|revoked))\b\s*(?P<to>.+)?",
        ),
    ),
}


def patterns_for(kind: str) -> tuple[Pattern, ...]:
    """Return common patterns plus the kind's own patterns."""
    return COMMON_PATTERNS + KIND_PATTERNS.get(kind, ())


def _regex_for(
    pattern: Pattern, aliases: Mapping[str, Sequence[str]] | None
) -> re.Pattern[str]:
    """Resolve a pattern's regex against the supplied alias vocabulary.

    A pattern with no template, or a link type the caller supplied no aliases
    for, keeps its packaged default cues.
    """
    if pattern.template is None or aliases is None:
        return pattern.regex
    cues = aliases.get(pattern.link_type)
    if not cues:
        return pattern.regex
    key = (pattern.name, tuple(cues))
    # Compiling per call would pay the regex compiler once per statement.
    if key not in _TEMPLATED_REGEXES:
        _TEMPLATED_REGEXES[key] = re.compile(
            pattern.template.format(cue=_alternation(key[1])), re.IGNORECASE
        )
    return _TEMPLATED_REGEXES[key]


def find_cues(
    text: str,
    kind: str,
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> list[CueMatch]:
    """Find every applicable cue in text in stable source order."""
    cues: list[CueMatch] = []
    for pattern in patterns_for(kind):
        for match in _regex_for(pattern, aliases).finditer(text):
            groups = match.groupdict()
            cue = groups.get("cue") or match.group(0)
            captured = (
                groups.get("from")
                if pattern.phrase_role == "from"
                else groups.get("to")
            )
            role = pattern.phrase_role
            phrase = captured.strip() if captured and captured.strip() else None
            cues.append(
                CueMatch(
                    pattern=pattern.name,
                    link_type=pattern.link_type,
                    cue=cue,
                    phrase=phrase,
                    start=match.start(),
                    end=match.end(),
                    phrase_role=role,
                    cue_span=match.span("cue"),
                    phrase_span=match.span(role) if phrase is not None else None,
                )
            )
    return sorted(cues, key=lambda cue: (cue.start, cue.pattern))


def all_patterns() -> tuple[Pattern, ...]:
    """Return every distinct pattern in stable registry order."""
    distinct: list[Pattern] = []
    seen: set[str] = set()
    for pattern in COMMON_PATTERNS + tuple(
        pattern for patterns in KIND_PATTERNS.values() for pattern in patterns
    ):
        if pattern.name not in seen:
            seen.add(pattern.name)
            distinct.append(pattern)
    return tuple(distinct)
