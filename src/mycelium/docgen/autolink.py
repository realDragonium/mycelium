"""Concept names in a rendered body become links without the writer marking
them.

This works on the HTML the shared renderer made, not on Markdown, so what is
prose is decided once, by the renderer: a name is linked only in text a reader
sees as prose. Text inside code, headings, links, table header cells, flows and
image placeholders is left alone.

Each concept is linked once in the lead and once in each section, at its first
occurrence. A link the writer placed counts as that section's link.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Literal

#: A single-word name this short is matched only as the store capitalises it.
SHORT_NAME = 4

_VOID = frozenset({"br", "hr", "img", "input", "wbr"})
_NOT_PROSE = frozenset(
    {"a", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "th", "figure"}
)
_NOT_PROSE_CLASS = "image-wanted"
_LINK_CLASS = "concept-link"
_STUB_CLASS = "stub"
#: Said inside every link to a page not written yet, for a reader who cannot
#: see its dotted underline. Text extraction skips it by its class.
STUB_NOTE = '<span class="visually-hidden"> (not written yet)</span>'
HIDDEN_CLASS = "visually-hidden"
#: The class attribute of every link in prose to a page not written yet.
STUB_LINK = f'class="{_LINK_CLASS} {_STUB_CLASS}"'


def stub_title(description: str | None) -> str:
    """The tooltip of a link to a page not written yet, unescaped."""
    return f"Not written yet — {description}" if description else "Not written yet"


@dataclass(frozen=True)
class Concept:
    id: str
    #: The names to find in prose. Empty for a concept only the writer links.
    names: tuple[str, ...]
    #: Where its links lead. None for a concept that is never linked, such as
    #: the page's own: its names still claim the text they match, so a shorter
    #: name inside one of them is not linked either.
    href: str | None
    #: Whether `href` is a generated page, not a written one.
    stub: bool = False
    description: str | None = None


@dataclass(frozen=True)
class Linked:
    html: str
    #: The concepts the result links to, automatically or by the writer.
    concept_ids: frozenset[str]


def exact_case(name: str) -> bool:
    """Whether a name is matched only with the capitals it is stored with: a
    single word that is short or all lower case, which is likely to be an
    everyday word as well. Any other name is matched ignoring case."""
    return len(name.split()) == 1 and (len(name) <= SHORT_NAME or name == name.lower())


@dataclass(frozen=True)
class _Matcher:
    pattern: re.Pattern[str]
    concepts: dict[str, Concept]


def _matcher(concepts: Sequence[Concept]) -> _Matcher | None:
    owners: dict[str, tuple[str, Concept] | None] = {}
    for concept in concepts:
        for name in concept.names:
            key = " ".join(name.split()).casefold()
            if not key:
                continue
            known = owners.get(key)
            # A name two concepts share says nothing about which one is meant.
            owners[key] = (
                (name, concept)
                if key not in owners or (known and known[1].id == concept.id)
                else None
            )
    claimed = sorted(
        (item for item in owners.values() if item is not None),
        key=lambda item: (-len(item[0]), item[0]),
    )
    if not claimed:
        return None
    alternatives: list[str] = []
    by_group: dict[str, Concept] = {}
    for number, (name, concept) in enumerate(claimed):
        words = r"\s+".join(re.escape(word) for word in name.split())
        group = f"n{number}"
        by_group[group] = concept
        alternatives.append(
            f"(?P<{group}>{words if exact_case(name) else f'(?i:{words})'})"
        )
    # Longest first, as whole words, with a plural ending on the last word.
    return _Matcher(
        re.compile(rf"(?<!\w)(?:{'|'.join(alternatives)})(?:e?s)?(?!\w)"), by_group
    )


@dataclass
class _Section:
    #: Markup is copied; text is escaped again; prose is searched for names.
    parts: list[tuple[Literal["markup", "text", "prose"], str]] = field(
        default_factory=list
    )
    written: set[str] = field(default_factory=set)


class _Reader(HTMLParser):
    def __init__(self, by_href: dict[str, Concept]) -> None:
        super().__init__(convert_charrefs=True)
        self.sections = [_Section()]
        self._by_href = by_href
        #: Per open element, whether the text inside it is not prose.
        self._open: list[bool] = []
        #: Per open link, whether it leads to a stub and needs `STUB_NOTE`.
        self._links: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "h2" and not self._open:
            self.sections.append(_Section())
        section = self.sections[-1]
        markup = self.get_starttag_text() or ""
        stub = False
        if tag == "a" and _LINK_CLASS in classes:
            concept = self._by_href.get(values.get("href") or "")
            if concept is not None:
                section.written.add(concept.id)
                markup = _open_tag(concept)
                stub = concept.stub
        if tag == "a":
            self._links.append(stub)
        section.parts.append(("markup", markup))
        if tag not in _VOID:
            self._open.append(tag in _NOT_PROSE or _NOT_PROSE_CLASS in classes)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.sections[-1].parts.append(("markup", self.get_starttag_text() or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._links and self._links.pop():
            self.sections[-1].parts.append(("markup", STUB_NOTE))
        self.sections[-1].parts.append(("markup", f"</{tag}>"))
        if self._open and tag not in _VOID:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        self.sections[-1].parts.append(("text" if any(self._open) else "prose", data))


def _escape(text: str) -> str:
    # As the Markdown renderer escapes text, so untouched text is unchanged.
    return escape(text, quote=False).replace('"', "&quot;")


def _open_tag(concept: Concept) -> str:
    classes = STUB_LINK if concept.stub else f'class="{_LINK_CLASS}"'
    tooltip = stub_title(concept.description) if concept.stub else concept.description
    title = f' title="{escape(tooltip)}"' if tooltip else ""
    return f'<a {classes} href="{escape(concept.href or "")}"{title}>'


def _link_names(text: str, matcher: _Matcher, linked: set[str]) -> str:
    out: list[str] = []
    position = 0
    for found in matcher.pattern.finditer(text):
        concept = matcher.concepts[str(found.lastgroup)]
        if concept.href is None or concept.id in linked:
            continue
        linked.add(concept.id)
        out += [
            _escape(text[position : found.start()]),
            _open_tag(concept),
            _escape(found.group()),
            STUB_NOTE if concept.stub else "",
            "</a>",
        ]
        position = found.end()
    out.append(_escape(text[position:]))
    return "".join(out)


def link_concepts(html: str, concepts: Sequence[Concept]) -> Linked:
    """`html`, a rendered body or part of one, with each concept's first
    occurrence linked in the text before the first top-level `<h2>` and in
    each section one starts.

    A concept link already in `html` is recognised by its address: it counts
    as its section's link for that concept, and it is marked as leading to a
    stub when it does."""
    if not concepts:
        return Linked(html, frozenset())
    matcher = _matcher(concepts)
    reader = _Reader({item.href: item for item in concepts if item.href is not None})
    reader.feed(html)
    reader.close()
    out: list[str] = []
    everywhere: set[str] = set()
    for section in reader.sections:
        linked = set(section.written)
        for kind, text in section.parts:
            if kind == "markup":
                out.append(text)
            elif kind == "text" or matcher is None:
                out.append(_escape(text))
            else:
                out.append(_link_names(text, matcher, linked))
        everywhere |= linked
    return Linked("".join(out), frozenset(everywhere))
