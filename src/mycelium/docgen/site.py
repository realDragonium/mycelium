"""A writing profile's documents as a static site: a home page, one page per
document, a generated page for each concept the documents link to that has
none, a list of the images they ask for, a report, one stylesheet, one script
and a search index. It is readable from `file://` with nothing loaded from
elsewhere, and without the script.

Everything is read through the profile's audience. The substrate is read
inside that audience's scope, so a concept, a relation or a description the
audience may not see is absent here without a rule of this module's own: an
external audience has no concept relations, and so no context block, no
parent chain and no grouping. A document whose statements or media left the
audience is left out and named.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field, replace
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit

from .. import (
    audience_scope,
    databases,
    docs_store,
    documentation_profiles,
    media,
    media_formats,
    media_store,
    prompt_store,
    store,
)
from ..audiences import Audience
from . import autolink, reads, render, schema

INDEX = "index.html"
STYLESHEET = "site.css"
SCRIPT = "site.js"
SEARCH_INDEX = "search-index.js"
IMAGES_WANTED = "images-wanted.html"
REPORT = "site-report.html"
MEDIA_DIRECTORY = "media"
STUB_DIRECTORY = "concept"
MAX_CONTEXT_ENTRIES = 12
MAX_STUB_STATEMENTS = 10
#: The most statements a generated page lists, folded after the first ones.
MAX_STUB_LISTED = 100
FEEDBACK_SCHEMES = ("http", "https", "mailto")

_DOCUMENTS_DATABASE = "mycelium-drafts.db"
_PROMPTS_DATABASE = "mycelium-prompts.db"
_RESERVED = frozenset(
    {
        "",
        ".",
        "..",
        INDEX,
        STYLESHEET,
        SCRIPT,
        SEARCH_INDEX,
        IMAGES_WANTED,
        REPORT,
        MEDIA_DIRECTORY,
        STUB_DIRECTORY,
    }
)
_SUMMARY_STUBS = 10
_SENTENCE = re.compile(r"(.+?[.!?…])(?:\s|$)", re.DOTALL)


class SiteRefused(Exception):
    """Why no site was written."""


@dataclass(frozen=True)
class LeftOut:
    title: str
    reason: str


@dataclass(frozen=True)
class StubCount:
    name: str
    #: How many written pages link to the concept.
    pages: int


@dataclass(frozen=True)
class PageNote:
    """Something the report says about one written page."""

    page: str
    text: str


@dataclass(frozen=True)
class Site:
    #: Every file written, relative to the output directory.
    files: tuple[str, ...]
    left_out: tuple[LeftOut, ...]
    #: Concepts that are linked but not written, the most linked first.
    stubs: tuple[StubCount, ...] = ()
    images_wanted: int = 0
    #: Flows a limit cut short, by title.
    cut_flows: tuple[PageNote, ...] = ()
    #: Concept links a writer wrote that match no concept, by name as written.
    unmatched_links: tuple[PageNote, ...] = ()


def summary(site: Site) -> list[str]:
    """What an export revealed, a line per finding, for a terminal."""
    lines = [f"left out {item.title!r}: {item.reason}" for item in site.left_out]
    if site.stubs:
        most = ", ".join(
            f"{item.name} ({_count(item.pages, 'page')})"
            for item in site.stubs[:_SUMMARY_STUBS]
        )
        lines.append(
            f"{_count(len(site.stubs), 'linked concept')} without a written "
            f"page; most linked: {most}"
        )
    if site.images_wanted:
        lines.append(
            f"{_count(site.images_wanted, 'image')} wanted, listed in {IMAGES_WANTED}"
        )
    lines += [
        f"flow cut short by a limit on {item.page!r}: {item.text}"
        for item in site.cut_flows
    ]
    lines += [
        f"concept link matching nothing on {item.page!r}: {item.text}"
        for item in site.unmatched_links
    ]
    return lines


class _NotExported(Exception):
    pass


@dataclass(frozen=True)
class _Page:
    row: sqlite3.Row
    revision: sqlite3.Row
    media: tuple[tuple[sqlite3.Row, bytes], ...]

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def title(self) -> str:
        return str(self.row["title"])

    @property
    def body(self) -> str:
        return str(self.revision["body"])

    @property
    def template(self) -> str:
        return str(self.row["document_type"])

    @property
    def path(self) -> str:
        return f"{self.template}/{self.row['slug']}.html"

    @property
    def href(self) -> str:
        return f"{quote(self.template)}/{quote(str(self.row['slug']))}.html"


def _stub_path(slug: str) -> str:
    return f"{STUB_DIRECTORY}/{slug}.html"


@dataclass(frozen=True)
class _Stub:
    entity_id: str
    name: str
    slug: str

    @property
    def path(self) -> str:
        return _stub_path(self.slug)

    # A slug holds nothing an address would need encoded.
    href = path


@dataclass(frozen=True)
class _Concepts:
    names: dict[str, str]
    descriptions: dict[str, str]
    parents: dict[str, str]
    #: Every name of a concept, for finding it in prose.
    all_names: dict[str, tuple[str, ...]]
    #: The names a person gave it besides the one in `names`.
    other_names: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class _Relation:
    label: str
    entity_id: str
    name: str
    note: str = ""


@dataclass(frozen=True)
class _Body:
    """A written page's body, rendered and linked."""

    lead: str
    sections: str
    #: The concepts it links to.
    linked: frozenset[str]
    unmatched: tuple[str, ...]


@dataclass
class _Export:
    title: str
    concepts: _Concepts
    pages: list[_Page]
    #: The written pages anchored on a concept, by template name.
    by_concept: dict[str, list[_Page]]
    #: A file name for every concept without a written page.
    slugs: dict[str, str]
    feedback_url: str | None
    #: The generated pages: concepts a written page links to.
    stubs: dict[str, _Stub] = field(default_factory=dict)


_STRUCTURE: dict[tuple[str, bool], str] = {
    ("contains", False): "Part of",
    ("contains", True): "Contains",
    ("sub-type", True): "A kind of",
    ("sub-type", False): "Kinds",
}
_RELATED = "Related"
#: How a relation reads from the page's own concept: the words when it is the
#: link's source, then when it is the target.
_RELATION_WORDS: dict[str, tuple[str, str]] = {
    "has": ("has", "belongs to"),
    "uses": ("uses", "used by"),
    "replaces": ("replaces", "replaced by"),
}
_LABEL_ORDER = [*_STRUCTURE.values(), _RELATED]


