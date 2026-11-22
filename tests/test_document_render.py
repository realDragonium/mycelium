"""The shared document renderer: plain Markdown, concept links, flow placements
and the page frame."""

from __future__ import annotations

import re

from mycelium.docgen import flows
from mycelium.docgen.flows import FlowLink, FlowStatement
from mycelium.docgen.render import (
    ConceptLink,
    ImagePlaceholder,
    LinkTarget,
    concept_links,
    contents,
    flow_placements,
    image_placeholders,
    lead_paragraph,
    render_frame,
    render_markdown,
    shortened,
    split_sections,
)
from mycelium.docgen.schema import StoredFlow


def test_plain_body_renders_as_before():
    body = (
        "# Welcome\n\n"
        "Exports run *nightly*. <script>alert(1)</script>\n\n"
        "[bad](javascript:alert(1)) ![pixel](https://example.test/p.png)\n\n"
        "![The export dialog](media:med_000000000001)\n\n"
        "```python\nprint('[[x]]')\n```\n"
    )
    assert render_markdown(body) == (
        "<h1>Welcome</h1>\n"
        "<p>Exports run <em>nightly</em>. &lt;script&gt;alert(1)&lt;/script&gt;</p>\n"
        "<p>[bad](javascript:alert(1)) pixel</p>\n"
        '<p><img src="/api/media/med_000000000001/content" '
        'alt="The export dialog" loading="lazy"></p>\n'
        "<pre><code class=\"language-python\">print('[[x]]')\n</code></pre>\n"
    )


def test_concept_links_are_found_with_name_text_and_position():
    body = "An [[Invoice]] belongs to [[Workspace | a workspace]]."
    assert concept_links(body) == [
        ConceptLink(name="Invoice", text="Invoice", start=3, end=14),
        ConceptLink(name="Workspace", text="a workspace", start=26, end=53),
    ]
    assert body[3:14] == "[[Invoice]]"


def test_concept_links_in_code_are_left_alone():
    body = (
        "Write `[[Invoice]]` or ``a ` [[Export]]`` to link; \\`[[SSO]] is one.\n\n"
        "A stray ` tick, then [[Workspace]].\n\n"
        "```\n[[Fenced]]\n```\n\n"
        "    [[Indented]]\n\n"
        "- item\n\n"
        "  ~~~text\n  [[Nested]]\n  ~~~\n\n"
        "[[ ]] and [[Last]]\n"
    )
    assert [link.name for link in concept_links(body)] == ["SSO", "Workspace", "Last"]
    html = render_markdown(body)
    assert "<code>[[Invoice]]</code>" in html
    assert "[[Fenced]]" in html and "[[Nested]]" in html and "[[Indented]]" in html
    assert "[[SSO]]" not in html and "[[Last]]" not in html


def test_concept_link_renders_as_a_link_only_with_a_target():
    body = "[[Invoice|Invoices]] need [[SSO]], [[Export]] and [[Unknown <b>]]."
    html = render_markdown(
        body,
        links={
            "Invoice": LinkTarget(href="invoice.html?a=1&b=2", description='A "bill"'),
            "SSO": LinkTarget(href="sso.html"),
            "Export": LinkTarget(description="No page yet"),
        },
    )
    assert html == (
        '<p><a class="concept-link" href="invoice.html?a=1&amp;b=2" '
        'title="A &quot;bill&quot;">Invoices</a> need '
        '<a class="concept-link" href="sso.html">SSO</a>, Export and '
        "Unknown &lt;b&gt;.</p>\n"
    )
    assert render_markdown(body).count("[[") == 0


def test_concept_link_with_a_pipe_does_not_split_a_table_cell():
    body = "| Who | What |\n|---|---|\n| [[Workspace|Owners]] | pay |\n"
    html = render_markdown(body, links={"Workspace": LinkTarget(href="w.html")})
    assert '<td><a class="concept-link" href="w.html">Owners</a></td>' in html
    assert html.count("<td>") == 2


def test_concept_link_in_alt_text_is_its_text():
    html = render_markdown(
        "![The [[Invoice|invoice]] list](media:med_000000000001)",
        links={"Invoice": LinkTarget(href="invoice.html")},
    )
    assert 'alt="The invoice list"' in html and "<a" not in html


