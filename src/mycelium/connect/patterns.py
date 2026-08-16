"""Lexical link patterns shared by auto-linking and offline evaluation.

Unknown statement kinds deliberately receive only the common pattern catalog. Aliases
belong to a link type, so every shipped template of that type accepts all of them; an
alias registered for one frame can therefore fire in another. This cross-frame reach
is the accepted cost of typing aliases rather than patterns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    """Describe one stable lexical cue for a proposed link type."""

    name: str
    link_type: str
    regex: re.Pattern[str]
    template: str | None = None
    default_cues: tuple[str, ...] = ()


@dataclass(frozen=True)
class CueMatch:
    """Describe one pattern match and its source-text offsets."""

    pattern: str
    link_type: str
    cue: str
    target_text: str | None
    start: int
    end: int


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
    _pattern("requires-verb", "requires", r"\b(?P<cue>requires?)\b\s*(?P<target>.+)"),
    _pattern(
        "requires-required",
        "requires",
        r"\b(?P<cue>(?:is|are) required (?:for|to|by))\b\s*(?P<target>.+)",
    ),
    _pattern("requires-needs", "requires", r"\b(?P<cue>needs?)\b\s*(?P<target>.+)"),
    _pattern(
        "requires-must-have",
        "requires",
        r"\b(?P<cue>must have)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "requires-only-when",
        "requires",
        r"\b(?P<cue>only (?:when|if|while|once))\b\s*(?P<target>.+)",
    ),
    _pattern("accepts-verb", "accepts", r"\b(?P<cue>accepts?)\b\s*(?P<target>.+)"),
    _pattern(
        "accepts-optional",
        "accepts",
        r"\b(?P<cue>optional(?:ly)?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "accepts-may-provide",
        "accepts",
        r"\b(?P<cue>(?:may|can) (?:include|specify|provide|supply|be given))\b\s*(?P<target>.+)",
    ),
    _pattern(
        "configures-verb",
        "configures",
        r"\b(?P<cue>configures?)\b\s*(?P<target>.+)",
    ),
    _templated(
        "configures-configured-on",
        "configures",
        r"\b(?P<cue>(?:is|are|can be) {cue} (?:on|for|via|in|per|at))\b\s*(?P<target>.+)",
        ("configured",),
    ),
    _pattern(
        "configures-parameterises",
        "configures",
        r"\b(?P<cue>parameteri[sz]es?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "restricts-verb",
        "restricts",
        r"\b(?P<cue>restricts?)\b\s*(?P<target>.+)",
    ),
    _templated(
        "restricts-limits",
        "restricts",
        r"\b(?P<cue>{cue})\b\s*(?P<target>.+)",
        ("limit", "limits"),
    ),
    _pattern(
        "restricts-limited-to",
        "restricts",
        r"\b(?P<cue>(?:is|are) (?:limited|capped|bounded) (?:to|by|at|between))\b\s*(?P<target>.+)",
    ),
    _pattern(
        "restricts-blocks",
        "restricts",
        r"\b(?P<cue>blocks?|prevents?|disables?|suppresses?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "enables-verb",
        "enables",
        r"\b(?P<cue>enables?|unlocks?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "enables-allows",
        "enables",
        r"\b(?P<cue>allows?|permits?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "enables-makes-available",
        "enables",
        r"\b(?P<cue>makes?)\b\s*(?P<target>.+?)\s+available\b",
    ),
    _pattern(
        "triggers-verb",
        "triggers",
        r"\b(?P<cue>triggers?|fires?|kicks? off|initiates?|starts?|launches?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "triggers-causes",
        "triggers",
        r"\b(?P<cue>causes?|results? in|leads? to)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "triggers-queues",
        "triggers",
        r"\b(?P<cue>queues?|schedules?|dispatches?|enqueues?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "establishes-verb",
        "establishes",
        r"\b(?P<cue>establishes?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "establishes-marks",
        "establishes",
        r"\b(?P<cue>marks?|flags?)\b\s*(?P<target>.+)\s+\bas\b",
    ),
    _pattern(
        "establishes-moves-into",
        "establishes",
        r"\b(?P<cue>moves?|puts?|places?)\b\s*(?P<target>.+)\s+\b(?:in|into|to)\b",
    ),
    _pattern(
        "establishes-becomes",
        "establishes",
        r"\b(?P<cue>becomes?|transitions? to|is set to|are set to)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "contains-verb",
        "contains",
        r"\b(?P<cue>contains?|includes?|comprises?|involves?|encompasses?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "contains-composed-of",
        "contains",
        r"\b(?P<cue>(?:is|are) (?:composed|made up) of)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "contains-consists-of",
        "contains",
        r"\b(?P<cue>consists? of)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "proceeds-verb",
        "proceeds",
        r"\b(?P<cue>proceeds? to|advances? to|continues? (?:to|with)|moves? on to|hands? off to)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "proceeds-followed-by",
        "proceeds",
        r"\b(?P<cue>(?:is|are) followed by)\b\s*(?P<target>.+)",
    ),
    _templated(
        "proceeds-redirected",
        "proceeds",
        r"\b(?P<cue>(?:is|are) {cue} (?:to|through))\b\s*(?P<target>.+)",
        ("redirected", "routed", "forwarded", "returned"),
    ),
    _pattern(
        "replaces-verb",
        "replaces",
        r"\b(?P<cue>replaces?|overrides?|takes? precedence over|wins over)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "replaces-instead-of",
        "replaces",
        r"\b(?P<cue>instead of|in place of)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "supersedes-verb",
        "supersedes",
        r"\b(?P<cue>supersedes?|deprecates?)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "governed-by-phrase",
        "governed-by",
        r"\b(?P<cue>(?:is|are) governed by|according to|subject to|as defined by|per the)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "varies-by-verb",
        "varies-by",
        r"\b(?P<cue>varies (?:by|with|per|across))\b\s*(?P<target>.+)",
    ),
    _pattern(
        "varies-by-depends",
        "varies-by",
        r"\b(?P<cue>depends? on|depending on|based on)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "fallback-to-verb",
        "fallback-to",
        r"\b(?P<cue>falls? back to|fallback to|otherwise)\b\s*(?P<target>.+)",
    ),
    _pattern(
        "fallback-to-none-apply",
        "fallback-to",
        r"\b(?P<cue>(?:if|when) (?:none|no other|nothing) .{0,40}?(?:appl\w*|match\w*))\b\s*(?P<target>.+)",
    ),
)


KIND_PATTERNS: dict[str, tuple[Pattern, ...]] = {
    "event": (
        _pattern(
            "requires-on-condition",
            "requires",
            r"\b(?P<cue>(?:is|are) (?:rejected|skipped|blocked|refused|denied|ignored) (?:on|for|due to|because of))\b\s*(?P<target>.+)",
        ),
        _pattern(
            "triggers-produces",
            "triggers",
            r"\b(?P<cue>produces?|generates?|emits?|creates?)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "triggers-notifies",
            "triggers",
            r"\b(?P<cue>notifies|notify|alerts?)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "proceeds-then",
            "proceeds",
            r"\b(?P<cue>then|and then|afterwards|next)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "establishes-event-state",
            "establishes",
            r"\b(?P<cue>(?:is|are) marked as|(?:is|are) marked)\b\s*(?P<target>.+)",
        ),
    ),
    "state": (
        _pattern(
            "valued-by-state",
            "valued-by",
            r"\b(?P<cue>(?:is|are) (?:derived|computed|calculated) (?:from|by|as))\b\s*(?P<target>.+)",
        ),
        _templated(
            "restricts-state",
            "restricts",
            r"\b(?P<cue>(?:is|are) {cue})\b\s*(?P<target>.+)?",
            ("disabled", "locked", "frozen", "suspended", "read-only"),
        ),
        _pattern(
            "enables-state",
            "enables",
            r"\b(?P<cue>(?:is|are) (?:enabled|active|unlocked|available))\b\s*(?P<target>.+)?",
        ),
    ),
    "capability": (
        _pattern(
            "governed-by-capability",
            "governed-by",
            r"\b(?P<cue>according to|as defined by|following the|under the)\b\s*(?P<target>.+)",
        ),
        _templated(
            "configures-capability",
            "configures",
            r"\b(?P<cue>can be {cue} (?:on|for|via|per|at|in))\b\s*(?P<target>.+)",
            ("configured", "set", "adjusted", "customised", "customized", "toggled"),
        ),
        _pattern(
            "varies-by-capability",
            "varies-by",
            r"\b(?P<cue>per|for each|by)\b\s*(?P<target>(?:company|user|locale|language|role|participant|selection flow|job profile)\b.*)",
        ),
        _pattern(
            "requires-capability",
            "requires",
            r"\b(?P<cue>only (?:for|by|when|if|with))\b\s*(?P<target>.+)",
        ),
        _pattern(
            "restricts-capability",
            "restricts",
            r"\b(?P<cue>cannot|can not|can no longer|is not allowed to|are not allowed to)\b\s*(?P<target>.+)",
        ),
    ),
    "rule": (
        _templated(
            "composes-formula",
            "composes",
            r"\b(?P<cue>{cue})\b\s*(?P<target>.+)",
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
            r"\b(?P<cue>(?:is|are) determined by)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "composes-combines",
            "composes",
            r"\b(?P<cue>combines?|aggregates?|weights?)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "valued-by-derived",
            "valued-by",
            r"\b(?P<cue>(?:is|are) (?:derived|computed|calculated|obtained) (?:from|as|by))\b\s*(?P<target>.+)",
        ),
        _pattern(
            "valued-by-determined",
            "valued-by",
            r"\b(?P<cue>(?:is|are) determined by)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "valued-by-equals",
            "valued-by",
            r"\b(?P<cue>equals?)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "cases-one-of",
            "cases",
            r"\b(?P<cue>(?:is|are) (?:one of|either|any of)|one of:)\s*(?P<target>.+)",
        ),
        _pattern(
            "cases-level-for",
            "cases",
            r"\b(?P<cue>(?:is|are) (?:low|medium|high|extra high|none|positive|negative) (?:for|when|if))\b\s*(?P<target>.+)",
        ),
        _pattern(
            "cases-enumeration",
            "cases",
            r"\b(?P<cue>has (?:\d+|two|three|four|five|six) (?:levels|values|types|modes|kinds|options|branches))\b\s*(?P<target>.+)",
        ),
        _pattern(
            "fallback-to-defaults",
            "fallback-to",
            r"\b(?P<cue>defaults? to)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "restricts-bounds",
            "restricts",
            r"\b(?P<cue>at most|at least|no more than|no fewer than|(?:is|are) bounded (?:between|by)|(?:is|are) capped at)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "requires-applies-when",
            "requires",
            r"\b(?P<cue>applies (?:only )?(?:when|if|to))\b\s*(?P<target>.+)",
        ),
    ),
    "property": (),
    "procedure": (
        _pattern(
            "teaches-how-to",
            "teaches",
            r"\b(?P<cue>how to)\b\s*(?P<target>.+)",
        ),
    ),
    "action": (
        _pattern(
            "performs-verb",
            "performs",
            r"^(?P<cue>click|open|select|enter|type|submit|send|navigate to|go to|press|choose|save|upload|delete|remove|add|create|enable|disable|toggle)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "resolves-fix",
            "resolves",
            r"\b(?P<cue>to (?:fix|resolve|clear|recover from))\b\s*(?P<target>.+)",
        ),
    ),
    "check": (
        _pattern(
            "verifies-verb",
            "verifies",
            r"^(?P<cue>verify|check|confirm|inspect|ensure|make sure|look (?:at|for)|compare)\b\s*(?P<target>.+)",
        ),
        _pattern(
            "confirms-if",
            "confirms",
            r"\b(?P<cue>indicates?|means?|shows? that)\b\s*(?P<target>.+)",
        ),
    ),
    "cause": (
        _pattern(
            "violates-missing",
            "violates",
            r"\b(?P<cue>(?:is|are) (?:missing|not set|absent|unset|not configured|expired|invalid|revoked))\b\s*(?P<target>.+)?",
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
            target = groups.get("target")
            target_text = target.strip() if target and target.strip() else None
            cues.append(
                CueMatch(
                    pattern=pattern.name,
                    link_type=pattern.link_type,
                    cue=cue,
                    target_text=target_text,
                    start=match.start(),
                    end=match.end(),
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