def _concepts(substrate: sqlite3.Connection) -> _Concepts:
    rows = substrate.execute(
        "SELECT e.id, e.description, COALESCE("
        "(SELECT text FROM names WHERE id = e.preferred_name_id), "
        "(SELECT MIN(text) FROM names WHERE entity_id = e.id)) AS name "
        "FROM entities e"
    ).fetchall()
    names = {str(row["id"]): str(row["name"]) for row in rows if row["name"]}
    all_names: dict[str, list[str]] = {}
    other_names: dict[str, list[str]] = {}
    for row in substrate.execute(
        "SELECT entity_id, text, generated_from_name_id FROM names ORDER BY text"
    ):
        entity_id, text = str(row["entity_id"]), str(row["text"])
        all_names.setdefault(entity_id, []).append(text)
        # A generated plural is a way to find the concept, not a name for it.
        if row["generated_from_name_id"] is None and text != names.get(entity_id):
            other_names.setdefault(entity_id, []).append(text)
    return _Concepts(
        names=names,
        descriptions={
            str(row["id"]): str(row["description"])
            for row in rows
            if row["description"]
        },
        parents=store.entity_parents(substrate),
        all_names={key: tuple(value) for key, value in all_names.items()},
        other_names={key: tuple(value) for key, value in other_names.items()},
    )


def _ancestors(entity_id: str, concepts: _Concepts) -> list[str]:
    """The concept's parents, the topmost first. Stops at a parent that was
    already passed or that cannot be named."""
    chain: list[str] = []
    seen = {entity_id}
    current = concepts.parents.get(entity_id)
    while current is not None and current not in seen and current in concepts.names:
        chain.append(current)
        seen.add(current)
        current = concepts.parents.get(current)
    return chain[::-1]


def _relations(
    substrate: sqlite3.Connection, entity_id: str, concepts: _Concepts
) -> list[_Relation]:
    """The concept's direct links: containment and kind first, then the rest."""
    links = [
        (other, link_type, True)
        for other, link_type in store.get_entity_links_outgoing(substrate, entity_id)
    ] + [
        (other, link_type, False)
        for other, link_type in store.get_entity_links_incoming(substrate, entity_id)
    ]
    found: list[_Relation] = []
    for other, link_type, outgoing in links:
        name = concepts.names.get(other)
        if other == entity_id or name is None:
            continue
        label = _STRUCTURE.get((link_type, outgoing))
        if label is not None:
            found.append(_Relation(label, other, name))
            continue
        words = _RELATION_WORDS.get(link_type)
        if words is None:
            plain = link_type.replace("-", " ")
            words = (plain, f"{plain} this")
        found.append(_Relation(_RELATED, other, name, words[0 if outgoing else 1]))
    found.sort(
        key=lambda item: (
            _LABEL_ORDER.index(item.label),
            item.name.casefold(),
            item.note,
            item.entity_id,
        )
    )
    return found[:MAX_CONTEXT_ENTRIES]


def _unsafe_segment(name: str) -> str | None:
    """Why `name` cannot be one file or directory name inside the site, or
    None when it can."""
    if not name:
        return "it is empty"
    if "/" in name or "\\" in name:
        return "it holds a path separator"
    if name.startswith("."):
        return "it starts with a dot"
    if any(unicodedata.category(char) == "Cc" for char in name):
        return "it holds a control character"
    return None


def _refuse_unsafe_paths(rows: list[sqlite3.Row]) -> None:
    """Template names are typed freely, so one could climb out of the
    output directory."""
    for row in rows:
        for part, value in (
            ("template name", str(row["document_type"])),
            ("slug", str(row["slug"])),
        ):
            reason = _unsafe_segment(value)
            if reason is not None:
                raise SiteRefused(
                    f"The document {row['title']!r} cannot be exported: its "
                    f"{part}, {value!r}, is not a safe file name ({reason})."
                )


def _admit(
    row: sqlite3.Row,
    revision: sqlite3.Row | None,
    scope: audience_scope.Scope,
) -> _Page:
    audience = scope.audience
    if revision is None:
        raise _NotExported("it has no stored revision")
    # Compared without case, since a file system may not tell `Media` from
    # `media`.
    if str(row["document_type"]).casefold() in _RESERVED:
        raise _NotExported(
            f"its template name, {row['document_type']!r}, cannot name a directory"
        )
    hidden = [
        statement_id
        for statement_id in json.loads(revision["statement_ids"])
        if statement_id not in scope.statement_ids
    ]
    if hidden:
        raise _NotExported(
            f"it cites {_count(len(hidden), 'statement')} that the audience "
            f"{audience.name} can no longer see: {', '.join(hidden)}"
        )
    for flow in schema.revision_flows(revision):
        cut = [item.statement_id for step in flow.drawing.steps for item in step.cut]
        if not scope.statement_ids.issuperset([*flow.drawing.statement_ids, *cut]):
            raise _NotExported(
                f"its flow {flow.name} shows a statement that the audience "
                f"{audience.name} can no longer see"
            )
    try:
        placed = media.published_files(
            str(revision["body"]), (audience.id, audience.internal)
        )
    except ValueError as exc:
        raise _NotExported(str(exc)) from exc
    return _Page(row, revision, tuple(placed))


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _media_name(item: sqlite3.Row) -> str:
    return f"{item['id']}.{media_formats.EXTENSIONS[str(item['content_type'])]}"


def _root(path: str) -> str:
    """From a page of the site back to its top."""
    return "../" * path.count("/")


def _anchor(page: _Page, concepts: _Concepts) -> str | None:
    own = page.row["anchor_entity_id"]
    return str(own) if own in concepts.names else None


def _written(export: _Export, entity_id: str, template: str | None) -> _Page | None:
    """The written page a concept's name leads to: the one of `template` when
    there is one, otherwise of the template that comes first by name."""
    pages = export.by_concept.get(entity_id, [])
    return next(
        (page for page in pages if page.template == template),
        pages[0] if pages else None,
    )


def _stub_link(export: _Export, href: str, entity_id: str, attributes: str = "") -> str:
    """A link to a generated page, marked as not written yet for every reader:
    a dotted underline, words a screen reader says, and a tooltip."""
    title = autolink.stub_title(export.concepts.descriptions.get(entity_id))
    return (
        f'<a class="stub" href="{escape(href)}" title="{escape(title)}"{attributes}>'
        f"{escape(export.concepts.names[entity_id])}{autolink.STUB_NOTE}</a>"
    )


def _name_html(
    export: _Export,
    root: str,
    entity_id: str,
    template: str | None,
    unlinked: str = "{}",
) -> str:
    """A concept's name outside a body: a link to its written page, a link
    marked as a stub to its generated one, or `unlinked` around the name."""
    name = escape(export.concepts.names[entity_id])
    page = _written(export, entity_id, template)
    if page is not None:
        return f'<a href="{escape(root + page.href)}">{name}</a>'
    stub = export.stubs.get(entity_id)
    if stub is not None:
        return _stub_link(export, root + stub.href, entity_id)
    return unlinked.format(name)


def _cited(page: _Page) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *json.loads(page.revision["statement_ids"]),
                *(
                    item
                    for flow in schema.revision_flows(page.revision)
                    for item in flow.drawing.statement_ids
                ),
            ]
        )
    )