def test_flow_placements_are_fenced_blocks_named_flow():
    body = (
        "Lead.\n\n```flow\nexport-request-to-download\n```\n\n"
        "```python\nflow\n```\n\n~~~flow\n  invite-accepted  \n~~~\n"
    )
    assert flow_placements(body) == ["export-request-to-download", "invite-accepted"]


class Graph:
    def __init__(self) -> None:
        self.statements = {
            "stm_req": FlowStatement("event", "An export is <requested>"),
            "stm_run": FlowStatement("event", "The export runs"),
            "stm_done": FlowStatement("event", "The file is ready"),
            "stm_fail": FlowStatement("event", "The owner is told"),
            "stm_big": FlowStatement("state", "The workspace has > 1000 invoices"),
            "stm_file": FlowStatement("state", "A download exists"),
        }
        self.outgoing = {
            "stm_req": [
                FlowLink("stm_run", "proceeds", None),
                FlowLink("stm_fail", "on-failure", {"statement_id": "stm_big"}),
            ],
            "stm_run": [
                FlowLink("stm_done", "contains", None),
                FlowLink("stm_req", "proceeds", None),
            ],
            "stm_done": [FlowLink("stm_file", "establishes", None)],
        }

    def statement(self, statement_id: str) -> FlowStatement | None:
        return self.statements.get(statement_id)

    def links(self, statement_id: str) -> list[FlowLink]:
        return self.outgoing.get(statement_id, [])


def test_placed_flow_draws_lines_only_for_arrows():
    drawing = flows.draw_flow(Graph(), "stm_req")
    assert drawing is not None
    drawing.steps[2].continues = True
    drawing.steps[2].more_outcomes = 2
    html = render_markdown(
        "Before.\n\n```flow\nexport\n```\n\nAfter.\n",
        flows={
            "export": StoredFlow(
                name="export",
                title="From request to <download>",
                start="stm_req",
                drawing=drawing,
            )
        },
    )

    assert html == (
        "<p>Before.</p>\n"
        '<figure class="flow-figure">'
        "<figcaption>From request to &lt;download&gt;</figcaption>"
        # The key names only the lines and boxes this drawing uses.
        '<ul class="flow-key" aria-label="Key">'
        '<li><span class="flow-key-line flow-key-then" aria-hidden="true"></span>'
        "then</li>"
        '<li><span class="flow-key-line flow-key-part" aria-hidden="true"></span>'
        "includes</li>"
        '<li><span class="flow-key-box flow-key-result" aria-hidden="true"></span>'
        "result</li>"
        '<li><span class="flow-key-box flow-key-failure" aria-hidden="true"></span>'
        "on failure</li></ul>"
        '<ol class="flow">'
        # A plain next step is a solid line and no arrow text.
        '<li class="flow-step flow-to-then" id="flow-export-step-1" value="1">'
        '<div class="flow-box"><span class="flow-statement">'
        "An export is &lt;requested&gt;</span></div>"
        '<ul class="flow-outcomes"><li class="flow-outcome flow-failure">'
        '<div class="flow-label">on failure, <span class="flow-if">when</span> '
        '<span class="flow-if-text">the workspace has &gt; 1000 invoices</span>:'
        '</div><span class="flow-statement">The owner is told</span></li></ul></li>'
        # A part is a line of its own kind, said beside it.
        '<li class="flow-step flow-to-part" id="flow-export-step-2" value="2">'
        '<div class="flow-box"><span class="flow-statement">The export runs</span></div>'
        '<ul class="flow-arrows"><li class="flow-arrow flow-join">&rarr; joins step '
        '<a class="flow-ref" href="#flow-export-step-1">1</a></li></ul>'
        '<p class="flow-via">includes</p></li>'
        '<li class="flow-step" id="flow-export-step-3" value="3">'
        '<div class="flow-box"><span class="flow-statement">The file is ready</span></div>'
        '<ul class="flow-outcomes"><li class="flow-outcome flow-result">'
        '<div class="flow-label">result:</div>'
        '<span class="flow-statement">A download exists</span></li>'
        '<li class="flow-more">and 2 more</li></ul>'
        '<ul class="flow-arrows">'
        # Stored before cuts were recorded: it cannot say what is missing.
        '<li class="flow-continues">&rarr; continues beyond this drawing</li></ul>'
        "</li>"
        "</ol></figure>\n"
        "<p>After.</p>\n"
    )


