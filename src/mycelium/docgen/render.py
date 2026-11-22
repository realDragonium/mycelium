"""Safe HTML for a document body, shared by every place that shows one.

A body is Markdown with three additions: concept links, `[[Name]]` or
`[[Name|text]]`; flow placements, a fenced block with the info string `flow`
holding a flow's name; and image placeholders, `![what to show](image-wanted)`,
which mark where a picture would help. The renderer looks nothing up: the
caller passes what each link resolved to and each placed flow's drawing.

The page frame is read from plain Markdown: the lead is everything before the
first `##` heading, and each `##` heading starts a section with a stable anchor.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import media
from . import flows as flow_drawing
from .schema import StoredFlow

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.token import Token


@dataclass(frozen=True)
class ConceptLink:
    name: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class LinkTarget:
    href: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Section:
    title: str
    anchor: str
    body: str


@dataclass(frozen=True)
class Frame:
    lead: str
    sections: list[Section]


@dataclass(frozen=True)
class ImagePlaceholder:
    description: str
    #: The title of the section it is in; None in the lead.
    section: str | None
    #: That section's anchor; None in the lead.
    anchor: str | None


_CONCEPT_LINK = re.compile(r"\[\[([^\[\]|\n]+)(?:\|([^\[\]\n]+))?\]\]")
_LINE_END = re.compile(r"\r\n?|\n")
_BLANK_LINE = re.compile(r"\n[ \t]*(?=\n)")
_BACKTICKS = re.compile(r"`+")
_FLOW_INFO = "flow"
#: The destination of an image that does not exist yet.
IMAGE_WANTED = "image-wanted"

# A recognised concept link is swapped for a placeholder before Markdown is
# parsed, so the pipe in `[[Name|text]]` cannot split a table cell and the
# renderer links exactly the spans `concept_links` reports.
_OPEN, _CLOSE = "", ""
_PLACEHOLDER = re.compile(f"{_OPEN}(\\d+){_CLOSE}")


def _markdown() -> MarkdownIt:
    from markdown_it import MarkdownIt

    return MarkdownIt("js-default")


def _line_starts(body: str) -> list[int]:
    return [0, *(found.end() for found in _LINE_END.finditer(body))]


def _prose_regions(body: str) -> Iterator[tuple[int, int]]:
    """The parts of a body outside fenced and indented code blocks."""
    starts = [*_line_starts(body), len(body)]
    position = 0
    for token in _markdown().parse(body):
        if token.type in ("fence", "code_block") and token.map is not None:
            first, last = (starts[min(line, len(starts) - 1)] for line in token.map)
            if first > position:
                yield position, first
            position = max(position, last)
    if position < len(body):
        yield position, len(body)


def _paragraphs(body: str) -> Iterator[tuple[int, int]]:
    """Prose split at blank lines, which a code span cannot cross."""
    for start, end in _prose_regions(body):
        position = start
        for blank in _BLANK_LINE.finditer(body, start, end):
            yield position, blank.end()
            position = blank.end()
        yield position, end


def _code_spans(body: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    position = start
    while position < end:
        if body[position] == "\\":
            position += 2
            continue
        opener = _BACKTICKS.match(body, position, end)
        if opener is None:
            position += 1
            continue
        position = opener.end()
        for closer in _BACKTICKS.finditer(body, position, end):
            if len(closer.group()) == len(opener.group()):
                spans.append((opener.start(), closer.end()))
                position = closer.end()
                break
    return spans


def _escaped(body: str, at: int) -> bool:
    backslashes = len(body[:at]) - len(body[:at].rstrip("\\"))
    return backslashes % 2 == 1


def concept_links(body: str) -> list[ConceptLink]:
    """The concept links a body holds, in order, with where each one is. Code
    spans and code blocks are left alone."""
    found: list[ConceptLink] = []
    for start, end in _paragraphs(body):
        spans = _code_spans(body, start, end)
        for link in _CONCEPT_LINK.finditer(body, start, end):
            name = link.group(1).strip()
            if not name or any(a < link.end() and link.start() < b for a, b in spans):
                continue
            if _escaped(body, link.start()):
                continue
            text = (link.group(2) or "").strip() or name
            found.append(ConceptLink(name, text, link.start(), link.end()))
    return found


def flow_placements(body: str) -> list[str]:
    """The names of the flows a body places, in order."""
    return [
        token.content.strip()
        for token in _markdown().parse(body)
        if token.type == "fence" and token.info.strip() == _FLOW_INFO
    ]


def _with_placeholders(body: str, links: Sequence[ConceptLink]) -> str:
    parts: list[str] = []
    position = 0
    for index, link in enumerate(links):
        parts += [body[position : link.start], f"{_OPEN}{index}{_CLOSE}"]
        position = link.end
    return "".join([*parts, body[position:]])


def _link_at(found: re.Match[str], links: Sequence[ConceptLink]) -> ConceptLink | None:
    index = int(found.group(1))
    return links[index] if index < len(links) else None


def _plain(text: str, links: Sequence[ConceptLink]) -> str:
    def display(found: re.Match[str]) -> str:
        link = _link_at(found, links)
        return found.group() if link is None else link.text

    return _PLACEHOLDER.sub(display, text)


def _split_text(token: Token, links: Sequence[ConceptLink]) -> list[Token]:
    from markdown_it.token import Token

    def text(content: str) -> Token:
        return Token("text", "", 0, content=content, level=token.level)

    out: list[Token] = []
    position = 0
    for found in _PLACEHOLDER.finditer(token.content):
        link = _link_at(found, links)
        if link is None:
            continue
        if found.start() > position:
            out.append(text(token.content[position : found.start()]))
        out.append(
            Token(
                "concept_link",
                "",
                0,
                content=link.text,
                meta={"name": link.name},
                level=token.level,
            )
        )
        position = found.end()
    if position < len(token.content) or not out:
        out.append(text(token.content[position:]))
    return out


def _place_links(tokens: Sequence[Token], links: Sequence[ConceptLink]) -> list[Token]:
    out: list[Token] = []
    in_link = 0
    for token in tokens:
        in_link += token.nesting if token.type in ("link_open", "link_close") else 0
        if token.type == "text" and not in_link:
            out += _split_text(token, links)
            continue
        if token.type == "text":
            # An anchor cannot hold another, so here a link is only its text.
            token.content = _plain(token.content, links)
        elif token.type == "image":
            # Alt text is an attribute, so a link inside it is only its text.
            for child in token.children or []:
                child.content = _plain(child.content, links)
        elif token.children:
            token.children = _place_links(token.children, links)
        out.append(token)
    return out


def _parse(body: str) -> tuple[MarkdownIt, list[Token], list[ConceptLink]]:
    links = concept_links(body)
    markdown = _markdown()
    tokens = _place_links(markdown.parse(_with_placeholders(body, links)), links)
    return markdown, tokens, links


def _title(inline: Token) -> str:
    return "".join(
        _title(child) if child.type == "image" else child.content
        for child in inline.children or []
        if child.type in ("text", "code_inline", "concept_link", "image")
    ).strip()


def _anchor(title: str, used: set[str]) -> str:
    base = re.sub(r"[^\w]+", "-", title.lower()).strip("-") or "section"
    anchor, number = base, 1
    while anchor in used:
        number += 1
        anchor = f"{base}-{number}"
    used.add(anchor)
    return anchor


def _headings(tokens: Sequence[Token]) -> list[tuple[Token, str, str]]:
    """Each top-level `##` heading's opening token, title and anchor."""
    used: set[str] = set()
    found: list[tuple[Token, str, str]] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2" and token.level == 0:
            title = _title(tokens[index + 1])
            found.append((token, title, _anchor(title, used)))
    return found