def _sources(substrate: sqlite3.Connection, page: _Page) -> str:
    """The cited statements as they read when the revision was reviewed."""
    stored: dict[str, str] = json.loads(page.revision["cited_statements"] or "{}")
    drawn: dict[str, str] = {}
    for flow in schema.revision_flows(page.revision):
        drawn.update(flow.drawing.conditions)
        for step in flow.drawing.steps:
            drawn[step.statement_id] = step.text
            drawn.update({item.statement_id: item.text for item in step.outcomes})
    wanted = _cited(page)
    known = {**drawn, **{key: text for key, text in stored.items() if text}}
    current = store.get_statement_texts(
        substrate, [item for item in wanted if item not in known]
    )
    items = "".join(
        f'<li id="source-{escape(item)}">'
        f"{escape(known.get(item) or current.get(item, ''))}</li>"
        for item in wanted
    )
    return (
        '<details class="sources"><summary>Sources: '
        f"{_count(len(wanted), 'statement')}</summary><ol>{items}</ol></details>\n"
    )


def _context(
    export: _Export,
    root: str,
    relations: list[_Relation],
    template: str | None,
    *,
    prose_stubs: bool = False,
) -> str:
    """The concept's relations as chips, and a key to their looks. Where the
    page's text links to pages not written yet, the key also names the dotted
    underline that marks them, with or without chips."""
    prose = (PROSE_STUB_KEY,) if prose_stubs else ()
    if not relations:
        return _key(prose)
    rows: list[str] = []
    for label in _LABEL_ORDER:
        entries = [
            '<li class="context-entry">'
            + (
                f'<span class="context-note">{escape(item.note)}</span> '
                if item.note
                else ""
            )
            + _name_html(
                export,
                root,
                item.entity_id,
                template,
                '<span class="context-muted">{}</span>',
            )
            + "</li>"
            for item in relations
            if item.label == label
        ]
        if entries:
            rows.append(
                f'<div><dt>{label}</dt><dd><ul class="context-list">'
                f"{''.join(entries)}</ul></dd></div>"
            )
    looks = {
        "written"
        if _written(export, item.entity_id, template) is not None
        else "stub"
        if item.entity_id in export.stubs
        else "plain"
        for item in relations
    }
    chips = [text for look, text in _CONTEXT_LOOKS if look in looks]
    return f'<dl class="context">{"".join(rows)}</dl>\n' + _key(
        (*(chips if len(looks) > 1 else ()), *prose)
    )


def _key(parts: tuple[str, ...]) -> str:
    said = " · ".join(parts)
    return f'<p class="context-key">{said[:1].upper()}{said[1:]}</p>\n' if said else ""


PROSE_STUB_KEY = "dotted underline in text: not written yet"


#: What each look of a name in a context block means, in the order the key
#: says them.
_CONTEXT_LOOKS = (
    ("written", "solid outline: written page"),
    ("stub", "dashed: not written yet"),
    ("plain", "plain text: no page"),
)


def _breadcrumb(
    export: _Export, root: str, entity_id: str | None, title: str, template: str | None
) -> str:
    crumbs = [f'<li><a href="{root}{INDEX}">Home</a></li>']
    crumbs += [
        f"<li>{_name_html(export, root, ancestor, template)}</li>"
        for ancestor in (_ancestors(entity_id, export.concepts) if entity_id else [])
    ]
    crumbs.append(f'<li aria-current="page">{escape(title)}</li>')
    return (
        f'<nav class="breadcrumb" aria-label="Breadcrumb"><ol>{"".join(crumbs)}'
        "</ol></nav>\n"
    )


def _aliases(concepts: _Concepts, entity_id: str | None, title: str) -> list[str]:
    """The concept's other names a page shows, and search finds it by."""
    return [
        name
        for name in concepts.other_names.get(entity_id or "", ())
        if name.casefold() != title.casefold()
    ]


def _also_called(names: list[str]) -> str:
    if not names:
        return ""
    return f'<p class="also-called">Also called: {escape(", ".join(names))}</p>\n'


def _feedback(export: _Export, title: str, path: str) -> str:
    if export.feedback_url is None:
        return ""
    url = export.feedback_url.replace("{title}", quote(title, safe="")).replace(
        "{page}", quote(path, safe="")
    )
    return (
        f'<p class="feedback"><a href="{escape(url)}">'
        "Report a problem with this page</a></p>\n"
    )


def _named_concepts(
    substrate: sqlite3.Connection, statement_ids: list[str]
) -> set[str]:
    return {
        str(row["entity_id"])
        for row in substrate.execute(
            "SELECT DISTINCT n.entity_id FROM statement_mentions m "
            "JOIN names n ON n.id = m.name_id "
            "WHERE m.statement_id IN (SELECT value FROM json_each(?))",
            (json.dumps(statement_ids),),
        )
    }


def _render_body(substrate: sqlite3.Connection, export: _Export, page: _Page) -> _Body:
    concepts = export.concepts
    root = _root(page.path)
    own = _anchor(page, concepts)

    links = schema.revision_links(page.revision)
    # A merged concept is gone, but its names moved to the one that survives.
    moved = reads.resolve_concept_links(
        substrate, [link.name for link in links if link.entity_id not in concepts.names]
    )
    matched = {
        link.name: link.entity_id
        if link.entity_id in concepts.names
        else moved.get(link.name)
        for link in links
    }
    written = {name: entity_id for name, entity_id in matched.items() if entity_id}
    named = _named_concepts(substrate, _cited(page)) & concepts.names.keys()

    def concept(entity_id: str) -> autolink.Concept:
        target = _written(export, entity_id, page.template)
        return autolink.Concept(
            id=entity_id,
            names=concepts.all_names.get(entity_id, ()) if entity_id in named else (),
            href=root
            + (
                target.href
                if target is not None
                else _stub_path(export.slugs[entity_id])
            ),
            stub=target is None,
            description=concepts.descriptions.get(entity_id),
        )

    linkable = {
        entity_id: concept(entity_id)
        for entity_id in sorted(named | set(written.values()))
        if entity_id != own
    }
    candidates = list(linkable.values())
    if own is not None:
        candidates.append(
            autolink.Concept(own, concepts.all_names.get(own, ()), href=None)
        )
    lead, sections = render.render_frame(
        page.body,
        links={
            name: render.LinkTarget(
                href=linkable[entity_id].href,
                description=linkable[entity_id].description,
            )
            for name, entity_id in written.items()
            if entity_id in linkable
        },
        flows={flow.name: flow for flow in schema.revision_flows(page.revision)},
        media_urls={
            str(item["id"]): f"{root}{MEDIA_DIRECTORY}/{_media_name(item)}"
            for item, _data in page.media
        },
        concept_names=[name for item in candidates for name in item.names]
        + list(written),
    )
    linked_lead = autolink.link_concepts(lead, candidates)
    linked_sections = autolink.link_concepts(sections, candidates)
    return _Body(
        lead=linked_lead.html,
        sections=linked_sections.html,
        linked=linked_lead.concept_ids | linked_sections.concept_ids,
        unmatched=tuple(
            dict.fromkeys(
                link.name
                for link in render.concept_links(page.body)
                if link.name not in written
            )
        ),
    )