def test_a_cut_flow_names_what_was_not_drawn_and_a_condition_reads_on():
    drawing = flows.draw_flow(Graph(), "stm_req")
    assert drawing is not None
    drawing.steps[2].continues = True
    drawing.steps[2].cut = [
        flows.CutStatement(statement_id="stm_a", text="The file is <mailed>"),
        flows.CutStatement(statement_id="stm_b", text="The link expires"),
    ]
    drawing.steps[2].more_cut = 4
    flow = StoredFlow(name="export", title="", start="stm_req", drawing=drawing)

    assert (
        '<li class="flow-continues">&rarr; continues: The file is &lt;mailed&gt;; '
        "The link expires (not drawn), and 4 more</li>"
    ) in render_markdown("```flow\nexport\n```\n", flows={"export": flow})
    # A concept name keeps its capital: one the document links, or one the
    # caller names.
    kept = '<span class="flow-if-text">Text of stm_if</span>'
    assert kept in _flow_html(
        Branches(), "stm_1", links={"Text": LinkTarget(href="text.html")}
    )
    assert kept in _flow_html(Branches(), "stm_1", concept_names=["Text"])


class Branches:
    """1 proceeds to 2 when a condition holds, and to 3; 1 starts 4 as a
    separate process; 2 proceeds to 4, 3 to 5, 4 to 6 and 6 to 7."""

    outgoing = {
        "stm_1": [
            FlowLink("stm_2", "proceeds", {"statement_id": "stm_if"}),
            FlowLink("stm_3", "proceeds", None),
            FlowLink("stm_4", "triggers", None),
        ],
        "stm_2": [FlowLink("stm_4", "proceeds", None)],
        "stm_3": [FlowLink("stm_5", "proceeds", None)],
        "stm_4": [FlowLink("stm_6", "proceeds", None)],
        "stm_6": [FlowLink("stm_7", "proceeds", None)],
    }

    def statement(self, statement_id: str) -> FlowStatement | None:
        return FlowStatement("event", f"Text of {statement_id}")

    def links(self, statement_id: str) -> list[FlowLink]:
        return self.outgoing.get(statement_id, [])


def _flow_html(reader: object, start: str, **options: object) -> str:
    drawing = flows.draw_flow(reader, start)  # type: ignore[arg-type]
    assert drawing is not None
    flow = StoredFlow(name="f", title="", start=start, drawing=drawing)
    return render_markdown("```flow\nf\n```\n", flows={"f": flow}, **options)


def _steps(html: str) -> list[str]:
    """Each step's own markup up to the next step, outer or nested."""
    return html.split('<li class="flow-step')[1:]


def test_steps_a_step_leads_to_hang_off_it_in_groups():
    html = _flow_html(Branches(), "stm_1")
    steps = _steps(html)
    # Numbered as drawn: each group's chains under the step that leads to them.
    assert re.findall(r'class="flow-step[^"]*" id="[^"]+" value="(\d+)"', html) == [
        *"1234567"
    ]
    assert re.findall(r"Text of (stm_\d)", html) == [
        "stm_1",
        "stm_2",
        "stm_3",
        "stm_5",
        "stm_4",
        "stm_6",
        "stm_7",
    ]
    # Step 1 has no line down: nothing follows it on its own.
    assert steps[0].startswith('" id="flow-f-step-1"')
    # A group names every step it holds.
    assert (
        '<div class="flow-group flow-group-branch"><p class="flow-group-label">'
        'Then, depending on the condition <span class="flow-group-steps">'
        '(steps 2–4)</span></p><ul class="flow-branches">'
        '<li class="flow-branch"><p class="flow-branch-label">'
        '<span class="flow-if">when</span> <span class="flow-if-text">text of stm_if'
        '</span></p><ol class="flow">'
    ) in steps[0]
    # Step 3 does not follow step 2 above it: a divider and where it comes from.
    assert (
        '<li class="flow-branch flow-branch-apart"><p class="flow-from">from step '
        '<a class="flow-ref" href="#flow-f-step-1">1</a></p><ol class="flow">'
        '<li class="flow-step flow-to-then" id="flow-f-step-3"'
    ) in html
    assert (
        '<div class="flow-group flow-group-separate"><p class="flow-group-label">'
        'Starts separately <span class="flow-group-steps">(steps 5–7)</span></p>'
    ) in steps[3]
    # 2 joins stm_4, drawn as step 5, by a link to it, and draws no line.
    assert steps[1].startswith('" id="flow-f-step-2"')
    assert (
        '&rarr; joins step <a class="flow-ref" href="#flow-f-step-5">5</a>' in steps[1]
    )
    assert steps[2].startswith(' flow-to-then" id="flow-f-step-3"')
    assert steps[4].startswith(' flow-to-then" id="flow-f-step-5"')
    assert "flow-reached" not in html and "&rarr; step" not in html
    assert "<details" not in html and "flow-source" not in html


