"""Concept names in a rendered body become links: where a name is found, how
often it is linked, and what is left alone."""

from __future__ import annotations

import pytest

from mycelium.docgen.autolink import STUB_NOTE, Concept, exact_case, link_concepts
from mycelium.docgen.render import LinkTarget, render_markdown

INVOICE = Concept("ent_invoice", ("invoice", "bill"), "invoice.html")
EXPORT = Concept("ent_export", ("workspace export",), "export.html")
WORKSPACE = Concept("ent_workspace", ("Workspace",), "workspace.html")
SSO = Concept("ent_sso", ("SSO", "single sign-on"), "concept/sso.html", stub=True)
ALL = (INVOICE, EXPORT, WORKSPACE, SSO)


def _linked(markdown: str, concepts: tuple[Concept, ...] = ALL) -> str:
    return link_concepts(render_markdown(markdown), concepts).html.strip()


def _a(concept: Concept, text: str) -> str:
    if concept.stub:
        return (
            f'<a class="concept-link stub" href="{concept.href}" '
            f'title="Not written yet">{text}{STUB_NOTE}</a>'
        )
    return f'<a class="concept-link" href="{concept.href}">{text}</a>'


def test_a_name_is_linked_at_its_first_occurrence_in_the_lead_and_each_section():
    html = link_concepts(
        render_markdown(
            "An invoice is sent. The invoice is paid.\n\n"
            "## Paying\n\nAn invoice is paid. Each invoice once.\n\n"
            "## Voiding\n\nNothing here.\n\n### Detail\n\nAn invoice is void.\n"
        ),
        ALL,
    )

    assert html.concept_ids == {INVOICE.id}
    assert html.html == (
        f"<p>An {_a(INVOICE, 'invoice')} is sent. The invoice is paid.</p>\n"
        '<h2 id="paying">Paying</h2>\n'
        f"<p>An {_a(INVOICE, 'invoice')} is paid. Each invoice once.</p>\n"
        '<h2 id="voiding">Voiding</h2>\n<p>Nothing here.</p>\n'
        "<h3>Detail</h3>\n"
        f"<p>An {_a(INVOICE, 'invoice')} is void.</p>\n"
    )


def test_the_longest_name_wins_and_claims_its_words():
    assert _linked("A workspace export leaves the Workspace.") == (
        f"<p>A {_a(EXPORT, 'workspace export')} leaves the "
        f"{_a(WORKSPACE, 'Workspace')}.</p>"
    )
    # The second mention of the longer name is not a place to link the shorter.
    assert _linked("A Workspace Export, then a Workspace Export.") == (
        f"<p>A {_a(EXPORT, 'Workspace Export')}, then a Workspace Export.</p>"
    )


@pytest.mark.parametrize(
    ("text", "linked"),
    [
        ("Two invoices.", "invoices"),
        ("(invoice)", "invoice"),
        ("invoice, then", "invoice"),
        ("The invoice's total", "invoice"),
        ("an invoice-level setting", "invoice"),
        ("pre-invoice", "invoice"),
        ("Three workspace exportes.", "workspace exportes"),
    ],
)
def test_a_name_is_found_as_whole_words_with_a_plural_ending(text, linked):
    assert f">{linked}</a>" in _linked(text)


@pytest.mark.parametrize(
    "text",
    [
        "It is invoiced.",
        "A reinvoice.",
        "An invoicer.",
        "invoice2",
        "billing",
        "_bill_x",
    ],
)
def test_a_name_inside_a_longer_word_is_left_alone(text):
    assert "<a" not in _linked(text)


def test_a_short_or_lower_case_single_word_is_matched_only_as_stored():
    assert [exact_case(name) for name in ("flow", "Plan", "SSO", "Flows")] == [
        True,
        True,
        True,
        False,
    ]
    assert not exact_case("Workspace") and not exact_case("audit log")
    # "invoice" is stored in lower case and "SSO" is short: each as stored.
    assert "<a" not in _linked("Invoice totals. Also sso.")
    assert _linked("With SSOs on.") == f"<p>With {_a(SSO, 'SSOs')} on.</p>"
    # Longer capitalised names and names of several words ignore case.
    assert _linked("a workspace with Single Sign-On") == (
        f"<p>a {_a(WORKSPACE, 'workspace')} with {_a(SSO, 'Single Sign-On')}</p>"
    )