@dataclass(frozen=True)
class _Node:
    """A place in the page tree: a concept's written pages, or a parent
    concept without one, and what sits under it. Pages anchored on no concept
    are nodes of their own."""

    entity_id: str | None
    pages: tuple[_Page, ...]
    children: tuple[_Node, ...] = ()


def _tree(export: _Export) -> list[_Node]:
    """The written pages as a tree of their concepts. A concept is placed under
    its nearest ancestor that has a page or is a page's direct parent; a loop
    of parents is cut where it is found."""
    concepts = export.concepts
    anchored: dict[str, list[_Page]] = {}
    loose: list[_Node] = []
    for page in export.pages:
        anchor = _anchor(page, concepts)
        if anchor is None:
            loose.append(_Node(None, (page,)))
        else:
            anchored.setdefault(anchor, []).append(page)
    members = set(anchored)
    members |= {
        parent
        for entity_id in anchored
        if (parent := concepts.parents.get(entity_id)) in concepts.names
        and parent != entity_id
    }
    under: dict[str | None, list[str]] = {}
    for entity_id in members:
        nearest = next(
            (
                ancestor
                for ancestor in reversed(_ancestors(entity_id, concepts))
                if ancestor in members
            ),
            None,
        )
        under.setdefault(nearest, []).append(entity_id)
    placed: set[str] = set()

    def node(entity_id: str) -> _Node:
        placed.add(entity_id)
        return _Node(
            entity_id,
            tuple(anchored.get(entity_id, ())),
            _ordered(
                [
                    node(child)
                    for child in under.get(entity_id, [])
                    if child not in placed
                ],
                concepts,
            ),
        )

    roots = [node(entity_id) for entity_id in under.get(None, [])]
    # What a loop of parents left unplaced starts at its first name.
    while left := sorted(
        members - placed, key=lambda item: (concepts.names[item].casefold(), item)
    ):
        roots.append(node(left[0]))
    return list(_ordered([*loose, *roots], concepts))


def _ordered(nodes: list[_Node], concepts: _Concepts) -> tuple[_Node, ...]:
    """Pages by title first, then parents without a page by name."""
    return tuple(
        sorted(
            nodes,
            key=lambda item: (
                not item.pages,
                (
                    item.pages[0].title
                    if item.pages
                    else concepts.names[item.entity_id or ""]
                ).casefold(),
                item.entity_id or "",
            ),
        )
    )


def _first_sentence(body: str) -> str:
    text = render.lead_paragraph(body)
    found = _SENTENCE.match(text)
    return found.group(1) if found else text


def _parent_html(export: _Export, root: str, entity_id: str, current: str) -> str:
    """A parent concept without a written page: a link to its generated page
    when there is one, otherwise its name."""
    name = escape(export.concepts.names[entity_id])
    stub = export.stubs.get(entity_id)
    if stub is None:
        return f'<span class="parent">{name}</span>'
    marked = ' aria-current="page"' if stub.path == current else ""
    return _stub_link(export, root + stub.href, entity_id, marked)


def _page_item(
    export: _Export, root: str, current: str, page: _Page, *, summary: bool
) -> str:
    """A written page's link, with its template when the site has several and
    its first sentence on the home page."""
    marked = ' aria-current="page"' if page.path == current else ""
    sentence = _first_sentence(page.body) if summary else ""
    several = len({item.template for item in export.pages}) > 1
    return (
        f'<a href="{escape(root + page.href)}"{marked}>{escape(page.title)}</a>'
        + (f' <span class="template">{escape(page.template)}</span>' if several else "")
        + (f' <span class="summary">{escape(sentence)}</span>' if sentence else "")
    )


def _sidebar_list(
    export: _Export, root: str, current: str, nodes: tuple[_Node, ...] | list[_Node]
) -> str:
    items: list[str] = []
    for node in nodes:
        nested = (
            '<ul class="documents">'
            + _sidebar_list(export, root, current, node.children)
            + "</ul>"
            if node.children
            else ""
        )
        if node.pages:
            items += [
                "<li>"
                + _page_item(export, root, current, page, summary=False)
                + (nested if index == 0 else "")
                + "</li>"
                for index, page in enumerate(node.pages)
            ]
        else:
            assert node.entity_id is not None
            items.append(
                "<li>"
                + _parent_html(export, root, node.entity_id, current)
                + f"{nested}</li>"
            )
    return "".join(items)


def _home_list(
    export: _Export, nodes: tuple[_Node, ...] | list[_Node], level: int
) -> str:
    """The page tree in the sidebar's order: runs of pages without children
    as cards, and a section for each page or parent concept that has some."""
    out: list[str] = []
    cards: list[_Page] = []

    def flush() -> None:
        if cards:
            out.append(
                '<ul class="documents">'
                + "".join(
                    f"<li>{_page_item(export, '', INDEX, page, summary=True)}</li>"
                    for page in cards
                )
                + "</ul>"
            )
            cards.clear()

    heading = f"h{min(level, 6)}"
    for node in nodes:
        pages = list(node.pages)
        if not node.children:
            cards += pages
            continue
        flush()
        if pages:
            first = pages.pop(0)
            title = f'<a href="{escape(first.href)}">{escape(first.title)}</a>'
            sentence = _first_sentence(first.body)
            lead = f'<p class="summary">{escape(sentence)}</p>' if sentence else ""
        else:
            assert node.entity_id is not None
            title, lead = _parent_html(export, "", node.entity_id, INDEX), ""
        out.append(
            f'<section class="page-group"><{heading} class="group-title">{title}'
            f"</{heading}>{lead}"
            + _home_list(export, node.children, level + 1)
            + "</section>"
        )
        # The concept's other pages follow its children, as in the sidebar.
        cards += pages
    flush()
    return "".join(out)


_WITH_CONTENTS = ' class="with-contents"'


