"""The static site of a writing profile's documents: which files are written,
what a page holds, and what its audience keeps out."""

from __future__ import annotations

import io
import json
import re
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

import media_samples
from mycelium import (
    audiences,
    auth,
    docs_store,
    drafts_store,
    media_store,
    prompt_store,
    store,
)
from mycelium.audiences import Audience
from mycelium.docgen import autolink, flows, reads, render, site
from mycelium.docgen.schema import StoredFlow
from mycelium.http import create_app
from mycelium.http.authentication import AuthMiddleware
from test_docgen_reads import (  # noqa: F401 — `db` is a fixture
    EXTERNAL,
    INTERNAL,
    Corpus,
    _corpus,
    db,
)

PROFILE = "developer-reference"
PAGE = "Entity page"
REQUESTED = "A member requests a workspace export."


@pytest.fixture
def docs(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    yield conn
    conn.close()


def _concept(conn: sqlite3.Connection, name: str) -> str:
    """A concept every audience sees, since a visible statement names it."""
    entity = store.create_entity(conn, f'About "{name}" & more.')
    store.create_name(conn, name, entity)
    text = f"A {name} exists."
    statement = store.create_statement(conn, "state", text)
    store.audience_labels.set_label(
        conn, statement, [INTERNAL.id, EXTERNAL.id], source="ai", reason="r"
    )
    store.derive_mentions(conn, statement, text, store.build_name_index(conn))
    conn.commit()
    return entity


def _document(
    conn: sqlite3.Connection,
    corpus: Corpus,
    title: str,
    body: str = "Body.",
    *,
    anchor: str | None = None,
    template: str = PAGE,
    cited: dict[str, str] | None = None,
    links: dict[str, str] | None = None,
    placed: tuple[StoredFlow, ...] = (),
) -> str:
    statements = cited if cited is not None else {corpus.requested: REQUESTED}
    return docs_store.upsert_document(
        conn,
        slug=re.sub(r"\W+", "-", title.lower()).strip("-"),
        title=title,
        body=body,
        guideline_set=PROFILE,
        document_type=template,
        statement_ids=list(statements),
        cited_statements=statements,
        anchor_entity_id=anchor,
        concept_links=[
            {"name": name, "entity_id": entity}
            for name, entity in (links or {}).items()
        ],
        flows=[flow.model_dump(mode="json") for flow in placed],
    )


def _export(
    substrate: sqlite3.Connection,
    documents: sqlite3.Connection,
    out: Path,
    audience: Audience = INTERNAL,
) -> site.Site:
    return site.write_site(
        substrate, documents, profile=PROFILE, audience=audience, out=out
    )


NOTE = autolink.STUB_NOTE
SIDEBAR = '<nav class="sidebar" id="site-pages" aria-label="Pages">'


def _stub_link(href: str, name: str, title: str = "", attributes: str = "") -> str:
    """A link to a generated page as every place outside a body writes it."""
    tooltip = f"Not written yet — {title}" if title else "Not written yet"
    return (
        f'<a class="stub" href="{href}" title="{tooltip}"{attributes}>{name}{NOTE}</a>'
    )


def _between(html: str, start: str, end: str) -> str:
    return html.split(start, 1)[1].split(end, 1)[0]


FRAME = {
    "index.html",
    "images-wanted.html",
    "site-report.html",
    "site.css",
    "site.js",
    "search-index.js",
}


def _main(html: str) -> str:
    return _between(html, '<main id="main">\n', "</main>")


def _statement(conn: sqlite3.Connection, text: str) -> str:
    """A statement every audience sees, naming the concepts its text holds."""
    statement = store.create_statement(conn, "state", text)
    store.audience_labels.set_label(
        conn, statement, [INTERNAL.id, EXTERNAL.id], source="ai", reason="r"
    )
    store.derive_mentions(conn, statement, text, store.build_name_index(conn))
    conn.commit()
    return statement


def _search_index(out: Path) -> list[dict[str, object]]:
    script = (out / "search-index.js").read_text()
    assert script.startswith("window.SITE_SEARCH = ") and script.endswith(";\n")
    entries: list[dict[str, object]] = json.loads(
        script.removeprefix("window.SITE_SEARCH = ").removesuffix(";\n")
    )
    return entries


@pytest.fixture
def media_db() -> Iterator[sqlite3.Connection]:
    conn = media_store.connect(":memory:")
    media_store.migrate(conn)
    media_store.use_connection(conn)
    yield conn
    media_store.reset()
    conn.close()


def _image(conn: sqlite3.Connection, media_id: str) -> None:
    at = "2026-08-01T00:00:00.000Z"
    conn.execute(
        "INSERT INTO media_items (id, content_type, byte_size, sha256, "
        "content_updated_at, origin, created_at, updated_at) "
        "VALUES (?, 'image/png', 1, 'x', ?, 'uploaded', ?, ?)",
        (media_id, at, at, at),
    )
    media_store.blobs.put(conn, media_id, media_samples.png())
    conn.commit()


def test_an_index_a_page_per_document_and_one_stylesheet_are_written(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export", anchor=corpus.export)
    _document(docs, corpus, "CSV export", anchor=corpus.csv)
    _document(docs, corpus, "Exporting", template="How-to")
    docs_store.upsert_document(
        docs, slug="other", title="Other", body="B", guideline_set="support"
    )
    out = tmp_path / "site"

    written = _export(db, docs, out)

    assert written.left_out == ()
    assert set(written.files) == FRAME | {
        "Entity page/workspace-export.html",
        "Entity page/csv-export.html",
        "How-to/exporting.html",
    }
    assert {
        path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()
    } == set(written.files)
    index = (out / "index.html").read_text()
    assert '<link rel="stylesheet" href="site.css">' in index
    assert '<span class="template">How-to</span>' in _main(index)
    page = (out / "Entity page" / "csv-export.html").read_text()
    assert '<link rel="stylesheet" href="../site.css">' in page
    for html in (index, page):
        assert "http" not in html
    assert "prefers-color-scheme: dark" in (out / "site.css").read_text()


def test_a_single_template_is_not_named_in_the_index(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export")

    _export(db, docs, tmp_path / "site")

    assert 'class="template"' not in (tmp_path / "site" / "index.html").read_text()


def test_an_output_directory_holding_anything_is_refused(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export")
    out = tmp_path / "site"
    out.mkdir()
    (out / "old.html").write_text("earlier export")

    with pytest.raises(site.SiteRefused, match="not an empty directory"):
        _export(db, docs, out)

    assert [path.name for path in out.iterdir()] == ["old.html"]
    with pytest.raises(site.SiteRefused):
        _export(db, docs, out / "old.html")
    (out / "old.html").unlink()
    assert "index.html" in _export(db, docs, out).files


@pytest.mark.parametrize("template", ["../x", "a/b", "a\\b", "..", ".hidden", "a\tb"])
def test_a_template_name_that_is_not_one_file_name_is_refused(
    db,  # noqa: F811
    docs,
    tmp_path,
    template,
):
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export")
    _document(docs, corpus, "Invoices", template=template)
    out = tmp_path / "site"

    with pytest.raises(site.SiteRefused, match="'Invoices' cannot be exported"):
        _export(db, docs, out)

    assert not out.exists()
    assert not (tmp_path / "x").exists()


def test_a_slug_holding_a_separator_is_refused(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    document_id = _document(docs, corpus, "Workspace export")
    docs.execute(
        "UPDATE generated_documents SET slug = '../../escape' WHERE id = ?",
        (document_id,),
    )
    docs.commit()

    with pytest.raises(site.SiteRefused, match=re.escape("its slug, '../../escape'")):
        _export(db, docs, tmp_path / "site")


def test_an_ordinary_template_name_with_spaces_and_signs_exports(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export", template="How-to guide_2 (SSO)")

    written = _export(db, docs, tmp_path / "site")

    assert "How-to guide_2 (SSO)/workspace-export.html" in written.files


def test_the_breadcrumb_follows_the_parents_and_stops_at_a_loop(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    # csv export is part of workspace export, which is part of audit log,
    # which is part of csv export again.
    store.insert_entity_links(
        db,
        [
            (corpus.audit, corpus.export, "contains"),
            (corpus.csv, corpus.audit, "contains"),
        ],
    )
    db.commit()
    _document(docs, corpus, "Workspace export", anchor=corpus.export)
    _document(docs, corpus, "CSV export", anchor=corpus.csv)
    _document(docs, corpus, "Exporting")

    _export(db, docs, tmp_path / "site")

    page = (tmp_path / "site" / PAGE / "csv-export.html").read_text()
    assert _between(page, '<nav class="breadcrumb"', "</nav>").endswith(
        '<ol><li><a href="../index.html">Home</a></li>'
        "<li>audit log</li>"
        '<li><a href="../Entity%20page/workspace-export.html">workspace export</a>'
        '</li><li aria-current="page">CSV export</li></ol>'
    )
    unanchored = (tmp_path / "site" / PAGE / "exporting.html").read_text()
    assert _between(unanchored, '<nav class="breadcrumb"', "</nav>").endswith(
        '<ol><li><a href="../index.html">Home</a></li>'
        '<li aria-current="page">Exporting</li></ol>'
    )
    assert 'class="context"' not in unanchored


def test_a_page_runs_from_title_to_sources(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    drawing = flows.draw_flow(reads.StoreFlowReader(db), corpus.requested)
    assert drawing is not None
    flow = StoredFlow(
        name="request-to-download",
        title="From request to <download>",
        start=corpus.requested,
        drawing=drawing,
    )
    _document(
        docs,
        corpus,
        "Workspace export",
        "The lead.\n\n## How it runs\n\n```flow\nrequest-to-download\n```\n\n"
        "## Limits\n\nTen.\n",
        anchor=corpus.export,
        cited={corpus.requested: "A member asked for an export, as first reviewed."},
        placed=(flow,),
    )
    _document(docs, corpus, "CSV export", "Lead.\n\n## Only\n\nOne.\n")

    _export(db, docs, tmp_path / "site")

    page = (tmp_path / "site" / PAGE / "workspace-export.html").read_text()
    order = [
        page.index(part)
        for part in (
            '<nav class="breadcrumb"',
            # The rail sits beside the title, the fold under the lead.
            '<nav class="contents contents-rail"',
            "<h1>Workspace export</h1>",
            '<div class="lead">\n<p>The lead.</p>',
            '<details class="contents contents-fold">',
            '<dl class="context">',
            # The link to a section stands beside its heading, outside its name.
            '<div class="section-heading"><h2 id="how-it-runs">How it runs</h2>'
            '<a class="heading-anchor" href="#how-it-runs" '
            'aria-label="Link to section: How it runs">#</a></div>',
            "<figcaption>From request to &lt;download&gt;</figcaption>",
            '<div class="section-heading"><h2 id="limits">Limits</h2>'
            '<a class="heading-anchor" href="#limits"',
            '<details class="sources">',
            '<p class="to-top"><a href="#top">Back to top</a></p>',
        )
    ]
    assert order == sorted(order)
    listed = (
        '<li><a href="#how-it-runs">How it runs</a></li>'
        '<li><a href="#limits">Limits</a></li>'
    )
    # A rail on a wide screen and a fold, closed, on a narrow one: CSS shows
    # one, and neither needs the script.
    assert _between(page, '<nav class="contents contents-rail"', "</nav>") == (
        ' aria-label="Contents"><p class="contents-title">On this page</p>'
        f'<ol>{listed}<li class="to-top"><a href="#top">Back to top</a></li></ol>'
    )
    assert _between(page, '<details class="contents contents-fold">', "</details>") == (
        f'<summary>On this page</summary><nav aria-label="Contents"><ol>{listed}</ol>'
        "</nav>"
    )
    assert '<main id="main" class="with-contents">' in page
    # A step does not link to its source; the folded list shows the text the
    # revision stored, or else what the flow drew.
    assert 'href="#source-' not in page and "flow-source" not in page
    sources = _between(page, '<details class="sources">', "</details>")
    assert sources.startswith(
        f"<summary>Sources: {len(drawing.statement_ids)} statements</summary>"
    )
    assert (
        f'<li id="source-{corpus.requested}">'
        "A member asked for an export, as first reviewed.</li>"
    ) in sources
    assert (
        f'<li id="source-{corpus.queued}">The workspace export is queued.</li>'
        in sources
    )
    assert "<details open" not in page
    single = (tmp_path / "site" / PAGE / "csv-export.html").read_text()
    assert 'class="contents' not in single
    assert '<main id="main">' in single


def test_the_context_block_groups_the_concept_links_and_caps_them(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    workspace = _concept(db, "data region")
    archive = _concept(db, "archive")
    billing = _concept(db, "billing run")
    plans = [_concept(db, f"plan {number:02}") for number in range(10)]
    store.insert_entity_links(
        db,
        [
            (workspace, corpus.export, "contains"),
            (corpus.export, archive, "sub-type"),
            (corpus.invoice, corpus.export, "sub-type"),
            (billing, corpus.export, "depends-on"),
            (corpus.export, corpus.export, "uses"),
            *((corpus.export, plan, "uses") for plan in plans),
        ],
    )
    db.commit()
    _document(docs, corpus, "Workspace export", anchor=corpus.export)
    _document(docs, corpus, "CSV export", anchor=corpus.csv)

    _export(db, docs, tmp_path / "site")

    page = (tmp_path / "site" / PAGE / "workspace-export.html").read_text()

    def muted(name: str, note: str = "") -> str:
        """An entry, its note before the name and inside it."""
        return (
            '<li class="context-entry">'
            + (f'<span class="context-note">{note}</span> ' if note else "")
            + f'<span class="context-muted">{name}</span></li>'
        )

    def row(label: str, *entries: str) -> str:
        """A label's entries as a list of their own."""
        return (
            f'<div><dt>{label}</dt><dd><ul class="context-list">{"".join(entries)}'
            "</ul></dd></div>"
        )

    # Twelve of the sixteen links: the five of containment and kind, then the
    # others by name.
    assert _between(page, '<dl class="context">', "</dl>") == (
        row("Part of", muted("data region"))
        + row(
            "Contains",
            '<li class="context-entry">'
            '<a href="../Entity%20page/csv-export.html">csv export</a></li>',
        )
        + row("A kind of", muted("archive"))
        + row("Kinds", muted("invoice"))
        + row(
            "Related",
            muted("audit log", "uses"),
            # A type without words of its own reads from its name.
            muted("billing run", "depends on this"),
            *(muted(f"plan {number:02}", "uses") for number in range(6)),
        )
    )


def test_concept_links_lead_to_the_pages_of_this_export(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    _document(
        docs,
        corpus,
        "Workspace export",
        "A [[workspace export]] holds [[CSV|rows]] and each [[invoice]], next "
        "to the [[audit log]], [[rows]] and [[Ledgr]].\n",
        anchor=corpus.export,
        links={
            "workspace export": corpus.export,
            "CSV": corpus.csv,
            "invoice": corpus.invoice,
            "audit log": corpus.audit,
            # Merged away since: its name now belongs to the csv export.
            "rows": "ent_merged_away",
        },
    )
    store.create_name(db, "rows", corpus.csv)
    db.commit()
    _document(docs, corpus, "CSV export", anchor=corpus.csv)
    _document(docs, corpus, "Audit log", anchor=corpus.audit, template="How-to")
    # A page that is left out is not a place to link to.
    _document(
        docs, corpus, "Invoice", anchor=corpus.invoice, cited={"stm_gone": "Gone."}
    )

    written = _export(db, docs, tmp_path / "site")

    assert [item.title for item in written.left_out] == ["Invoice"]
    page = (tmp_path / "site" / PAGE / "workspace-export.html").read_text()
    csv = (
        '<a class="concept-link" href="../Entity%20page/csv-export.html" '
        'title="The export as comma-separated rows.">'
    )
    assert (
        f"<p>A workspace export holds {csv}rows</a> and each "
        '<a class="concept-link stub" href="../concept/invoice.html" '
        'title="Not written yet — A bill sent to a customer.">'
        f"invoice{NOTE}</a>, next to the "
        '<a class="concept-link" href="../How-to/audit-log.html" '
        'title="The record of who did what.">audit log</a>, '
        f"{csv}rows</a> and Ledgr.</p>"
    ) in page
    assert written.unmatched_links == (
        site.PageNote(
            "Workspace export", "Ledgr", "Entity%20page/workspace-export.html"
        ),
    )


def test_a_document_whose_statements_left_the_audience_is_left_out(
    db,  # noqa: F811
    docs,
    media_db,
    tmp_path,
):
    corpus = _corpus(db)
    drawing = flows.draw_flow(reads.StoreFlowReader(db), corpus.requested)
    assert drawing is not None
    flow = StoredFlow(name="steps", title="Steps", start="s", drawing=drawing)
    _document(docs, corpus, "Workspace export", anchor=corpus.export)
    _document(docs, corpus, "Failures", cited={corpus.failed: "It fails."})
    _document(docs, corpus, "Steps", "```flow\nsteps\n```\n", placed=(flow,))
    _document(docs, corpus, "Dialog", "![Gone](media:med_00000000000f)\n")

    written = _export(db, docs, tmp_path / "site", EXTERNAL)

    assert {item.title: item.reason for item in written.left_out} == {
        "Failures": (
            "it cites 1 statement that the audience External technical can no "
            f"longer see: {corpus.failed}"
        ),
        "Steps": (
            "its flow steps shows a statement that the audience External "
            "technical can no longer see"
        ),
        "Dialog": (
            "The document places media that no longer exists: med_00000000000f. "
            "Revise it before publishing."
        ),
    }
    assert set(written.files) == FRAME | {"Entity page/workspace-export.html"}
    assert "Failures" not in (tmp_path / "site" / "index.html").read_text()
    assert _export(db, docs, tmp_path / "internal").left_out == (written.left_out[0],)


def test_a_flow_naming_a_hidden_statement_it_did_not_draw_is_left_out(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    step = flows.Step(
        number=1,
        statement_id=corpus.queued,
        text="The workspace export is queued.",
        kind="event",
        continues=True,
        cut=[flows.CutStatement(statement_id=corpus.failed, text="It fails.")],
    )
    drawing = flows.Drawing(
        start=corpus.queued,
        steps=[step],
        conditions={},
        truncated=True,
        statement_ids=[corpus.queued],
        link_set=[],
    )
    flow = StoredFlow(name="cut", title="", start=corpus.queued, drawing=drawing)
    _document(docs, corpus, "Cut", "```flow\ncut\n```\n", placed=(flow,))

    written = _export(db, docs, tmp_path / "site", EXTERNAL)

    assert [item.title for item in written.left_out] == ["Cut"]


def test_an_external_audience_gets_no_hierarchy_and_no_unlabelled_media(
    db,  # noqa: F811
    docs,
    media_db,
    tmp_path,
):
    corpus = _corpus(db)
    _image(media_db, "med_000000000001")
    _document(
        docs,
        corpus,
        "Workspace export",
        "It holds a [[csv export]].\n",
        anchor=corpus.export,
        links={"csv export": corpus.csv},
    )
    _document(docs, corpus, "CSV export", anchor=corpus.csv)
    _document(docs, corpus, "Dialog", "![The dialog](media:med_000000000001)\n")

    written = _export(db, docs, tmp_path / "site", EXTERNAL)

    assert [item.title for item in written.left_out] == ["Dialog"]
    assert "media its audience may not see" in written.left_out[0].reason
    assert not (tmp_path / "site" / "media").exists()
    csv = (tmp_path / "site" / PAGE / "csv-export.html").read_text()
    assert _between(csv, '<nav class="breadcrumb"', "</nav>").endswith(
        '<ol><li><a href="../index.html">Home</a></li>'
        '<li aria-current="page">CSV export</li></ol>'
    )
    page = (tmp_path / "site" / PAGE / "workspace-export.html").read_text()
    assert 'class="context"' not in page + csv
    assert (
        '<p>It holds a <a class="concept-link" '
        'href="../Entity%20page/csv-export.html">csv export</a>.</p>'
    ) in page


def test_placed_media_is_copied_and_referenced_beside_the_pages(
    db,  # noqa: F811
    docs,
    media_db,
    tmp_path,
):
    corpus = _corpus(db)
    _image(media_db, "med_000000000001")
    _document(docs, corpus, "Dialog", "![The dialog](media:med_000000000001)\n")

    written = _export(db, docs, tmp_path / "site")

    assert "media/med_000000000001.png" in written.files
    assert (
        tmp_path / "site" / "media" / "med_000000000001.png"
    ).read_bytes() == media_samples.png()
    assert (
        '<img src="../media/med_000000000001.png" alt="The dialog" loading="lazy">'
        in (tmp_path / "site" / PAGE / "dialog.html").read_text()
    )


def test_hostile_text_is_escaped_everywhere(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    hostile = '<script>alert("x")</script> & co'
    escaped = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; co"
    tag = _concept(db, "<b>tag</b>")
    store.insert_entity_links(db, [(corpus.export, tag, "contains")])
    db.commit()
    _document(
        docs,
        corpus,
        hostile,
        f"{hostile} [[tag|<i>tag</i>]]\n\n## {hostile}\n\nA.\n\n## B\n\nB.\n",
        anchor=corpus.export,
        cited={corpus.requested: hostile},
        links={"tag": tag},
    )
    _document(docs, corpus, "Tag", anchor=tag)

    _export(db, docs, tmp_path / "site")

    [page_path] = (tmp_path / "site" / PAGE).glob("script*.html")
    page = page_path.read_text()
    index = (tmp_path / "site" / "index.html").read_text()
    assert "<script>alert" not in page + index
    assert "<b>" not in page and "<i>" not in page
    assert f"<title>{escaped} — Developer reference</title>" in page
    assert f"<h1>{escaped}</h1>" in page
    assert f">{escaped}</a></h2>" in index
    assert (
        'title="About &quot;&lt;b&gt;tag&lt;/b&gt;&quot; &amp; more.">'
        "&lt;i&gt;tag&lt;/i&gt;</a>"
    ) in page
    assert '<a href="../Entity%20page/tag.html">&lt;b&gt;tag&lt;/b&gt;</a>' in page
    assert f'<li id="source-{corpus.requested}">{escaped}</li>' in page


def _auto_linked(db: sqlite3.Connection, docs: sqlite3.Connection) -> Corpus:  # noqa: F811
    """A written page about the workspace export whose statements name the
    invoice and the audit log, neither of which has a page, and a written page
    about the csv export."""
    corpus = _corpus(db)
    store.create_name(db, "data export", corpus.export)
    store.create_name(db, "bill", corpus.invoice)
    db.commit()
    logged = _statement(db, "The audit log records each invoice.")
    _document(
        docs,
        corpus,
        "Workspace export",
        "A workspace export holds every invoice. Each invoice is a row.\n\n"
        "## What is recorded\n\nThe audit log and the invoice, as a csv export.\n\n"
        "## Limits\n\nTen a day.\n",
        anchor=corpus.export,
        cited={corpus.ready: "Ready.", logged: "Logged."},
    )
    _document(docs, corpus, "CSV export", "Rows.\n", anchor=corpus.csv)
    return corpus


def test_concept_names_are_linked_and_unwritten_concepts_get_a_stub(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    _auto_linked(db, docs)
    out = tmp_path / "site"

    written = _export(db, docs, out)

    invoice = (
        '<a class="concept-link stub" href="../concept/invoice.html" '
        'title="Not written yet — A bill sent to a customer.">'
    )
    audit = (
        '<a class="concept-link stub" href="../concept/audit-log.html" '
        f'title="Not written yet — The record of who did what.">audit log{NOTE}</a>'
    )
    page = (out / PAGE / "workspace-export.html").read_text()
    # Its own name is never linked, and the csv export is named by no
    # statement the page cites.
    assert (
        f"<p>A workspace export holds every {invoice}invoice{NOTE}</a>. "
        "Each invoice is a row.</p>"
    ) in page
    assert (
        f"<p>The {audit} and the {invoice}invoice{NOTE}</a>, as a csv export.</p>"
        in page
    )
    assert set(written.files) == FRAME | {
        "Entity page/workspace-export.html",
        "Entity page/csv-export.html",
        "concept/invoice.html",
        "concept/audit-log.html",
    }
    assert written.stubs == (
        site.StubCount("audit log", 1),
        site.StubCount("invoice", 1),
    )

    stub = _main((out / "concept" / "audit-log.html").read_text())
    assert stub == (
        '<nav class="breadcrumb" aria-label="Breadcrumb"><ol>'
        '<li><a href="../index.html">Home</a></li>'
        '<li aria-current="page">audit log</li></ol></nav>\n'
        "<h1>audit log</h1>\n"
        '<p class="stub-note">This page has not been written yet. What it shows '
        "is generated from the knowledge base.</p>\n"
        '<p class="stub-description">The record of who did what.</p>\n'
        '<dl class="context"><div><dt>Related</dt><dd><ul class="context-list">'
        '<li class="context-entry"><span class="context-note">used by</span> '
        '<a href="../Entity%20page/workspace-export.html">workspace export</a>'
        "</li></ul></dd></div></dl>\n"
        '<section class="known"><h2>What is known</h2><ul>'
        "<li>The audit log records each workspace export.</li>"
        "<li>The audit log records each invoice.</li></ul></section>\n"
        '<section class="linked-from"><h2>Linked from</h2><ul>'
        '<li><a href="../Entity%20page/workspace-export.html">Workspace export</a>'
        "</li></ul></section>\n"
    )
    assert (
        '<p class="also-called">Also called: bill</p>'
        in (out / "concept" / "invoice.html").read_text()
    )


def test_relation_lists_link_to_a_stub_only_where_one_was_generated(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _auto_linked(db, docs)
    region = _concept(db, "data region")
    store.insert_entity_links(
        db, [(corpus.audit, corpus.invoice, "uses"), (corpus.audit, region, "uses")]
    )
    db.commit()

    _export(db, docs, tmp_path / "site")

    stub = (tmp_path / "site" / "concept" / "audit-log.html").read_text()
    invoice = _stub_link(
        "../concept/invoice.html", "invoice", "A bill sent to a customer."
    )
    assert invoice in stub
    assert '<span class="context-muted">data region</span>' in stub
    # A footnote says what the looks of the names mean, when there are several.
    assert (
        '</dl>\n<p class="context-key">Solid outline: written page · dashed: not '
        "written yet · plain text: no page</p>\n"
    ) in stub
    page = (tmp_path / "site" / PAGE / "workspace-export.html").read_text()
    assert (
        '<span class="context-note">uses</span> '
        + _stub_link(
            "../concept/audit-log.html", "audit log", "The record of who did what."
        )
    ) in page
    assert not (tmp_path / "site" / "concept" / "data-region.html").exists()


def test_the_key_names_the_dotted_underline_where_text_links_to_a_stub(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _auto_linked(db, docs)
    _document(
        docs,
        corpus,
        "Billing",
        "Each invoice is sent.\n",
        cited={corpus.ready: "Ready."},
    )
    out = tmp_path / "site"

    _export(db, docs, out)

    page = (out / PAGE / "workspace-export.html").read_text()
    assert (
        '</dl>\n<p class="context-key">Solid outline: written page · dashed: not '
        "written yet · dotted underline in text: not written yet</p>\n"
    ) in page
    # Without a context block the key stands alone.
    billing = _main((out / PAGE / "billing.html").read_text())
    assert 'class="context"' not in billing
    assert (
        '<p class="context-key">Dotted underline in text: not written yet</p>\n'
        in billing
    )
    # No link to a page not written yet, no word about it.
    assert "Dotted underline" not in (out / PAGE / "csv-export.html").read_text()
    assert "dotted underline" not in (out / "concept" / "invoice.html").read_text()


def test_stub_file_names_do_not_collide(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    first = _concept(db, "Plan: A")
    second = _concept(db, "plan a")
    _document(
        docs,
        corpus,
        "Plans",
        "[[Plan: A]] and [[plan a]].\n",
        links={"Plan: A": first, "plan a": second},
    )

    written = _export(db, docs, tmp_path / "site")

    assert {path for path in written.files if path.startswith("concept/")} == {
        "concept/plan-a.html",
        "concept/plan-a-2.html",
    }
    # A name without a letter a file name can hold still gets one.
    assert site._slugs({"ent_b": "計画", "ent_a": "計画書"}) == {
        "ent_b": "concept",
        "ent_a": "concept-2",
    }


def test_an_external_stub_shows_no_description_and_no_relations(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    _auto_linked(db, docs)
    out = tmp_path / "site"

    _export(db, docs, out, EXTERNAL)

    page = (out / PAGE / "workspace-export.html").read_text()
    assert (
        '<a class="concept-link stub" href="../concept/invoice.html" '
        f'title="Not written yet">invoice{NOTE}</a>'
    ) in page
    stub = _main((out / "concept" / "invoice.html").read_text())
    assert "A bill sent" not in stub and 'class="context"' not in stub
    # "bill" is in no statement this audience sees, so it is not a name here.
    assert "Also called" not in stub
    known = _between(stub, '<section class="known"><h2>What is known</h2><ul>', "</ul>")
    assert known.count("<li>") == 3
    assert "This page has not been written yet." in stub


def test_a_stub_lists_ten_statements_naming_it_and_folds_the_rest(
    db,  # noqa: F811
    docs,
    tmp_path,
    monkeypatch,
):
    corpus = _corpus(db)
    sso = _concept(db, "single sign-on")
    for number in range(11):
        _statement(db, f"Single sign-on rule {number:02} holds.")
    _document(
        docs,
        corpus,
        "Login",
        "[[single sign-on]] signs members in.\n",
        links={"single sign-on": sso},
    )

    _export(db, docs, tmp_path / "site")

    stub = _main((tmp_path / "site" / "concept" / "single-sign-on.html").read_text())
    known = _between(
        stub, '<section class="known"><h2>What is known</h2>', "</section>"
    )
    # The concept's own statement, then the first nine of the rules.
    first = known.split("<details")[0]
    assert first.count("<li>") == site.MAX_STUB_STATEMENTS == 10
    assert "<li>A single sign-on exists.</li>" in first
    assert "rule 08" in first and "rule 09" not in first
    assert known.endswith(
        '<details class="more-statements"><summary>2 more statements name it'
        "</summary><ul><li>Single sign-on rule 09 holds.</li>"
        "<li>Single sign-on rule 10 holds.</li></ul></details>"
    )

    # Past the cap the rest are counted, not listed.
    monkeypatch.setattr(site, "MAX_STUB_LISTED", 11)
    _export(db, docs, tmp_path / "capped")
    stub = _main((tmp_path / "capped" / "concept" / "single-sign-on.html").read_text())
    assert (
        "<summary>2 more statements name it</summary>"
        "<ul><li>Single sign-on rule 09 holds.</li></ul>"
        '<p class="stub-statements">The first 11 of 12 statements are listed.</p>'
        "</details>"
    ) in stub


def test_the_home_page_is_a_tree_of_pages_in_the_sidebars_order(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _auto_linked(db, docs)
    region = _concept(db, "data region")
    store.insert_entity_links(db, [(region, corpus.invoice, "contains")])
    db.commit()
    _document(
        docs,
        corpus,
        "Invoice",
        "An *invoice* bills a customer, e.g. monthly. More follows.\n",
        anchor=corpus.invoice,
    )
    _document(docs, corpus, "Exporting", "## Steps\n\nOne.\n")
    _document(docs, corpus, "Zones", "Where data lives.\n")
    out = tmp_path / "site"

    _export(db, docs, out)

    assert _main((out / "index.html").read_text()) == (
        "<h1>Developer reference</h1>\n"
        # Pages under no other have no heading of their own.
        '<div class="home"><ul class="documents">'
        '<li><a href="Entity%20page/exporting.html">Exporting</a></li></ul>'
        # A written page with children is their heading, once.
        '<section class="page-group"><h2 class="group-title">'
        '<a href="Entity%20page/workspace-export.html">Workspace export</a></h2>'
        '<p class="summary">A workspace export holds every invoice.</p>'
        '<ul class="documents">'
        '<li><a href="Entity%20page/csv-export.html">CSV export</a> '
        '<span class="summary">Rows.</span></li></ul></section>'
        # The page after it in the sidebar comes after it here too.
        '<ul class="documents"><li><a href="Entity%20page/zones.html">Zones</a> '
        '<span class="summary">Where data lives.</span></li></ul>'
        # The parent has no page, so it is named in plain text.
        '<section class="page-group"><h2 class="group-title">'
        '<span class="parent">data region</span></h2>'
        '<ul class="documents">'
        '<li><a href="Entity%20page/invoice.html">Invoice</a> '
        '<span class="summary">An invoice bills a customer, e.g.</span></li>'
        "</ul></section></div>\n"
        '<details class="stubs"><summary>Not written yet <span class="count">(1)'
        '</span></summary><ul class="stub-list">'
        "<li>"
        + _stub_link(
            "concept/audit-log.html", "audit log", "The record of who did what."
        )
        + "</li></ul></details>\n"
    )
    sidebar = _between(
        (out / "index.html").read_text(),
        SIDEBAR,
        "</nav>",
    )
    assert sidebar == (
        '<ul class="documents">'
        '<li><a href="Entity%20page/exporting.html">Exporting</a></li>'
        '<li><a href="Entity%20page/workspace-export.html">Workspace export</a>'
        '<ul class="documents">'
        '<li><a href="Entity%20page/csv-export.html">CSV export</a></li></ul></li>'
        '<li><a href="Entity%20page/zones.html">Zones</a></li>'
        '<li><span class="parent">data region</span><ul class="documents">'
        '<li><a href="Entity%20page/invoice.html">Invoice</a></li></ul></li></ul>'
    )


def test_a_parent_without_a_written_page_is_a_sidebar_link_to_its_stub(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    region = _concept(db, "data region")
    store.insert_entity_links(db, [(region, corpus.invoice, "contains")])
    db.commit()
    _document(
        docs,
        corpus,
        "Invoice",
        "Kept in a [[data region]].\n",
        anchor=corpus.invoice,
        links={"data region": region},
    )
    out = tmp_path / "site"

    _export(db, docs, out)

    def sidebar(path: str) -> str:
        html = (out / path).read_text()
        return _between(html, SIDEBAR, "</nav>")

    assert sidebar("concept/data-region.html") == (
        '<ul class="documents"><li>'
        + _stub_link(
            "../concept/data-region.html",
            "data region",
            "About &quot;data region&quot; &amp; more.",
            attributes=' aria-current="page"',
        )
        + '<ul class="documents">'
        '<li><a href="../Entity%20page/invoice.html">Invoice</a></li></ul></li></ul>'
    )
    assert sidebar("Entity page/invoice.html") == (
        '<ul class="documents"><li>'
        + _stub_link(
            "../concept/data-region.html",
            "data region",
            "About &quot;data region&quot; &amp; more.",
        )
        + '<ul class="documents"><li><a href="../Entity%20page/'
        'invoice.html" aria-current="page">Invoice</a></li></ul></li></ul>'
    )


def test_the_page_tree_nests_deeper_and_survives_a_loop_of_parents(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    workspace = _concept(db, "workspace")
    invoices = _concept(db, "invoices")
    exports = _concept(db, "exports")
    store.insert_entity_links(
        db,
        [
            (workspace, invoices, "contains"),
            (invoices, exports, "contains"),
            (exports, workspace, "contains"),
            (corpus.export, corpus.audit, "contains"),
        ],
    )
    db.commit()
    for name, anchor in (
        ("Workspace", workspace),
        ("Invoices", invoices),
        ("Exports", exports),
        ("Audit log", corpus.audit),
    ):
        _document(docs, corpus, name, anchor=anchor)
    out = tmp_path / "site"

    _export(db, docs, out)

    page = (out / PAGE / "audit-log.html").read_text()
    sidebar = _between(page, SIDEBAR, "</nav>")
    # Each page once; the loop is cut at the first name.
    assert re.sub(r' href="[^"]*"', "", sidebar) == (
        '<ul class="documents">'
        '<li><a>Exports</a><ul class="documents"><li><a>Workspace</a>'
        '<ul class="documents"><li><a>Invoices</a></li></ul></li></ul></li>'
        # A parent without a written page, linked to its generated page when
        # it has one; here it has none.
        '<li><span class="parent">workspace export</span>'
        '<ul class="documents"><li><a aria-current="page">Audit log</a></li></ul>'
        "</li></ul>"
    )


def test_an_external_home_page_is_one_untitled_group(db, docs, tmp_path):  # noqa: F811
    _auto_linked(db, docs)

    _export(db, docs, tmp_path / "site", EXTERNAL)

    index = _main((tmp_path / "site" / "index.html").read_text())
    assert '<section class="page-group">' not in index
    assert "group-title" not in index


def test_every_page_carries_the_sidebar_and_marks_itself(db, docs, tmp_path):  # noqa: F811
    _auto_linked(db, docs)
    out = tmp_path / "site"

    written = _export(db, docs, out)

    marked = {
        "index.html": None,
        "images-wanted.html": None,
        "site-report.html": None,
        "Entity page/csv-export.html": (
            '<a href="../Entity%20page/csv-export.html" aria-current="page">'
            "CSV export</a>"
        ),
        "concept/invoice.html": None,
        "Entity page/workspace-export.html": (
            '<a href="../Entity%20page/workspace-export.html" aria-current="page">'
            "Workspace export</a>"
        ),
        "concept/audit-log.html": None,
    }
    assert set(marked) == {path for path in written.files if path.endswith(".html")}
    for path, current in marked.items():
        html = (out / path).read_text()
        root = "../" if "/" in path else ""
        sidebar = _between(html, SIDEBAR, "</nav>")
        assert sidebar.count("aria-current") == (0 if current is None else 1)
        assert current is None or current in sidebar
        assert f'<a href="{root}Entity%20page/csv-export.html"' in sidebar
        # Maintenance pages are in the footer, not among the reader's pages.
        assert "site-report.html" not in sidebar
        footer = _between(html, '<footer class="site-footer">', "</footer>")
        own = ' aria-current="page"'
        assert footer == (
            f'<p>Maintenance: <a href="{root}images-wanted.html"'
            f"{own if path == 'images-wanted.html' else ''}>Images wanted</a> · "
            f'<a href="{root}site-report.html"'
            f"{own if path == 'site-report.html' else ''}>Site report</a></p>"
        )
        assert (
            f'<a class="site-title" href="{root}index.html">Developer reference</a>'
            in html
        )
        # The checkbox folds the sidebar without the script, the button with it.
        assert '<input type="checkbox" id="sidebar-toggle"' in html
        assert (
            '<button type="button" class="sidebar-button" aria-expanded="false" '
            'aria-controls="site-pages" hidden>Pages</button>'
        ) in html
        # Without the script a search box would do nothing.
        assert '<div class="search" role="search" hidden>' in html
        assert (
            '<input id="search" type="search" placeholder="Search" '
            'aria-label="Search this site" autocomplete="off" role="combobox" '
            'aria-expanded="false" aria-autocomplete="list" '
            'aria-controls="search-results" aria-keyshortcuts="/">'
        ) in html
        assert (
            '<div id="search-panel" class="search-panel" hidden>'
            '<p id="search-count" class="search-count"></p>'
            '<ul id="search-results" class="search-results" role="listbox" '
            'aria-label="Search results"></ul></div>'
            '<p id="search-status" class="visually-hidden" role="status"></p>'
        ) in html
        assert '<a class="skip-link" href="#main">Skip to content</a>' in html
        assert '<main id="main"' in html
        assert html.endswith(
            f'<script src="{root}search-index.js"></script>'
            f'<script src="{root}site.js" data-root="{root}"></script>\n'
            "</body></html>\n"
        )
    assert "<title>Developer reference</title>" in (out / "index.html").read_text()
    assert (
        "<title>CSV export — Developer reference</title>"
        in (out / PAGE / "csv-export.html").read_text()
    )


def test_every_link_of_every_page_leads_to_a_file_of_the_site(
    db,  # noqa: F811
    docs,
    media_db,
    tmp_path,
):
    corpus = _auto_linked(db, docs)
    _image(media_db, "med_000000000001")
    _document(
        docs,
        corpus,
        "Dialog",
        "![The dialog](media:med_000000000001)\n\n## Wanted\n\n"
        "![The export dialog, open](image-wanted)\n",
        template="How-to",
    )
    out = tmp_path / "site"

    written = _export(db, docs, out)

    pages = [path for path in written.files if path.endswith(".html")]
    assert {path.count("/") for path in pages} == {0, 1}
    checked = 0
    for path in pages:
        html = (out / path).read_text()
        for target in re.findall(r'(?:href|src)="([^"#]+)(?:#[^"]*)?"', html):
            assert ":" not in target, target
            assert (out / path).parent.joinpath(unquote(target)).is_file(), (
                path,
                target,
            )
            checked += 1
    assert checked > 50


def _search_text(html: str) -> str:
    reader = site._Text()
    reader.feed(html)
    reader.close()
    (_anchor, _heading, text) = reader.sections[0]
    return " ".join("".join(text).split())


def test_search_text_ends_each_flow_statement_and_leaves_out_hidden_words():
    assert _search_text(
        f'<p>Turn on <a class="concept-link stub" href="sso.html">SSO{NOTE}</a>.</p>'
        '<figure class="flow-figure"><ol class="flow"><li><div class="flow-box">'
        '<span class="flow-statement">An invoice is sent</span></div>'
        '<p class="flow-via">then, <span class="flow-if">when</span> '
        '<span class="flow-if-text">payment fails</span></p></li>'
        '<li><div class="flow-box"><span class="flow-statement">The owner is told.'
        "</span></div></li></ol></figure>"
    ) == ("Turn on SSO. An invoice is sent. payment fails. The owner is told.")


def test_search_text_leaves_out_a_flows_key():
    assert _search_text(
        '<figure class="flow-figure"><ul class="flow-key" aria-label="Key">'
        '<li><span class="flow-key-line flow-key-then" aria-hidden="true"></span>'
        "then</li><li>other outcome</li></ul>"
        '<ol class="flow"><li><div class="flow-box"><span class="flow-statement">'
        "An invoice is sent</span></div></li></ol></figure>"
    ) == ("An invoice is sent.")


class _ExportFlow:
    """An export includes a job and an SSO check, and on failure, when it is
    large, tells the owner. The job starts two separate processes and, when
    scheduled, leads on to compression; each joins back."""

    texts = {
        "a": "A workspace export is requested",
        "p": "The export job starts",
        "p1": "Each invoice is written to the file",
        "p2": "The audit log records the export",
        "r": "The file is compressed.",
        "q": "SSO access is checked",
        "o": "The owner gets an email",
        "big": "the workspace holds over 1000 invoices",
        "due": "the export is scheduled",
    }
    outgoing = {
        "a": [
            flows.FlowLink("p", "contains", None),
            flows.FlowLink("q", "contains", None),
            flows.FlowLink("o", "on-failure", {"statement_id": "big"}),
        ],
        "p": [
            flows.FlowLink("p1", "triggers", None),
            flows.FlowLink("p2", "triggers", None),
            flows.FlowLink("r", "proceeds", {"statement_id": "due"}),
        ],
        "p1": [flows.FlowLink("a", "proceeds", None)],
        "p2": [flows.FlowLink("p1", "proceeds", None)],
        "r": [flows.FlowLink("a", "proceeds", None)],
        "q": [
            flows.FlowLink("a", "proceeds", None),
            flows.FlowLink("p1", "proceeds", None),
        ],
    }

    def statement(self, statement_id: str) -> flows.FlowStatement | None:
        return flows.FlowStatement("event", self.texts[statement_id])

    def links(self, statement_id: str) -> list[flows.FlowLink]:
        return self.outgoing.get(statement_id, [])


def test_search_text_keeps_only_what_a_flow_states():
    graph = _ExportFlow()
    drawing = flows.draw_flow(graph, "a")
    assert drawing is not None
    drawing.steps[0].more_outcomes = 2
    drawing.steps[-1].continues = True
    html = render.render_markdown(
        "Before.\n\n```flow\nexport\n```\n",
        flows={
            "export": StoredFlow(
                name="export", title="Exporting a workspace", start="a", drawing=drawing
            )
        },
    )
    # The flow has every kind of way-finding text a search should leave out.
    for shown in ("Includes", "Starts separately:", "and 1 more", "from step", "joins"):
        assert shown in html

    text = _search_text(html)

    assert text == (
        "Before. Exporting a workspace. A workspace export is requested. "
        "the workspace holds over 1000 invoices. The owner gets an email. "
        "The export job starts. the export is scheduled. The file is compressed. "
        "Each invoice is written to the file. The audit log records the export. "
        "SSO access is checked."
    )


def test_search_text_adds_no_full_stop_before_punctuation_of_its_own():
    assert _search_text(
        "<p>Exports run nightly</p><p>, then again.</p><p>Keep it in <code>.env"
        "</code>.</p>"
    ) == ("Exports run nightly, then again. Keep it in .env.")


def test_search_text_names_each_later_cells_column_and_ends_each_cell():
    assert _search_text(
        "<p>Roles are as follows.</p><table><thead><tr><th>Role</th>"
        "<th>Pays <code>invoices</code></th><th>Limit:</th></tr></thead><tbody>"
        "<tr><td>Owner</td><td>Yes</td><td>None.</td></tr>"
        "<tr><td>Member</td><td></td><td><em>10</em> exports</td></tr></tbody>"
        "</table><p>After.</p>"
    ) == (
        "Roles are as follows. Owner. Pays invoices: Yes. Limit: None. "
        "Member. Limit: 10 exports. After."
    )


def test_search_text_ends_each_list_item_once_and_nested_lists_too():
    assert _search_text(
        "<p>An export holds:</p><ul><li>Each <code>invoice</code></li>"
        '<li>The <a href="sso.html">SSO</a> log.</li>'
        "<li>Settings:<ol><li>Limits</li><li>Owners;</li></ol></li>"
        "<li>The plan<ul><li><p>Seats</p></li></ul></li></ul><p>After.</p>"
    ) == (
        "An export holds: Each invoice. The SSO log. Settings: Limits. Owners; "
        "The plan. Seats. After."
    )


def test_search_text_names_no_column_of_a_table_without_headers():
    assert _search_text(
        "<table><tbody><tr><td>Owner</td><td>Pays invoices</td></tr></tbody></table>"
    ) == ("Owner. Pays invoices.")


def test_the_search_index_holds_titles_headings_text_and_what_a_stub_shows(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    _auto_linked(db, docs)
    out = tmp_path / "site"

    _export(db, docs, out)

    entries = {str(entry["title"]): entry for entry in _search_index(out)}
    assert list(entries) == ["CSV export", "Workspace export", "audit log", "invoice"]
    # A concept's other names, as its pages show them, are found as its title.
    assert entries["Workspace export"] == {
        "title": "Workspace export",
        "href": "Entity%20page/workspace-export.html",
        "aliases": ["data export"],
        "sections": [
            {
                "anchor": "",
                "heading": "",
                "text": "A workspace export holds every invoice. Each invoice is a row.",
            },
            {
                "anchor": "what-is-recorded",
                "heading": "What is recorded",
                "text": "The audit log and the invoice, as a csv export.",
            },
            {"anchor": "limits", "heading": "Limits", "text": "Ten a day."},
        ],
    }
    assert entries["invoice"] == {
        "title": "invoice",
        "href": "concept/invoice.html",
        "stub": True,
        "aliases": ["bill"],
        "sections": [
            {"anchor": "", "heading": "", "text": "A bill sent to a customer."}
        ],
    }
    assert "aliases" not in entries["CSV export"]
    # An external stub shows no description and no other name, so neither is
    # found.
    external = tmp_path / "external"
    _export(db, docs, external, EXTERNAL)
    stubs = {
        str(entry["title"]): entry
        for entry in _search_index(external)
        if entry.get("stub")
    }
    assert stubs["invoice"]["sections"] == [] and "aliases" not in stubs["invoice"]
    script = (out / "site.js").read_text()
    assert "window.SITE_SEARCH" in script and "fetch(" not in script
    assert "http" not in script


def test_a_written_page_shows_its_other_names_and_when_it_was_written(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    _auto_linked(db, docs)
    out = tmp_path / "site"

    _export(db, docs, out)

    page = (out / PAGE / "workspace-export.html").read_text()
    assert (
        "<h1>Workspace export</h1>\n"
        '<p class="also-called">Also called: data export</p>\n'
        '<div class="lead">'
    ) in page
    [document] = [
        row
        for row in docs_store.list_documents(docs, limit=None)
        if row["title"] == "Workspace export"
    ]
    revision = docs_store.get_revision(docs, str(document["id"]), 1)
    assert revision is not None
    day = str(revision["created_at"])[:10]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
    sources = page.split('<details class="sources">', 1)[1]
    assert _between(sources, "</details>\n", "</footer>") == (
        f'<p class="revision-date">Written <time datetime="{day}">{day}</time></p>\n'
        '<p class="to-top"><a href="#top">Back to top</a></p>\n'
    )
    assert "Also called" not in (out / PAGE / "csv-export.html").read_text()
    assert "Report a problem" not in page


def test_a_feedback_address_is_filled_in_for_written_pages_and_stubs(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _auto_linked(db, docs)
    _document(docs, corpus, "Why & how?", "Body.\n")
    out = tmp_path / "site"

    site.write_site(
        db,
        docs,
        profile=PROFILE,
        audience=INTERNAL,
        out=out,
        feedback_url="https://tracker.example/new?title={title}&page={page}&x={other}",
    )

    def feedback(href: str) -> str:
        return (
            f'<p class="feedback"><a href="{href}">Report a problem with this page'
            "</a></p>\n"
        )

    assert (
        feedback(
            "https://tracker.example/new?title=Why%20%26%20how%3F"
            "&amp;page=Entity%20page%2Fwhy-how.html&amp;x={other}"
        )
        in (out / PAGE / "why-how.html").read_text()
    )
    assert (
        feedback(
            "https://tracker.example/new?title=audit%20log"
            "&amp;page=concept%2Faudit-log.html&amp;x={other}"
        )
        in (out / "concept" / "audit-log.html").read_text()
    )
    for path in ("index.html", "images-wanted.html", "site-report.html"):
        assert "Report a problem" not in (out / path).read_text()


@pytest.mark.parametrize(
    "template",
    ["javascript:alert('{title}')", "tracker.example/new?t={title}", "", "file:///x"],
)
def test_a_feedback_address_that_is_not_a_web_or_mail_address_is_refused(
    db,  # noqa: F811
    docs,
    tmp_path,
    template,
):
    _auto_linked(db, docs)
    out = tmp_path / "site"

    with pytest.raises(site.SiteRefused, match="http:, https: or mailto:"):
        site.write_site(
            db,
            docs,
            profile=PROFILE,
            audience=INTERNAL,
            out=out,
            feedback_url=template,
        )

    assert not out.exists()
    site.write_site(
        db,
        docs,
        profile=PROFILE,
        audience=INTERNAL,
        out=out,
        feedback_url="mailto:docs@example.test?subject={title}",
    )
    assert (
        'href="mailto:docs@example.test?subject=CSV%20export"'
        in (out / PAGE / "csv-export.html").read_text()
    )


def test_the_images_a_writer_asked_for_are_listed_with_page_and_section(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    _document(
        docs,
        corpus,
        "Workspace export",
        "![The export <dialog>, open](image-wanted)\n\n## Where it is\n\n"
        "In the menu ![the settings menu, expanded](image-wanted) at the top.\n\n"
        "| Format | Limit |\n|---|---|\n| CSV | 1 GB |\n",
    )
    out = tmp_path / "site"

    written = _export(db, docs, out)

    assert written.images_wanted == 2
    wanted = _main((out / "images-wanted.html").read_text())
    link = '<a href="Entity%20page/workspace-export.html'
    assert _between(wanted, "<tbody>", "</tbody>") == (
        f'<tr><td>{link}">Workspace export</a></td><td>Lead</td>'
        "<td>The export &lt;dialog&gt;, open</td></tr>"
        f'<tr><td>{link}#where-it-is">Workspace export</a></td>'
        "<td>Where it is</td><td>the settings menu, expanded</td></tr>"
    )
    page = (out / PAGE / "workspace-export.html").read_text()
    assert '<figure class="image-wanted">' in page
    # Every table, written or generated, scrolls in a box of its own.
    scrolling = (
        '<div class="table-scroll" role="region" aria-label="Table" tabindex="0">'
        "<table>"
    )
    for html in (page, wanted):
        assert html.count(scrolling) == html.count("<table>") == 1
        assert html.count("</table></div>") == 1


def test_the_report_and_the_summary_say_what_the_pages_reveal(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _auto_linked(db, docs)
    drawing = flows.draw_flow(reads.StoreFlowReader(db), corpus.requested)
    assert drawing is not None
    cut = StoredFlow(
        name="steps",
        title="From request to download",
        start=corpus.requested,
        drawing=drawing.model_copy(update={"truncated": True}),
    )
    _document(
        docs,
        corpus,
        "Exporting",
        "See [[Ledgr]] and [[Ledgr]] and the [[invoice]].\n\n```flow\nsteps\n```\n\n"
        "![The export dialog, open](image-wanted)\n",
        links={"invoice": corpus.invoice},
        placed=(cut,),
    )
    _document(docs, corpus, "Gone", cited={"stm_gone": "Gone."})
    out = tmp_path / "site"

    written = _export(db, docs, out)

    assert written.stubs == (
        site.StubCount("invoice", 2),
        site.StubCount("audit log", 1),
    )
    assert written.cut_flows == (
        site.PageNote(
            "Exporting", "From request to download", "Entity%20page/exporting.html"
        ),
    )
    assert written.unmatched_links == (
        site.PageNote("Exporting", "Ledgr", "Entity%20page/exporting.html"),
    )
    assert site.summary(written) == [
        "left out 'Gone': it cites 1 statement that the audience Internal "
        "technical can no longer see: stm_gone",
        "2 linked concepts without a written page; most linked: invoice (2 pages), "
        "audit log (1 page)",
        "1 image wanted, listed in images-wanted.html",
        "flow cut short by a limit on 'Exporting': From request to download",
        "concept link matching nothing on 'Exporting': Ledgr",
    ]
    report = _main((out / "site-report.html").read_text())
    exporting = '<a href="Entity%20page/exporting.html">Exporting</a>'
    for part in (
        "<tr><td>"
        + _stub_link("concept/invoice.html", "invoice", "A bill sent to a customer.")
        + "</td><td>2</td></tr><tr><td>"
        + _stub_link(
            "concept/audit-log.html", "audit log", "The record of who did what."
        )
        + "</td><td>1</td></tr>",
        '<p>1, listed in <a href="images-wanted.html">Images wanted</a>.</p>',
        "<tr><td>Gone</td><td>it cites 1 statement that the audience Internal "
        "technical can no longer see: stm_gone</td></tr>",
        f"<tr><td>{exporting}</td><td>From request to download</td></tr>",
        f"<tr><td>{exporting}</td><td>Ledgr</td></tr>",
    ):
        assert part in report


def test_an_export_with_nothing_to_report_says_none(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export")

    written = _export(db, docs, tmp_path / "site")

    assert site.summary(written) == []
    report = _main((tmp_path / "site" / "site-report.html").read_text())
    assert report.count("<p>None.</p>") == 4 and "<table>" not in report
    assert "<p>None.</p>" in (tmp_path / "site" / "images-wanted.html").read_text()


@pytest.fixture
def data_dir(tmp_path: Path) -> Iterator[Path]:
    """An instance's data directory holding the corpus and a profile that
    writes for the external audience."""
    path = tmp_path / "data"
    path.mkdir()
    substrate = store.connect(path / "mycelium.db")
    store.migrate(substrate)
    corpus = _corpus(substrate)
    substrate.close()
    documents = docs_store.connect(path / "mycelium-drafts.db")
    docs_store.migrate(documents)
    _document(documents, corpus, "Workspace export", anchor=corpus.export)
    _document(documents, corpus, "Failures", cited={corpus.failed: "It fails."})
    documents.close()
    prompts = prompt_store.connect(path / "mycelium-prompts.db")
    prompt_store.migrate(prompts)
    audiences.seed(prompts)
    for slot, text in ((PAGE, "One page per concept."), ("audience", EXTERNAL.id)):
        prompt_store.save(
            prompts, type="guideline-set", name=f"{PROFILE}/{slot}", text=text
        )
    prompts.close()
    media = media_store.connect(path / media_store.DB_NAME)
    media_store.migrate(media)
    media.close()
    yield path
    media_store.reset()


def _run(monkeypatch: pytest.MonkeyPatch, data_dir: Path, *arguments: str) -> None:
    from mycelium import __main__

    monkeypatch.setattr(
        "sys.argv", ["mycelium", "--data-dir", str(data_dir), "docs-site", *arguments]
    )
    __main__.main()


def test_the_command_exports_for_the_profiles_audience_and_names_what_it_left_out(
    data_dir, tmp_path, monkeypatch, capsys
):
    out = tmp_path / "site"

    _run(monkeypatch, data_dir, "--profile", PROFILE, "--out", str(out))

    printed = capsys.readouterr().err
    assert "left out 'Failures': it cites 1 statement that the audience" in printed
    assert f"wrote 7 files to {out}; see site-report.html" in printed
    assert (out / PAGE / "workspace-export.html").exists()
    assert not (out / PAGE / "failures.html").exists()


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        (PROFILE, "is not an empty directory"),
        ("support", "There is no writing profile named 'support'"),
    ],
)
def test_the_command_stops_with_a_reason_and_writes_nothing(
    data_dir, tmp_path, monkeypatch, capsys, profile, message
):
    out = tmp_path / "site"
    out.mkdir()
    if profile == PROFILE:
        (out / "kept.txt").write_text("kept")
    before = sorted(path.name for path in out.iterdir())

    with pytest.raises(SystemExit) as stopped:
        _run(monkeypatch, data_dir, "--profile", profile, "--out", str(out))

    assert stopped.value.code == 1
    printed = capsys.readouterr().err
    assert printed.startswith("no site written: ") and message in printed
    assert sorted(path.name for path in out.iterdir()) == before


def test_the_command_passes_the_feedback_address_and_refuses_a_bad_one(
    data_dir, tmp_path, monkeypatch, capsys
):
    out = tmp_path / "site"

    with pytest.raises(SystemExit) as stopped:
        _run(
            monkeypatch,
            data_dir,
            "--profile",
            PROFILE,
            "--out",
            str(out),
            "--feedback-url",
            "javascript:void(0)",
        )

    assert stopped.value.code == 1 and not out.exists()
    assert "no site written: The feedback address" in capsys.readouterr().err
    _run(
        monkeypatch,
        data_dir,
        "--profile",
        PROFILE,
        "--out",
        str(out),
        "--feedback-url",
        "https://tracker.example/new?page={page}",
    )
    assert (
        'href="https://tracker.example/new?page=Entity%20page%2Fworkspace-export.html"'
        in (out / PAGE / "workspace-export.html").read_text()
    )


def test_the_site_title_is_given_or_the_profile_name_made_readable(
    data_dir, tmp_path, monkeypatch
):
    assert site.readable_title("developer-reference") == "Developer reference"
    assert site.readable_title("support_api-v2") == "Support api v2"
    out = tmp_path / "site"

    _run(
        monkeypatch,
        data_dir,
        "--profile",
        PROFILE,
        "--out",
        str(out),
        "--title",
        "Invoicing <docs>",
    )

    index = (out / "index.html").read_text()
    page = (out / PAGE / "workspace-export.html").read_text()
    assert "<title>Invoicing &lt;docs&gt;</title>" in index
    assert "<h1>Invoicing &lt;docs&gt;</h1>" in index
    assert (
        '<a class="site-title" href="../index.html">Invoicing &lt;docs&gt;</a>' in page
    )
    assert "<title>Workspace export — Invoicing &lt;docs&gt;</title>" in page


def test_search_text_keeps_what_a_flow_states_apart_and_leaves_out_the_rest(
    db,  # noqa: F811
    docs,
    tmp_path,
):
    corpus = _corpus(db)
    # A condition written without a full stop, as a label's colon follows it.
    sso = _statement(db, "SSO is on")
    receipt = _statement(db, "A receipt is stored.")
    rows = _statement(db, "The rows are written.")
    checked = _statement(db, "The rows are checked.")
    archive = _statement(db, "The archive is zipped.")
    db.execute(
        "UPDATE statements SET kind = 'event' WHERE id IN (?, ?, ?)",
        (rows, checked, archive),
    )
    store.insert_links(
        db,
        [
            (corpus.ready, receipt, "establishes", {"statement_id": sso}),
            (corpus.queued, rows, "contains", None),
            (rows, checked, "proceeds", None),
            (corpus.queued, archive, "contains", {"statement_id": sso}),
        ],
    )
    db.commit()
    drawing = flows.draw_flow(reads.StoreFlowReader(db), corpus.requested)
    assert drawing is not None
    flow = StoredFlow(
        name="steps", title="From request", start=corpus.requested, drawing=drawing
    )
    _document(
        docs,
        corpus,
        "Workspace export",
        "Lead.\n\n## How it runs\n\n```flow\nsteps\n```\n",
        placed=(flow,),
    )
    out = tmp_path / "site"

    _export(db, docs, out)

    page = (out / PAGE / "workspace-export.html").read_text()
    key = _between(page, '<ul class="flow-key" aria-label="Key">', "</ul>")
    assert "depends on a condition or an outcome" in key and "other outcome" in key
    [text] = [
        section["text"]
        for entry in _search_index(out)
        for section in entry["sections"]  # type: ignore[attr-defined]
        if section["anchor"] == "how-it-runs"
    ]
    assert text.startswith("From request. A member requests a workspace export.")
    for part in (
        "SSO is on. The archive is zipped.",
        "The rows are written.",
        "SSO is on. A receipt is stored.",
    ):
        assert part in text
    for wrong in (
        *(".:", " ,", "..", "depends on a condition", "other outcome"),
        *("Includes", "(steps", "outcome,", "result,", "when "),
    ):
        assert wrong not in text


def test_the_archive_holds_the_files_the_export_writes(db, docs, tmp_path):  # noqa: F811
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export")
    out = tmp_path / "site"
    _export(db, docs, out)

    files, _ = site.build_site(db, docs, profile=PROFILE, audience=INTERNAL)
    packed = site.archive(files)

    with zipfile.ZipFile(io.BytesIO(packed)) as bundle:
        unpacked = {name: bundle.read(name) for name in bundle.namelist()}
        modes = {entry.external_attr >> 16 for entry in bundle.infolist()}
    assert unpacked == {
        path.relative_to(out).as_posix(): path.read_bytes()
        for path in out.rglob("*")
        if path.is_file()
    }
    assert modes == {0o644}
    assert site.archive(files) == packed


def test_an_admin_downloads_the_site_and_a_writer_does_not(
    db,  # noqa: F811
    docs,
    monkeypatch,
):
    corpus = _corpus(db)
    _document(docs, corpus, "Workspace export")
    role = "admin"

    async def resolve(*_):
        return auth.Principal(id="fixture", name="Fixture", role=role, type="human")

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    monkeypatch.setattr(store, "substrate_connection", lambda: db)
    monkeypatch.setattr(drafts_store, "connection", lambda: docs)
    monkeypatch.setattr(site, "profile_audience", lambda _profile: INTERNAL)
    client = TestClient(create_app())
    address = f"/api/documentation/sites/{PROFILE}"

    response = client.get(address, params={"title": "Acme handbook"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f"{PROFILE}-site.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert "Acme handbook" in bundle.read("index.html").decode()
    refused = client.get(address, params={"feedback_url": "javascript:alert(1)"})
    assert refused.status_code == 400
    assert "http:, https: or mailto:" in refused.json()["detail"]
    role = "writer"
    assert client.get(address).status_code == 403