class Nested:
    """a includes p and q; p starts p1 and p2 and leads on to r. p1, r and q
    join a; p2 joins p1, and q joins p1 too."""

    outgoing = {
        "a": [FlowLink("p", "contains", None), FlowLink("q", "contains", None)],
        "p": [
            FlowLink("p1", "triggers", None),
            FlowLink("p2", "triggers", None),
            FlowLink("r", "proceeds", None),
        ],
        "p1": [FlowLink("a", "proceeds", None)],
        "p2": [FlowLink("p1", "proceeds", None)],
        "r": [FlowLink("a", "proceeds", None)],
        "q": [FlowLink("a", "proceeds", None), FlowLink("p1", "proceeds", None)],
    }

    def statement(self, statement_id: str) -> FlowStatement | None:
        return FlowStatement("event", f"Text of {statement_id}")

    def links(self, statement_id: str) -> list[FlowLink]:
        return self.outgoing.get(statement_id, [])


def test_groups_below_the_first_level_are_folded_and_references_reach_them():
    html = _flow_html(Nested(), "a")
    # p1 is named twice: in the summary of its fold and as the step.
    assert re.findall(r"Text of (\w+)", html) == ["a", "p", "p1", "p1", "p2", "r", "q"]
    # The first level stays open.
    assert (
        '<div class="flow-group flow-group-part"><p class="flow-group-label">'
        'Includes <span class="flow-group-steps">(steps 2–6)</span></p>'
    ) in html
    # A fold says what is inside: the first step, how many more, then where.
    assert (
        '<details class="flow-group flow-group-separate" id="flow-f-group-3">'
        '<summary class="flow-group-label">'
        '<span class="flow-group-kind">Starts separately:</span> '
        '<span class="flow-group-first">Text of p1</span> '
        '<span class="flow-group-more">and 1 more</span> '
        '<span class="flow-group-steps">(steps 3 and 4)</span></summary>'
        '<ul class="flow-branches">'
    ) in html
    # Step 5 follows step 2, with a fold between them.
    assert (
        '</details><p class="flow-via">from step '
        '<a class="flow-ref" href="#flow-f-step-2">2</a></p></li>'
        '<li class="flow-step" id="flow-f-step-5"'
    ) in html
    steps = _steps(html)
    # From inside the fold a reference leads to the step itself.
    assert 'joins step <a class="flow-ref" href="#flow-f-step-3">3</a>' in steps[3]
    # From outside, to the fold, until the script points it at the step.
    assert (
        'joins steps <a class="flow-ref" href="#flow-f-step-1">1</a> and '
        '<a class="flow-ref" href="#flow-f-group-3" data-step="flow-f-step-3">3</a>'
    ) in steps[5]


class FiveProcesses:
    """1 starts 2 to 6 as separate processes; 1 also proceeds to 7."""

    outgoing = {
        "stm_1": [
            *(FlowLink(f"stm_{n}", "triggers", None) for n in range(2, 7)),
            FlowLink("stm_7", "proceeds", None),
        ],
    }

    def statement(self, statement_id: str) -> FlowStatement | None:
        return FlowStatement("event", f"Text of {statement_id}")

    def links(self, statement_id: str) -> list[FlowLink]:
        return self.outgoing.get(statement_id, [])