def _frame(
    export: _Export, path: str, title: str, main: str, *, contents: bool = False
) -> str:
    root = _root(path)

    def site_link(target: str, text: str) -> str:
        marked = ' aria-current="page"' if target == path else ""
        return f'<a href="{root}{target}"{marked}>{text}</a>'

    full_title = export.title if path == INDEX else f"{title} — {export.title}"
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(full_title)}</title>"
        f'<link rel="stylesheet" href="{root}{STYLESHEET}"></head>\n'
        '<body>\n<a class="skip-link" href="#main">Skip to content</a>\n'
        '<header class="site-header">'
        f'<a class="site-title" href="{root}{INDEX}">{escape(export.title)}</a>'
        # Hidden until the script shows it: without the script it does nothing.
        '<div class="search" role="search" hidden><input id="search" type="search" '
        'placeholder="Search" aria-label="Search this site" autocomplete="off" '
        'role="combobox" aria-expanded="false" aria-autocomplete="list" '
        'aria-controls="search-results" aria-keyshortcuts="/">'
        '<kbd class="search-key" aria-hidden="true">/</kbd>'
        '<div id="search-panel" class="search-panel" hidden>'
        '<p id="search-count" class="search-count"></p>'
        '<ul id="search-results" class="search-results" role="listbox" '
        'aria-label="Search results"></ul></div>'
        '<p id="search-status" class="visually-hidden" role="status"></p></div>'
        '</header>\n<div class="layout">\n'
        # The checkbox folds the sidebar on a narrow screen without a script;
        # the script swaps it for the button.
        '<input type="checkbox" id="sidebar-toggle" class="sidebar-toggle">'
        '<label for="sidebar-toggle" class="sidebar-label">Pages</label>\n'
        '<button type="button" class="sidebar-button" aria-expanded="false" '
        'aria-controls="site-pages" hidden>Pages</button>\n'
        '<nav class="sidebar" id="site-pages" aria-label="Pages"><ul class="documents">'
        + _sidebar_list(export, root, path, _tree(export))
        + "</ul></nav>\n"
        + f'<main id="main"{_WITH_CONTENTS if contents else ""}>\n{main}</main>\n'
        '<footer class="site-footer"><p>Maintenance: '
        + site_link(IMAGES_WANTED, "Images wanted")
        + " · "
        + site_link(REPORT, "Site report")
        + "</p></footer>\n</div>\n"
        f'<script src="{root}{SEARCH_INDEX}"></script>'
        f'<script src="{root}{SCRIPT}" data-root="{root}"></script>\n'
        "</body></html>\n"
    )


#: A heading that starts a section; the renderer gives only those an anchor.
_SECTION_HEADING = re.compile(r'<h2 id="([^"]+)">(.*?)</h2>', re.DOTALL)


def _heading_anchors(html: str, headings: list[tuple[str, str]]) -> str:
    """Each section heading with a link to itself, for sharing the section.
    The link stands beside the heading, not in it, so it is not part of the
    heading's name."""
    titles = {anchor_id: title for title, anchor_id in headings}

    def anchored(found: re.Match[str]) -> str:
        anchor_id, text = found.groups()
        title = titles.get(anchor_id, "")
        return (
            f'<div class="section-heading"><h2 id="{anchor_id}">{text}</h2>'
            f'<a class="heading-anchor" href="#{anchor_id}" '
            f'aria-label="Link to section: {escape(title)}">#</a></div>'
        )

    return _SECTION_HEADING.sub(anchored, html)


def _contents(headings: list[tuple[str, str]]) -> tuple[str, str]:
    """The contents list twice: in a rail beside the title on a wide screen,
    and folded under the lead on a narrow one, so neither needs the script.
    CSS shows one of them."""
    if len(headings) < 2:
        return "", ""
    listed = "".join(
        f'<li><a href="#{escape(anchor_id)}">{escape(heading)}</a></li>'
        for heading, anchor_id in headings
    )
    return (
        '<nav class="contents contents-rail" aria-label="Contents">'
        f'<p class="contents-title">On this page</p><ol>{listed}'
        '<li class="to-top"><a href="#top">Back to top</a></li></ol></nav>\n',
        '<details class="contents contents-fold"><summary>On this page</summary>'
        f'<nav aria-label="Contents"><ol>{listed}</ol></nav></details>\n',
    )


def _page_html(
    substrate: sqlite3.Connection, export: _Export, page: _Page, body: _Body
) -> str:
    concepts = export.concepts
    root = _root(page.path)
    anchor = _anchor(page, concepts)
    relations = _relations(substrate, anchor, concepts) if anchor else []
    headings = render.contents(page.body)
    rail, fold = _contents(headings)
    written = str(page.revision["created_at"])[:10]
    return _frame(
        export,
        page.path,
        page.title,
        _breadcrumb(export, root, anchor, page.title, page.template)
        + rail
        + f"<h1>{escape(page.title)}</h1>\n"
        + _also_called(_aliases(concepts, anchor, page.title))
        + f'<div class="lead">\n{_scrolling(body.lead)}</div>\n'
        + fold
        + _context(
            export,
            root,
            relations,
            page.template,
            prose_stubs=autolink.STUB_LINK in body.lead + body.sections,
        )
        + _heading_anchors(_scrolling(body.sections), headings)
        + '<footer class="page-footer">\n'
        + _sources(substrate, page)
        + f'<p class="revision-date">Written <time datetime="{escape(written)}">'
        f"{escape(written)}</time></p>\n"
        + _feedback(export, page.title, page.path)
        + '<p class="to-top"><a href="#top">Back to top</a></p>\n'
        + "</footer>\n",
        contents=bool(rail),
    )


def _stub_html(
    substrate: sqlite3.Connection, export: _Export, stub: _Stub, linking: list[_Page]
) -> str:
    concepts = export.concepts
    root = _root(stub.path)
    description = concepts.descriptions.get(stub.entity_id)
    statements = store.count_statements(substrate, entity_id=stub.entity_id)
    known = store.list_statements(
        substrate, limit=MAX_STUB_LISTED, entity_id=stub.entity_id
    )
    linked_from = "".join(
        f'<li><a href="{escape(root + page.href)}">{escape(page.title)}</a></li>'
        for page in linking
    )
    return _frame(
        export,
        stub.path,
        stub.name,
        _breadcrumb(export, root, stub.entity_id, stub.name, None)
        + f"<h1>{escape(stub.name)}</h1>\n"
        + _also_called(_aliases(concepts, stub.entity_id, stub.name))
        + '<p class="stub-note">This page has not been written yet. What it '
        "shows is generated from the knowledge base.</p>\n"
        + (
            f'<p class="stub-description">{escape(description)}</p>\n'
            if description
            else ""
        )
        + _context(export, root, _relations(substrate, stub.entity_id, concepts), None)
        + _known(known, statements)
        + '<section class="linked-from"><h2>Linked from</h2>'
        f"<ul>{linked_from}</ul></section>\n" + _feedback(export, stub.name, stub.path),
    )


def _known(known: list[sqlite3.Row], statements: int) -> str:
    """The statements that name a generated page's concept: the first few,
    then the rest folded, up to `MAX_STUB_LISTED`."""
    if not known:
        return ""

    def listed(rows: list[sqlite3.Row]) -> str:
        return "".join(f"<li>{escape(str(row['text']))}</li>" for row in rows)

    first, rest = known[:MAX_STUB_STATEMENTS], known[MAX_STUB_STATEMENTS:]
    more = statements - len(first)
    names = "names" if more == 1 else "name"
    folded = ""
    if rest:
        cap = (
            f'<p class="stub-statements">The first {len(known)} of {statements} '
            "statements are listed.</p>"
            if statements > len(known)
            else ""
        )
        folded = (
            f'<details class="more-statements"><summary>'
            f"{_count(more, 'more statement')} {names} it</summary>"
            f"<ul>{listed(rest)}</ul>{cap}</details>"
        )
    elif more > 0:
        folded = (
            f'<p class="stub-statements">{_count(more, "more statement")} {names} '
            "it.</p>"
        )
    return (
        f'<section class="known"><h2>What is known</h2><ul>{listed(first)}</ul>'
        f"{folded}</section>\n"
    )