def split_sections(body: str) -> Frame:
    """A body's lead, everything before the first `##` heading, and its sections."""
    _markdown_it, tokens, _links = _parse(body)
    starts = [*_line_starts(body), len(body)]
    bounds = [
        (starts[token.map[0]], starts[token.map[1]], title, anchor)
        for token, title, anchor in _headings(tokens)
        if token.map is not None
    ]
    ends = [*(heading[0] for heading in bounds[1:]), len(body)]
    return Frame(
        lead=body[: bounds[0][0]] if bounds else body,
        sections=[
            Section(title=title, anchor=anchor, body=body[after:end])
            for (_start, after, title, anchor), end in zip(bounds, ends, strict=False)
        ],
    )


def contents(body: str) -> list[tuple[str, str]]:
    """A body's contents list: each section's title and anchor."""
    return [
        (section.title, section.anchor) for section in split_sections(body).sections
    ]


def _wanted(token: Token) -> bool:
    return token.type == "image" and token.attrGet("src") == IMAGE_WANTED


def _words(tokens: Sequence[Token]) -> list[str]:
    """The words of inline content as a reader sees them."""
    return "".join(
        " " if token.type in ("softbreak", "hardbreak") else token.content
        for token in tokens
    ).split()


def _alt(image: Token) -> str:
    return " ".join(_words(image.children or []))