def test_a_name_in_emphasis_or_split_by_a_line_break_is_linked():
    assert _linked("A **workspace export** and an *invoice*.") == (
        f"<p>A <strong>{_a(EXPORT, 'workspace export')}</strong> and an "
        f"<em>{_a(INVOICE, 'invoice')}</em>.</p>"
    )
    broken = _a(EXPORT, "workspace\nexport")
    assert _linked("Start a workspace\nexport now.") == f"<p>Start a {broken} now.</p>"


def test_code_headings_links_and_placeholders_are_left_alone():
    markdown = (
        "Call `invoice` or [an invoice](https://example.test/invoice).\n\n"
        "## The invoice\n\n### An invoice heading\n\n"
        "```\ninvoice\n```\n\n    invoice\n\n"
        "![An invoice in the list](image-wanted)\n\n"
        "Inline ![the invoice as a row](image-wanted) here.\n"
    )

    assert link_concepts(render_markdown(markdown), ALL).html == render_markdown(
        markdown
    )


def test_a_table_is_linked_in_its_cells_but_not_its_header():
    html = _linked("| invoice | Workspace |\n|---|---|\n| invoice | none |\n")

    assert "<th>invoice</th>" in html and "<th>Workspace</th>" in html
    assert f"<td>{_a(INVOICE, 'invoice')}</td>" in html


def test_a_link_the_writer_placed_is_its_sections_link_wherever_it_stands():
    html = link_concepts(
        render_markdown(
            "An invoice, then [[bill|the bill]] and [[SSO]].\n\n## Next\n\nAn invoice.\n",
            links={
                "bill": LinkTarget(href=INVOICE.href),
                "SSO": LinkTarget(href=SSO.href),
            },
        ),
        ALL,
    )

    assert html.concept_ids == {INVOICE.id, SSO.id}
    assert html.html == (
        f"<p>An invoice, then {_a(INVOICE, 'the bill')} and {_a(SSO, 'SSO')}.</p>\n"
        f'<h2 id="next">Next</h2>\n<p>An {_a(INVOICE, "invoice")}.</p>\n'
    )


def test_a_concept_without_an_address_is_never_linked_but_claims_its_names():
    own = Concept("ent_export", ("workspace export",), None)

    html = link_concepts(
        render_markdown("A workspace export of a Workspace."), (own, WORKSPACE)
    )

    assert html.concept_ids == {WORKSPACE.id}
    assert html.html == (
        f"<p>A workspace export of a {_a(WORKSPACE, 'Workspace')}.</p>\n"
    )


def test_a_name_two_concepts_share_is_not_linked():
    other = Concept("ent_other", ("Invoice", "receipt"), "other.html")

    assert _linked("An invoice and a receipt.", (INVOICE, other)) == (
        f"<p>An invoice and a {_a(other, 'receipt')}.</p>"
    )


def test_text_is_escaped_as_it_was_and_a_description_becomes_the_tooltip():
    markdown = 'A <b>"bold"</b> & it\'s `<code>` and an invoice.\n'
    described = Concept(
        "ent_invoice", ("invoice",), "a b.html", description='A "bill".'
    )

    html = link_concepts(render_markdown(markdown), (described,)).html

    assert html == render_markdown(markdown).replace(
        "invoice",
        '<a class="concept-link" href="a b.html" title="A &quot;bill&quot;.">'
        "invoice</a>",
    )
    assert link_concepts(render_markdown(markdown), ()).html == render_markdown(
        markdown
    )


def test_a_link_to_a_stub_says_so_in_hidden_text_and_its_tooltip():
    described = Concept(
        "ent_sso", ("SSO",), "concept/sso.html", stub=True, description="Sign-in."
    )
    opened = (
        '<a class="concept-link stub" href="concept/sso.html" '
        'title="Not written yet — Sign-in.">'
    )
    written = render_markdown(
        "Turn on [[SSO|single sign-on]]. SSO again.",
        links={"SSO": LinkTarget(href="concept/sso.html")},
    )

    assert _linked("Turn on SSO.", (described,)) == (
        f"<p>Turn on {opened}SSO{STUB_NOTE}</a>.</p>"
    )
    assert link_concepts(written, (described,)).html.strip() == (
        f"<p>Turn on {opened}single sign-on{STUB_NOTE}</a>. SSO again.</p>"
    )