def _index_html(export: _Export) -> str:
    stubs = "".join(
        f"<li>{_stub_link(export, stub.href, stub.entity_id)}</li>"
        for stub in export.stubs.values()
    )
    return _frame(
        export,
        INDEX,
        export.title,
        f"<h1>{escape(export.title)}</h1>\n"
        + f'<div class="home">{_home_list(export, _tree(export), 2)}</div>\n'
        + (
            '<details class="stubs"><summary>Not written yet '
            f'<span class="count">({len(export.stubs)})</span></summary>'
            f'<ul class="stub-list">{stubs}</ul></details>\n'
            if stubs
            else ""
        ),
    )


def _table(headings: list[str], rows: list[list[str]], empty: str) -> str:
    """A table of cells that are already HTML, or `empty` without rows."""
    if not rows:
        return f"<p>{empty}</p>\n"
    head = "".join(f"<th>{heading}</th>" for heading in headings)
    body = "".join(
        f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows
    )
    return _scrolling(
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>\n"
    )


def _scrolling(html: str) -> str:
    """Each table in a box of its own that scrolls sideways, so a wide one
    does not widen the page. The box can take focus to be scrolled from the
    keyboard."""
    return html.replace(
        "<table>",
        '<div class="table-scroll" role="region" aria-label="Table" tabindex="0">'
        "<table>",
    ).replace("</table>", "</table></div>")


def _page_link(page: _Page, fragment: str = "") -> str:
    """A link to a written page from the top of the site."""
    target = f"{page.href}#{quote(fragment)}" if fragment else page.href
    return f'<a href="{escape(target)}">{escape(page.title)}</a>'


def _images_wanted(export: _Export) -> tuple[str, int]:
    rows: list[list[str]] = []
    for page in export.pages:
        anchors: dict[str, str] = {}
        for heading, anchor_id in render.contents(page.body):
            anchors.setdefault(heading, anchor_id)
        rows += [
            [
                _page_link(page, anchors.get(item.section or "", "")),
                escape(item.section or "Lead"),
                escape(item.description),
            ]
            for item in render.image_placeholders(page.body)
        ]
    html = _frame(
        export,
        IMAGES_WANTED,
        "Images wanted",
        "<h1>Images wanted</h1>\n"
        "<p>Where a writer marked that a picture would help.</p>\n"
        + _table(["Page", "Section", "What it should show"], rows, "None."),
    )
    return html, len(rows)


def _report_html(export: _Export, site: Site) -> str:
    titles = {page.title: page for page in export.pages}

    def notes(items: tuple[PageNote, ...]) -> list[list[str]]:
        return [[_page_link(titles[item.page]), escape(item.text)] for item in items]

    by_name = {stub.name: stub for stub in export.stubs.values()}
    return _frame(
        export,
        REPORT,
        "Site report",
        "<h1>Site report</h1>\n"
        "<h2>Linked concepts without a written page</h2>\n"
        + _table(
            ["Concept", "Written pages linking to it"],
            [
                [
                    _stub_link(
                        export, by_name[item.name].href, by_name[item.name].entity_id
                    ),
                    str(item.pages),
                ]
                for item in site.stubs
            ],
            "None.",
        )
        + "<h2>Images wanted</h2>\n"
        f'<p>{site.images_wanted}, listed in <a href="{IMAGES_WANTED}">'
        "Images wanted</a>.</p>\n"
        "<h2>Documents left out</h2>\n"
        + _table(
            ["Document", "Why"],
            [[escape(item.title), escape(item.reason)] for item in site.left_out],
            "None.",
        )
        + "<h2>Flows cut short by a limit</h2>\n"
        + _table(["Page", "Flow"], notes(site.cut_flows), "None.")
        + "<h2>Concept links that match no concept</h2>\n"
        + _table(["Page", "Name as written"], notes(site.unmatched_links), "None."),
    )


_INLINE = frozenset({"a", "code", "em", "s", "span", "strong", "time"})
_VOID = frozenset(
    {"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"}
)
#: What a search keeps of a flow figure: what its steps, outcomes and
#: conditions state. Its key, group labels, fold summaries, step references
#: and the kinds of its lines only find their way around it. Each part ends in
#: a full stop in text, so that an excerpt does not run them together.
_FLOW_FIGURE = "flow-figure"
_FLOW_KEPT = frozenset({"flow-statement", "flow-if-text"})
#: Table cells and list items end in a full stop in text for the same reason,
#: and so does an item's text before a list nested in it. A body cell after
#: the first is given its column's header, as "Header: cell", so an excerpt of
#: a row still says what each cell is; a header is not text of its own.
_SENTENCE_TAGS = frozenset({"figcaption", "li", "td", "th"})
_LISTS = frozenset({"ol", "ul"})
_ENDED = (".", "!", "?", "…", ":", ";")
#: Punctuation that closes the text before it, as against ".env".
_LEADING_PUNCTUATION = re.compile(r"[:,;.!?)](?!\w)")
#: Where an element starts or ends, which separates words.
_BREAK = "\n"