def test_a_step_starting_five_processes_says_so_once_and_still_leads_on():
    html = _flow_html(FiveProcesses(), "stm_1")
    steps = _steps(html)
    assert steps[0].startswith(' flow-to-then" id="flow-f-step-1"')
    assert html.count("flow-group-label") == 1
    assert 'Starts separately <span class="flow-group-steps">(steps 2–6)</span>' in html
    assert html.count('<li class="flow-branch') == 5
    # None of the five follows the one above it.
    assert html.count('<li class="flow-branch flow-branch-apart">') == 4
    assert html.count('<p class="flow-from">from step ') == 4
    # The five draw no line between them: none leads to the next.
    assert all(" flow-to-" not in step.split(">")[0] for step in steps[1:])
    assert steps[-1].startswith('" id="flow-f-step-7"')


def test_an_image_address_can_be_given_by_media_id():
    body = "![Dialog](media:med_000000000001) ![Gone](media:med_000000000002)\n"
    assert render_markdown(
        body, media_urls={"med_000000000001": "../media/a b.png"}
    ) == ('<p><img src="../media/a b.png" alt="Dialog" loading="lazy"> Gone</p>\n')


def test_a_frame_renders_the_lead_apart_from_the_sections():
    lead, sections = render_frame(BODY, links={"Invoice": LinkTarget(href="i.html")})
    assert (
        lead
        == '<p>An <a class="concept-link" href="i.html">Invoice</a> is a bill.</p>\n'
    )
    assert sections.startswith('<h2 id="how-invoices-are-paid">How <a class=')
    assert lead + sections == render_markdown(
        BODY, links={"Invoice": LinkTarget(href="i.html")}
    )
    assert render_frame("Only a lead.") == ("<p>Only a lead.</p>\n", "")


def test_placement_without_a_drawing_is_its_name():
    html = render_markdown("```flow\n<b>missing</b>\n```\n")
    assert html == "<p>&lt;b&gt;missing&lt;/b&gt;</p>\n"


BODY = (
    "An [[Invoice]] is a bill.\n\n"
    "## How [[Invoice|invoices]] are *paid*\n\n"
    "By card.\n\n"
    "```\n## not a heading\n```\n\n"
    "### Detail\n\n"
    "## Limits & `quotas`\n\n"
    "Ten.\n\n"
    "## Limits & `quotas`\n\n"
    "> ## quoted\n\n"
    "## !!!\n"
)


def test_body_splits_into_lead_and_sections_with_stable_anchors():
    frame = split_sections(BODY)
    assert frame.lead == "An [[Invoice]] is a bill.\n\n"
    assert [(section.title, section.anchor) for section in frame.sections] == [
        ("How invoices are paid", "how-invoices-are-paid"),
        ("Limits & quotas", "limits-quotas"),
        ("Limits & quotas", "limits-quotas-2"),
        ("!!!", "section"),
    ]
    assert frame.sections[0].body == (
        "\nBy card.\n\n```\n## not a heading\n```\n\n### Detail\n\n"
    )
    assert frame.sections[2].body == "\n> ## quoted\n\n"
    assert contents(BODY) == [
        (section.title, section.anchor) for section in frame.sections
    ]
    assert split_sections("No headings.").sections == []
    assert split_sections("No headings.").lead == "No headings."


def test_rendered_section_headings_carry_their_anchors():
    html = render_markdown(BODY)
    assert '<h2 id="how-invoices-are-paid">How invoices are <em>paid</em></h2>' in html
    assert '<h2 id="limits-quotas">' in html and '<h2 id="limits-quotas-2">' in html
    assert "<h3>Detail</h3>" in html
    assert "<h2>quoted</h2>" in html


def test_an_image_placeholder_renders_as_a_marked_figure_with_its_description():
    body = (
        "A member opens the export dialog.\n\n"
        "![The export dialog with <CSV> selected](image-wanted)\n\n"
        "Then see ![the queued status badge](image-wanted) in the list.\n"
    )

    html = render_markdown(body)

    assert (
        '<figure class="image-wanted">'
        '<span class="image-wanted-label">Image wanted</span> '
        "<figcaption>The export dialog with &lt;CSV&gt; selected</figcaption></figure>"
    ) in html
    assert "<p><figure" not in html
    # Inside a sentence a figure would break the paragraph.
    assert (
        '<span class="image-wanted"><span class="image-wanted-label">Image wanted'
        "</span> <span>the queued status badge</span></span>"
    ) in html
    assert "<img" not in html