def _images_wanted(tokens: Sequence[Token]) -> Iterator[Token]:
    for token in tokens:
        if _wanted(token):
            yield token
        yield from _images_wanted(token.children or [])


def image_placeholders(body: str) -> list[ImagePlaceholder]:
    """The image placeholders a body holds, in order, each with what it asks
    for and the section it is in."""
    _markdown_it, tokens, _links = _parse(body)
    sections = {
        id(token): (title, anchor) for token, title, anchor in _headings(tokens)
    }
    found: list[ImagePlaceholder] = []
    section: tuple[str, str] | tuple[None, None] = (None, None)
    for token in tokens:
        section = sections.get(id(token), section)
        found += [
            ImagePlaceholder(
                description=_alt(image), section=section[0], anchor=section[1]
            )
            for image in _images_wanted(token.children or [])
        ]
    return found


def lead_paragraph(body: str, max_words: int = 60) -> str:
    """The first paragraph of a body's lead as plain text, cut to
    `max_words`. Empty when the body opens with anything else."""
    _markdown_it, tokens, _links = _parse(body)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2" and token.level == 0:
            break
        if token.type == "paragraph_open" and token.level == 0:
            words = _words(tokens[index + 1].children or [])
            return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")
    return ""


def _stand_alone(tokens: Sequence[Token]) -> list[Token]:
    """A paragraph holding only an image placeholder becomes one block, since
    a figure cannot sit inside a paragraph."""
    from markdown_it.token import Token

    out: list[Token] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        inline = tokens[index + 1] if index + 1 < len(tokens) else None
        children = [
            child
            for child in (inline.children or [] if inline is not None else [])
            if child.type != "text" or child.content.strip()
        ]
        if (
            token.type == "paragraph_open"
            and len(children) == 1
            and _wanted(children[0])
        ):
            out.append(
                Token("image_wanted", "", 0, content=_alt(children[0]), block=True)
            )
            index += 3
        else:
            out.append(token)
            index += 1
    return out


_KEY_LINES: dict[flow_drawing.EdgeKind, str] = {
    "then": "then",
    "part": "includes",
    "separate": "starts a separate process",
    "branch": "depends on a condition or an outcome",
}
_KEY_BOXES = {"result": "result", "failure": "on failure", "other": "other outcome"}


def _outcome_kind(outcome: flow_drawing.SideOutcome) -> str:
    label = flow_drawing.side_label(outcome.links)
    return {"result": "result", "on failure": "failure"}.get(label, "other")


def _flow_key(
    chain: Sequence[flow_drawing.Placed], drawing: flow_drawing.Drawing
) -> str:
    """What the line styles and side boxes mean, for those the drawing uses."""
    lines = flow_drawing.line_kinds(chain)
    boxes = {_outcome_kind(o) for step in drawing.steps for o in step.outcomes}
    if not boxes and lines <= {"then"}:
        return ""
    items = [
        f'<li><span class="flow-key-line flow-key-{kind}" aria-hidden="true"></span>'
        f"{text}</li>"
        for kind, text in _KEY_LINES.items()
        if kind in lines
    ] + [
        f'<li><span class="flow-key-box flow-key-{kind}" aria-hidden="true"></span>'
        f"{text}</li>"
        for kind, text in _KEY_BOXES.items()
        if kind in boxes
    ]
    return f'<ul class="flow-key" aria-label="Key">{"".join(items)}</ul>'


def _folded(
    chain: Sequence[flow_drawing.Placed], depth: int, around: tuple[int, ...]
) -> Iterator[tuple[int, tuple[int, ...]]]:
    """Each step's number with the folded groups it sits in, outermost first,
    each named by its first step."""
    for placed in chain:
        yield placed.step.number, around
        for group in placed.groups:
            inside = (*around, group.numbers[0]) if depth >= 1 else around
            for branch in group.branches:
                yield from _folded(branch.chain, depth + 1, inside)


_SUMMARY_LENGTH = 60