class _Text(HTMLParser):
    """A rendered body as plain text, by section, as a sighted reader sees
    it: text only a screen reader is given is left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        #: Anchor, heading and text; the lead has no anchor.
        self.sections: list[tuple[str, list[str], list[str]]] = [("", [], [])]
        self._in_heading = False
        #: Per open element, its tag and classes.
        self._open: list[tuple[str, set[str]]] = []
        #: A full stop owed after the text so far, given only once more text
        #: follows that does not start with punctuation of its own.
        self._stop_owed = False
        #: A list item has ended and the next one started, so its first letter
        #: follows a full stop of this reader's.
        self._item_ended = False
        self._next_item = False
        #: The current table's column headers, the one being read, and the
        #: column of the body cell being read.
        self._headers: list[str] = []
        self._header: list[str] | None = None
        self._column = 0
        #: A column's header owed before the cell's first text.
        self._label = ""

    def _skipped(self) -> bool:
        in_figure = kept = False
        for tag, classes in self._open:
            if autolink.HIDDEN_CLASS in classes or tag == "thead":
                return True
            in_figure = in_figure or _FLOW_FIGURE in classes
            kept = kept or tag == "figcaption" or bool(classes & _FLOW_KEPT)
        return in_figure and not kept

    def _add(self, text: str) -> None:
        _anchor_id, heading, body = self.sections[-1]
        parts = heading if self._in_heading else body
        if self._skipped():
            # What is left out still keeps the words around it apart.
            if parts and parts[-1] != _BREAK:
                parts.append(_BREAK)
            return
        said = text.lstrip()
        if self._label and said:
            if self._stop_owed:
                self._stop_owed = False
                self._stop(parts)
            parts.append(self._label + " ")
            self._label = ""
        elif _LEADING_PUNCTUATION.match(said):
            # It follows the text before it with no separator of this reader's.
            self._stop_owed = False
            while parts and parts[-1] == _BREAK:
                parts.pop()
        elif self._stop_owed and said:
            self._stop_owed = False
            self._stop(parts)
            first = said[0]
            if (
                self._next_item
                and first.islower()
                and len(first.upper()) == 1
                and self._after_sentence(parts)
                and not self._in_code()
            ):
                start = len(text) - len(said)
                text = text[:start] + first.upper() + said[1:]
        if said:
            self._item_ended = self._next_item = False
        parts.append(text)

    def _in_code(self) -> bool:
        return any(tag in ("code", "pre") for tag, _classes in self._open)

    @staticmethod
    def _after_sentence(parts: list[str]) -> bool:
        said = "".join(parts).rstrip()
        return said.endswith((".", "!", "?"))

    def _settle(self) -> None:
        """Gives the full stop still owed at the end of a section."""
        if self._stop_owed:
            self._stop_owed = False
            self._stop(self.sections[-1][2])

    def close(self) -> None:
        super().close()
        self._settle()

    @staticmethod
    def _stop(parts: list[str]) -> None:
        for at in range(len(parts) - 1, -1, -1):
            said = parts[at].rstrip()
            if said:
                if not said.endswith(_ENDED):
                    parts[at] = said + "." + parts[at][len(said) :]
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        anchor = values.get("id")
        # Only a heading that starts a section was given an anchor.
        if tag == "h2" and anchor:
            self._settle()
            self.sections.append((anchor, [], []))
            self._in_heading = True
        elif tag not in _INLINE:
            self._add(_BREAK)
        if (
            tag in _LISTS
            and any(open_tag == "li" for open_tag, _ in self._open)
            and not self._skipped()
        ):
            self._stop_owed = True
        if tag == "li" and self._item_ended:
            self._next_item = True
        if tag == "table":
            self._headers = []
        elif tag == "tr":
            self._column = 0
        elif tag == "th" and any(open_tag == "thead" for open_tag, _ in self._open):
            self._header = []
        elif tag == "td":
            header = (
                self._headers[self._column] if self._column < len(self._headers) else ""
            )
            self._label = f"{header}:" if self._column and header else ""
            self._column += 1
        if tag not in _VOID:
            self._open.append((tag, set((values.get("class") or "").split())))

    def handle_endtag(self, tag: str) -> None:
        while any(open_tag == tag for open_tag, _classes in self._open):
            open_tag, classes = self._open[-1]
            ends = open_tag in _SENTENCE_TAGS or classes & _FLOW_KEPT
            if ends and not self._skipped():
                self._stop_owed = True
                self._item_ended = open_tag == "li"
            self._open.pop()
            if open_tag == tag:
                break
        if tag == "th" and self._header is not None:
            self._headers.append(" ".join("".join(self._header).split()).rstrip(".:;"))
            self._header = None
        elif tag == "td":
            self._label = ""
        if tag == "h2":
            self._in_heading = False
        elif tag not in _INLINE:
            self._add(_BREAK)

    def handle_data(self, data: str) -> None:
        hidden = any(autolink.HIDDEN_CLASS in classes for _tag, classes in self._open)
        if self._header is not None and not hidden:
            self._header.append(data)
        self._add(data)


def _search_entry(
    page: _Page, body: _Body, aliases: list[str] | None = None
) -> dict[str, object]:
    reader = _Text()
    reader.feed(body.lead + body.sections)
    reader.close()

    def words(parts: list[str]) -> str:
        return " ".join("".join(parts).split())

    entry: dict[str, object] = {"title": page.title, "href": page.href}
    if aliases:
        entry["aliases"] = aliases
    entry["sections"] = [
        {"anchor": anchor, "heading": words(heading), "text": words(text)}
        for anchor, heading, text in reader.sections
    ]
    return entry


def _stub_entry(concepts: _Concepts, stub: _Stub) -> dict[str, object]:
    """What a generated page shows of the concept besides its name."""
    entry: dict[str, object] = {"title": stub.name, "href": stub.href, "stub": True}
    aliases = _aliases(concepts, stub.entity_id, stub.name)
    if aliases:
        entry["aliases"] = aliases
    description = concepts.descriptions.get(stub.entity_id, "")
    entry["sections"] = (
        [{"anchor": "", "heading": "", "text": description}] if description else []
    )
    return entry


def _search_index(export: _Export, bodies: dict[str, _Body]) -> str:
    entries = [
        _search_entry(
            page,
            bodies[page.id],
            _aliases(export.concepts, _anchor(page, export.concepts), page.title),
        )
        for page in export.pages
    ] + [_stub_entry(export.concepts, stub) for stub in export.stubs.values()]
    # A script that sets a global, since a page opened from `file://` may not
    # fetch a file beside it.
    return f"window.SITE_SEARCH = {json.dumps(entries, separators=(',', ':'))};\n"


def _slugs(names: dict[str, str]) -> dict[str, str]:
    """A file name per concept, the same on every export of the same concepts."""
    used: set[str] = set()
    slugs: dict[str, str] = {}
    for entity_id, name in sorted(
        names.items(), key=lambda item: (item[1].casefold(), item[0])
    ):
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "concept"
        slug, number = base, 1
        while slug in used:
            number += 1
            slug = f"{base}-{number}"
        used.add(slug)
        slugs[entity_id] = slug
    return slugs


def _build(
    substrate: sqlite3.Connection,
    documents: sqlite3.Connection,
    profile: str,
    scope: audience_scope.Scope,
    feedback_url: str | None,
    title: str,
) -> tuple[dict[str, bytes], Site]:
    rows = sorted(
        (
            row
            for row in docs_store.list_documents(documents, limit=None)
            if row["guideline_set"] == profile
        ),
        key=lambda row: (
            str(row["title"]).casefold(),
            str(row["document_type"]),
            str(row["slug"]),
        ),
    )
    _refuse_unsafe_paths(rows)
    pages: list[_Page] = []
    left_out: list[LeftOut] = []
    for row in rows:
        revision = (
            None
            if row["current_revision"] is None
            else docs_store.get_revision(
                documents, str(row["id"]), int(row["current_revision"])
            )
        )
        try:
            pages.append(_admit(row, revision, scope))
        except _NotExported as exc:
            left_out.append(LeftOut(str(row["title"]), str(exc)))

    concepts = _concepts(substrate)
    by_concept: dict[str, list[_Page]] = {}
    for page in sorted(pages, key=lambda page: (page.template, page.path)):
        anchor = _anchor(page, concepts)
        if anchor is not None:
            by_concept.setdefault(anchor, []).append(page)
    export = _Export(
        title=title,
        concepts=concepts,
        pages=pages,
        by_concept=by_concept,
        slugs=_slugs(
            {
                entity_id: name
                for entity_id, name in concepts.names.items()
                if entity_id not in by_concept
            }
        ),
        feedback_url=feedback_url,
    )
    bodies = {page.id: _render_body(substrate, export, page) for page in pages}
    linking: dict[str, list[_Page]] = {}
    for page in pages:
        for entity_id in bodies[page.id].linked:
            if entity_id in export.slugs:
                linking.setdefault(entity_id, []).append(page)
    export.stubs = {
        entity_id: _Stub(entity_id, concepts.names[entity_id], export.slugs[entity_id])
        for entity_id in sorted(
            linking, key=lambda item: (concepts.names[item].casefold(), item)
        )
    }

    wanted_html, wanted = _images_wanted(export)
    site = Site(
        files=(),
        left_out=tuple(left_out),
        stubs=tuple(
            sorted(
                (
                    StubCount(stub.name, len(linking[stub.entity_id]))
                    for stub in export.stubs.values()
                ),
                key=lambda item: (-item.pages, item.name.casefold()),
            )
        ),
        images_wanted=wanted,
        cut_flows=tuple(
            PageNote(page.title, flow.title.strip() or flow.name)
            for page in pages
            for flow in schema.revision_flows(page.revision)
            if flow.drawing.truncated
        ),
        unmatched_links=tuple(
            PageNote(page.title, name)
            for page in pages
            for name in bodies[page.id].unmatched
        ),
    )
    here = Path(__file__).parent
    files: dict[str, bytes] = {
        INDEX: _index_html(export).encode(),
        IMAGES_WANTED: wanted_html.encode(),
        REPORT: _report_html(export, site).encode(),
        STYLESHEET: (here / STYLESHEET).read_bytes(),
        SCRIPT: (here / SCRIPT).read_bytes(),
        SEARCH_INDEX: _search_index(export, bodies).encode(),
    }
    for page in pages:
        files[page.path] = _page_html(substrate, export, page, bodies[page.id]).encode()
        for item, data in page.media:
            files[f"{MEDIA_DIRECTORY}/{_media_name(item)}"] = data
    for stub in export.stubs.values():
        files[stub.path] = _stub_html(
            substrate, export, stub, linking[stub.entity_id]
        ).encode()
    return files, replace(site, files=tuple(files))


def readable_title(profile: str) -> str:
    """A profile's name as a site title: `developer-reference` becomes
    "Developer reference"."""
    words = " ".join(re.split(r"[-_\s]+", profile)).strip()
    return words[:1].upper() + words[1:]


def _feedback_template(template: str | None) -> str | None:
    if template is None:
        return None
    template = template.strip()
    if urlsplit(template).scheme.lower() not in FEEDBACK_SCHEMES:
        raise SiteRefused(
            f"The feedback address {template!r} is not one a page may link to. "
            "It must start with http:, https: or mailto:."
        )
    return template


def build_site(
    substrate: sqlite3.Connection,
    documents: sqlite3.Connection,
    *,
    profile: str,
    audience: Audience,
    feedback_url: str | None = None,
    title: str | None = None,
) -> tuple[dict[str, bytes], Site]:
    """The site of `profile`'s current documents as its files by path, read
    through `audience`.

    `feedback_url` puts a link to report a problem on every written and
    generated page. In it `{title}` and `{page}`, the page's path within the
    site, are replaced URL-encoded. `title` names the site in its header, on
    its home page and after each page's title; without it the profile's name
    is made readable.

    Raises `SiteRefused` when `feedback_url` is not an http, https or mailto
    address, or a document's template name or slug is not a single safe file
    name."""
    feedback = _feedback_template(feedback_url)
    scope = audience_scope.capture(substrate, audience)
    with audience_scope.applied(substrate, scope):
        return _build(
            substrate,
            documents,
            profile,
            scope,
            feedback,
            (title or "").strip() or readable_title(profile),
        )


def write_site(
    substrate: sqlite3.Connection,
    documents: sqlite3.Connection,
    *,
    profile: str,
    audience: Audience,
    out: Path,
    feedback_url: str | None = None,
    title: str | None = None,
) -> Site:
    """Write what `build_site` returns into `out`, which must be missing or
    empty so no page of an earlier export survives.

    Raises `SiteRefused`, having written nothing, when `out` holds something
    or `build_site` refuses."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise SiteRefused(
            f"{out} is not an empty directory. Choose a new or empty one, so "
            "that no page of an earlier export is left behind."
        )
    files, site = build_site(
        substrate,
        documents,
        profile=profile,
        audience=audience,
        feedback_url=feedback_url,
        title=title,
    )
    inside = out.resolve()
    targets = {path: (out / path).resolve() for path in files}
    for path, target in targets.items():
        if not target.is_relative_to(inside):
            raise SiteRefused(f"The file {path!r} would be written outside {out}.")
    for path, data in files.items():
        target = targets[path]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return site