def test_image_placeholders_are_listed_with_their_section():
    body = (
        "![The workspace settings page](image-wanted)\n\n"
        "## How is an export requested?\n\n"
        "![The export dialog with\nCSV selected](image-wanted)\n\n"
        "![A real screenshot](media:med_0123456789ab)\n\n"
        "`![not a placeholder](image-wanted)`\n\n"
        "## What can go wrong?\n\n"
        "Read on. ![The failed export banner](image-wanted)\n"
    )

    assert image_placeholders(body) == [
        ImagePlaceholder("The workspace settings page", None),
        ImagePlaceholder(
            "The export dialog with CSV selected", "How is an export requested?"
        ),
        ImagePlaceholder("The failed export banner", "What can go wrong?"),
    ]
    assert image_placeholders("No picture is wanted here.") == []


def test_the_lead_paragraph_is_plain_text_cut_to_a_word_limit():
    body = (
        "An [[Invoice|invoice]] bills a `workspace`\nfor one period.\n\n"
        "A second paragraph.\n\n## Sections\n\nMore.\n"
    )

    assert lead_paragraph(body) == "An invoice bills a workspace for one period."
    assert lead_paragraph(body, max_words=3) == "An invoice bills…"
    assert lead_paragraph("## Only sections\n\nText.\n") == ""


class Conditional:
    """An export proceeds to running when (SSO or Team) and not overdue, and
    the owner is told on failure when any of two holds; running leads on."""

    outgoing = {
        "stm_req": [
            FlowLink(
                "stm_run",
                "proceeds",
                {
                    "op": "and",
                    "of": [
                        {
                            "op": "or",
                            "of": [
                                {"statement_id": "stm_sso"},
                                {"statement_id": "stm_team"},
                            ],
                        },
                        {"op": "not", "of": [{"statement_id": "stm_late"}]},
                    ],
                },
            ),
            FlowLink(
                "stm_told",
                "on-failure",
                {
                    "op": "or",
                    "of": [{"statement_id": "stm_sso"}, {"statement_id": "stm_late"}],
                },
            ),
        ],
        "stm_run": [FlowLink("stm_done", "proceeds", None)],
    }
    texts = {
        "stm_req": "An export is requested",
        "stm_run": "The export runs",
        "stm_told": "The owner is told",
        "stm_done": "The file is ready",
        "stm_sso": "SSO is on",
        "stm_team": "The plan is <Team>",
        "stm_late": "An invoice is overdue",
    }

    def statement(self, statement_id: str) -> FlowStatement | None:
        kind = (
            "state" if statement_id in ("stm_sso", "stm_team", "stm_late") else "event"
        )
        return FlowStatement(kind, self.texts[statement_id])

    def links(self, statement_id: str) -> list[FlowLink]:
        return self.outgoing.get(statement_id, [])


def test_a_condition_reads_as_words_and_nested_lists_without_quotes():
    html = _flow_html(Conditional(), "stm_req")
    assert "&quot;" not in html
    # The line to the next step says its condition under the step, a list
    # where it holds several.
    assert (
        '<div class="flow-via">then, <span class="flow-if">when all of:</span>'
        '<ul class="flow-if-list"><li><span class="flow-if">any of:</span>'
        '<ul class="flow-if-list"><li><span class="flow-if-text">SSO is on</span></li>'
        '<li><span class="flow-if-text">the plan is &lt;Team&gt;</span></li></ul></li>'
        '<li><span class="flow-if">not</span> '
        '<span class="flow-if-text">an invoice is overdue</span></li></ul></div>'
    ) in html
    # An outcome's label that ends in a list takes no colon after it.
    assert (
        '<div class="flow-label">on failure, <span class="flow-if">when any of:</span>'
        '<ul class="flow-if-list"><li><span class="flow-if-text">SSO is on</span></li>'
        '<li><span class="flow-if-text">an invoice is overdue</span></li></ul></div>'
        '<span class="flow-statement">The owner is told</span>'
    ) in html


def test_a_fold_summary_cuts_long_text_at_a_word():
    assert shortened("Short enough") == "Short enough"
    text = "The workspace owner receives an email that the export is ready to download"
    assert (
        shortened(text) == "The workspace owner receives an email that the export is…"
    )
    assert len(shortened(text)) <= 60
    assert shortened("x" * 80, 10) == "xxxxxxxxx…"