def shortened(text: str, length: int = _SUMMARY_LENGTH) -> str:
    """`text` cut at a word to at most `length` characters, with an ellipsis
    where it was cut."""
    if len(text) <= length:
        return text
    cut = text[: length - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:.") + "…"


def _has_list(said: flow_drawing.Said) -> bool:
    return any(meaning.condition and meaning.condition.items for meaning in said)


class _FlowMarkup:
    """A flow as nested lists. Groups below the first level are folded."""

    def __init__(self, flow: StoredFlow, names: Collection[str]) -> None:
        from markdown_it.common.utils import escapeHtml

        self.escape = escapeHtml
        self.flow = flow
        #: Concept names, which keep their capital at the start of a condition.
        self.names = names
        self.texts = flow.drawing.conditions
        self.laid_out = flow_drawing.layout(flow.drawing)
        self.folds = dict(_folded(self.laid_out, 0, ()))

    def step_id(self, number: int) -> str:
        return self.escape(f"flow-{self.flow.name}-step-{number}")

    def group_id(self, first: int) -> str:
        return self.escape(f"flow-{self.flow.name}-group-{first}")

    def step_ref(self, number: int, origin: int) -> str:
        """A link to a step. Inside a fold the reader at `origin` has not
        opened, it leads to that fold until the script points it at the step,
        so it lands somewhere visible without the script."""
        closed = [fold for fold in self.folds[number] if fold not in self.folds[origin]]
        if not closed:
            return f'<a class="flow-ref" href="#{self.step_id(number)}">{number}</a>'
        return (
            f'<a class="flow-ref" href="#{self.group_id(closed[0])}" '
            f'data-step="{self.step_id(number)}">{number}</a>'
        )

    def condition(self, item: flow_drawing.Condition) -> str:
        lead = (
            f'<span class="flow-if">{self.escape(item.lead)}</span>'
            if item.lead
            else ""
        )
        if not item.items:
            said = flow_drawing.condition_case(item.text, self.names)
            text = f'<span class="flow-if-text">{self.escape(said)}</span>'
            return f"{lead} {text}" if lead else text
        entries = "".join(f"<li>{self.condition(entry)}</li>" for entry in item.items)
        return f'{lead}<ul class="flow-if-list">{entries}</ul>'

    def said(self, said: flow_drawing.Said) -> str:
        """What a line says, parallel links joined by "or"."""
        parts: list[str] = []
        for meaning in said:
            label = self.escape(meaning.label)
            condition = (
                "" if meaning.condition is None else self.condition(meaning.condition)
            )
            parts.append(
                f"{label}, {condition}" if label and condition else label or condition
            )
        return "; or ".join(parts)

    def label(self, said: flow_drawing.Said, kind: str, inline: str = "span") -> str:
        """`said` in an element of the class `kind`: a block where it holds a
        list, otherwise `inline`."""
        tag = "div" if _has_list(said) else inline
        return f'<{tag} class="{kind}">{self.said(said)}</{tag}>'

    def outcome(self, item: flow_drawing.SideOutcome) -> str:
        said = flow_drawing.meanings(item.links, self.texts, side=True)
        colon = "" if _has_list(said) else ":"
        return (
            f'<li class="flow-outcome flow-{_outcome_kind(item)}">'
            f'<div class="flow-label">{self.said(said)}{colon}</div>'
            f'<span class="flow-statement">{self.escape(item.text)}</span></li>'
        )

    def outcomes(self, step: flow_drawing.Step) -> str:
        items = [self.outcome(item) for item in step.outcomes]
        if step.more_outcomes:
            items.append(
                f'<li class="flow-more">{flow_drawing.more_text(step.more_outcomes)}'
                "</li>"
            )
        return f'<ul class="flow-outcomes">{"".join(items)}</ul>' if items else ""

    def arrows(self, item: flow_drawing.Placed) -> str:
        origin = item.step.number
        lines = [
            '<li class="flow-arrow flow-join">&rarr; joins '
            + flow_drawing.numbers_text(
                join.to, lambda number: self.step_ref(number, origin)
            )
            + (f" {self.label(join.said, 'flow-label')}" if join.said else "")
            + "</li>"
            for join in item.joins
        ]
        if item.step.continues:
            lines.append(
                '<li class="flow-continues">&rarr; '
                f"{flow_drawing.continues_text(item.step, self.escape)}</li>"
            )
        return f'<ul class="flow-arrows">{"".join(lines)}</ul>' if lines else ""

    def from_step(self, origin: int, here: int) -> str:
        return f"from step {self.step_ref(origin, here)}"

    def group(self, item: flow_drawing.Group, owner: int, depth: int) -> str:
        branches: list[str] = []
        for index, branch in enumerate(item.branches):
            first = branch.chain[0].step.number
            # Only the first branch hangs right under the step it comes from.
            apart = index > 0
            branches.append(
                f'<li class="flow-branch{" flow-branch-apart" if apart else ""}">'
                + (
                    f'<p class="flow-from">{self.from_step(owner, first)}</p>'
                    if apart
                    else ""
                )
                + (
                    self.label(branch.said, "flow-branch-label", "p")
                    if branch.said
                    else ""
                )
                + f'<ol class="flow">{self.chain(branch.chain, depth + 1)}</ol></li>'
            )
        numbers = item.numbers
        steps = flow_drawing.numbers_text(numbers)
        kind = f"flow-group flow-group-{item.kind}"
        listed = f'<ul class="flow-branches">{"".join(branches)}</ul>'
        if depth == 0:
            return (
                f'<div class="{kind}"><p class="flow-group-label">'
                f"{self.escape(item.label)} "
                f'<span class="flow-group-steps">({steps})</span></p>{listed}</div>'
            )
        first_text = shortened(item.branches[0].chain[0].step.text)
        more = len(numbers) - 1
        return (
            f'<details class="{kind}" id="{self.group_id(numbers[0])}">'
            f'<summary class="flow-group-label">'
            f'<span class="flow-group-kind">{self.escape(item.label)}:</span> '
            f'<span class="flow-group-first">{self.escape(first_text)}</span>'
            + (
                f' <span class="flow-group-more">{flow_drawing.more_text(more)}</span>'
                if more
                else ""
            )
            + f' <span class="flow-group-steps">({steps})</span></summary>'
            f"{listed}</details>"
        )

    def via(self, item: flow_drawing.Placed) -> str:
        """What the line to the step under this one says. Where groups stand
        between them, it also says which step that line comes from."""
        assert item.onward is not None
        said = self.said(item.onward_said)
        here = item.step.number
        if item.groups:
            text = self.from_step(here, here) + (f": {said}" if said else "")
        elif said:
            text = said
        else:
            return ""
        tag = "div" if _has_list(item.onward_said) else "p"
        return f'<{tag} class="flow-via">{text}</{tag}>'

    def placed(self, item: flow_drawing.Placed, depth: int) -> str:
        step = item.step
        line = f" flow-to-{item.onward}" if item.onward else ""
        return (
            f'<li class="flow-step{line}" id="{self.step_id(step.number)}" '
            f'value="{step.number}"><div class="flow-box">'
            f'<span class="flow-statement">{self.escape(step.text)}</span></div>'
            + self.outcomes(step)
            + self.arrows(item)
            + "".join(self.group(found, step.number, depth) for found in item.groups)
            + (self.via(item) if item.onward else "")
            + "</li>"
        )

    def chain(self, items: Sequence[flow_drawing.Placed], depth: int) -> str:
        return "".join(self.placed(item, depth) for item in items)

    def figure(self) -> str:
        title = self.flow.title.strip()
        return (
            '<figure class="flow-figure">'
            + (f"<figcaption>{self.escape(title)}</figcaption>" if title else "")
            + _flow_key(self.laid_out, self.flow.drawing)
            + f'<ol class="flow">{self.chain(self.laid_out, 0)}</ol></figure>\n'
        )


def _flow_html(flow: StoredFlow, names: Collection[str]) -> str:
    return _FlowMarkup(flow, names).figure()


def _render(
    body: str,
    *,
    links: Mapping[str, LinkTarget] | None,
    flows: Mapping[str, StoredFlow] | None,
    media_urls: Mapping[str, str] | None,
    concept_names: Collection[str] | None,
) -> tuple[str, str]:
    """The lead and the sections of a body as HTML."""
    from markdown_it.common.utils import escapeHtml
    from markdown_it.renderer import RendererHTML
    from markdown_it.utils import EnvType, OptionsDict

    targets = links or {}
    placed = flows or {}
    markdown, tokens, written = _parse(body)
    tokens = _stand_alone(tokens)
    headings = _headings(tokens)
    for heading, _title_text, anchor in headings:
        heading.attrSet("id", anchor)

    def wanted(description: str, tag: str, caption: str) -> str:
        return (
            f'<{tag} class="image-wanted">'
            '<span class="image-wanted-label">Image wanted</span> '
            f"<{caption}>{escapeHtml(description)}</{caption}></{tag}>"
        )

    def image_wanted(
        self: RendererHTML,
        tokens: Sequence[Token],
        idx: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        return wanted(tokens[idx].content, "figure", "figcaption") + "\n"

    def image(
        self: RendererHTML,
        tokens: Sequence[Token],
        idx: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[idx]
        if _wanted(token):
            return wanted(_alt(token), "span", "span")
        alt = escapeHtml(self.renderInlineAsText(token.children or [], options, env))
        found = media.REFERENCE.fullmatch(str(token.attrGet("src") or ""))
        if found is None:
            return alt
        url = (
            media.content_url(found.group(1))
            if media_urls is None
            else media_urls.get(found.group(1))
        )
        if url is None:
            return alt
        return f'<img src="{escapeHtml(url)}" alt="{alt}" loading="lazy">'

    def concept_link(
        self: RendererHTML,
        tokens: Sequence[Token],
        idx: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[idx]
        text = escapeHtml(token.content)
        target = targets.get(str(token.meta["name"]))
        if target is None or not target.href:
            return text
        title = (
            f' title="{escapeHtml(target.description)}"' if target.description else ""
        )
        return (
            f'<a class="concept-link" href="{escapeHtml(target.href)}"{title}>'
            f"{text}</a>"
        )

    def fence(
        self: RendererHTML,
        tokens: Sequence[Token],
        idx: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[idx]
        if token.info.strip() != _FLOW_INFO:
            return RendererHTML.fence(self, tokens, idx, options, env)
        name = token.content.strip()
        flow = placed.get(name)
        if flow is None:
            return f"<p>{escapeHtml(name)}</p>\n"
        return _flow_html(
            flow, targets.keys() if concept_names is None else concept_names
        )

    markdown.add_render_rule("image", image)
    markdown.add_render_rule("image_wanted", image_wanted)
    markdown.add_render_rule("concept_link", concept_link)
    markdown.add_render_rule("fence", fence)
    first = next(
        (
            index
            for index, token in enumerate(tokens)
            if headings and token is headings[0][0]
        ),
        len(tokens),
    )

    def html(part: Sequence[Token]) -> str:
        rendered: str = markdown.renderer.render(part, markdown.options, {})
        # A placeholder the inline pass did not turn into a link (inside a code
        # span this module's scan missed, or a link destination) goes back to
        # its text.
        return _PLACEHOLDER.sub(
            lambda found: escapeHtml(_plain(found.group(), written)), rendered
        )

    return html(tokens[:first]), html(tokens[first:])


def render_markdown(
    body: str,
    *,
    links: Mapping[str, LinkTarget] | None = None,
    flows: Mapping[str, StoredFlow] | None = None,
    media_urls: Mapping[str, str] | None = None,
    concept_names: Collection[str] | None = None,
) -> str:
    """Safe HTML for a document body. The only images are media references;
    any other image becomes its alt text, so a document cannot load outside
    content. An image placeholder becomes a marked figure with what it asks
    for.

    `links` maps a concept link's name as written to what it resolved to, and
    `flows` a placed flow's name to the stored flow, whose title is its caption.
    A link without a target is its text; a placement without a flow is its
    name.

    Without `media_urls` an image is served by Mycelium under the reader's own
    audience check. With it, an image's address is looked up by media id, and
    one that is absent becomes its alt text.

    A condition in a flow starts lower case after its "when" unless it starts
    with an acronym or a concept name: one of `concept_names`, or without
    them, of the names in `links`."""
    lead, sections = _render(
        body,
        links=links,
        flows=flows,
        media_urls=media_urls,
        concept_names=concept_names,
    )
    return lead + sections


def render_frame(
    body: str,
    *,
    links: Mapping[str, LinkTarget] | None = None,
    flows: Mapping[str, StoredFlow] | None = None,
    media_urls: Mapping[str, str] | None = None,
    concept_names: Collection[str] | None = None,
) -> tuple[str, str]:
    """`render_markdown` in two parts: the lead and the sections, so a page can
    set its contents list between them."""
    return _render(
        body,
        links=links,
        flows=flows,
        media_urls=media_urls,
        concept_names=concept_names,
    )