def archive(files: Mapping[str, bytes]) -> bytes:
    """`files` as one zip. The same files give the same bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for path in sorted(files):
            entry = zipfile.ZipInfo(path)
            # Without a mode, unzip on Unix creates files nobody may read.
            entry.external_attr = 0o644 << 16
            bundle.writestr(entry, files[path], zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def profile_audience(profile: str) -> Audience:
    """The audience `profile` writes for, in the configured prompt store.
    Raises `SiteRefused` when there is no such profile or its audience was
    retired."""
    catalogue = documentation_profiles.capture()
    names = [item.name for item in catalogue.profiles]
    if profile not in names:
        raise SiteRefused(
            f"There is no writing profile named {profile!r}. "
            f"Profiles: {', '.join(names) or 'none'}."
        )
    audience = catalogue.audience(profile)
    if audience is None:
        raise SiteRefused(
            f"The audience of the profile {profile!r} was retired. Choose an "
            "audience for the profile first."
        )
    return audience


def export_data_dir(
    data_dir: Path,
    profile: str,
    out: Path,
    feedback_url: str | None = None,
    title: str | None = None,
) -> Site:
    """`write_site` for the instance kept in `data_dir`, for the audience the
    profile writes for. Reads the databases as they are; it migrates nothing."""
    needed = (
        databases.SUBSTRATE,
        _DOCUMENTS_DATABASE,
        _PROMPTS_DATABASE,
        media_store.DB_NAME,
    )
    missing = [name for name in needed if not (data_dir / name).exists()]
    if missing:
        raise SiteRefused(
            f"{data_dir} has no {', '.join(missing)}. Point --data-dir at the "
            "data directory of an instance the server has run on."
        )
    prompt_store.configure(data_dir / _PROMPTS_DATABASE)
    media_store.configure(data_dir / media_store.DB_NAME)
    audience = profile_audience(profile)
    with (
        closing(store.connect(data_dir / databases.SUBSTRATE)) as substrate,
        closing(docs_store.connect(data_dir / _DOCUMENTS_DATABASE)) as documents,
    ):
        return write_site(
            substrate,
            documents,
            profile=profile,
            audience=audience,
            out=out,
            feedback_url=feedback_url,
            title=title,
        )
