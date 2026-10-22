"""Lexical cues for phrasing validation."""

from __future__ import annotations

import re

# Coordinating conjunctions that join two clauses into a compound statement.
COORDINATING_CONJUNCTIONS = frozenset({"and"})

# Subordinating conjunctions that signal a precondition leaking into text
PRECONDITION_SCONJ = {
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

HEDGE_WORDS = [
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
HEDGE_RE = re.compile(r"\b(" + "|".join(HEDGE_WORDS) + r")\b")
HEDGE_PHRASE_RE = re.compile(r"\bin\s+most\s+cases\b")

# High-precision phrase markers for compound events. spaCy's clause-level
# detection misses these because the parser often mistags the head when
# the construction starts mid-clause; literal phrases catch the long tail.
COMPOUND_PHRASES = [
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
HIDDEN_EVENT_STATE_PHRASES = [
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
