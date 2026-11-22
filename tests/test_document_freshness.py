"""Whether a generated document still says what its cited statements say."""

from __future__ import annotations

import json

import pytest

from mycelium import (
    doc_runs,
    docs_store,
    document_freshness,
    drafts_store,
    media_store,
    store,
)
from mycelium.docgen import flows, loop
from mycelium.docgen.schema import FlowDefinition, StoredFlow
from mycelium.document_freshness import (
    FlowChange,
    Freshness,
    MediaChange,
    StatementChange,
    _Cited,
    assess,
    assess_media,
)
from mycelium.server import documentation
from test_docgen_reads import (  # noqa: F401 — `db` is a fixture
    EXTERNAL,
    INTERNAL,
    Corpus,
    _context,
    _corpus,
    db,
)


def test_assess_reports_each_kind_of_change():
    cited = {"a": "same", "b": "before", "c": "merged away", "d": "gone"}
    current = {"a": "same", "b": "after", "e": "survivor"}

    result = assess(cited, current, {"c": "e"})

    assert result == Freshness(
        "out_of_date",
        (
            StatementChange("b", "edited", "before", "after"),
            StatementChange("c", "merged", "merged away", "survivor", "e"),
            StatementChange("d", "deleted", "gone", None),
        ),
    )
    assert assess({"a": "same"}, current, {}) == Freshness("current")
    assert assess(None, current, {}) == Freshness("unknown")


@pytest.fixture
def connections(tmp_path):
    substrate = store.connect(
        tmp_path / "mycelium.db", history_path=tmp_path / "history.db"
    )
    store.migrate(substrate)
    drafts = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(drafts)
    yield drafts, substrate
    drafts.close()
    substrate.close()


def _save(drafts, body, cited, **identity):
    return docs_store.upsert_document(
        drafts,
        slug="page",
        title="Page",
        body=body,
        guideline_set="kb",
        document_type="how-to",
        statement_ids=list(cited or {}),
        cited_statements=cited,
        **identity,
    )


def test_edits_merges_and_deletions_since_the_revision_make_it_out_of_date(
    connections,
):
    drafts, substrate = connections
    edited = store.create_statement(substrate, "state", "Exports run nightly.")
    merged = store.create_statement(substrate, "state", "Exports are CSV.")
    survivor = store.create_statement(substrate, "state", "Exports are CSV files.")
    deleted = store.create_statement(substrate, "state", "Exports are emailed.")
    substrate.commit()
    cited = {
        sid: store.get_statement(substrate, sid)["text"]
        for sid in (edited, merged, deleted)
    }
    document_id = _save(drafts, "v1", cited)

    def freshness() -> Freshness:
        return document_freshness.for_documents(
            drafts, lambda: substrate, [document_id]
        )[document_id]

    assert freshness().status == "current"

    store.update_statement_text(substrate, edited, "Exports run hourly.")
    store.delete_statement(substrate, merged, merged_into=survivor)
    store.delete_statement(substrate, deleted)
    substrate.commit()

    assert freshness() == Freshness(
        "out_of_date",
        (
            StatementChange(
                edited, "edited", "Exports run nightly.", "Exports run hourly."
            ),
            StatementChange(
                merged, "merged", "Exports are CSV.", "Exports are CSV files.", survivor
            ),
            StatementChange(deleted, "deleted", "Exports are emailed.", None),
        ),
    )

    revised = {sid: store.get_statement(substrate, sid)["text"] for sid in (edited,)}
    _save(
        drafts,
        "v2",
        revised,
        updates=document_id,
        replacing=docs_store.body_digest("v1"),
    )
    assert freshness().status == "current"


def test_a_revision_saved_without_a_citation_record_is_unknown(connections):
    drafts, substrate = connections
    document_id = _save(drafts, "legacy", None)

    assert document_freshness.for_documents(drafts, lambda: substrate, [document_id])[
        document_id
    ] == Freshness("unknown")


def test_updating_sources_briefs_the_revision_with_what_changed(
    connections, monkeypatch
):
    drafts, substrate = connections
    statement = store.create_statement(substrate, "state", "Exports run nightly.")
    substrate.commit()
    document_id = _save(drafts, "v1", {statement: "Exports run nightly."})
    drafts_store.use_connection(drafts)
    store.use_substrate_connection(substrate)
    monkeypatch.setattr(documentation, "_check_guideline_selection", lambda *_: None)
    started = {}

    def start_run(**kwargs):
        started.update(kwargs)
        return docs_store.create_run(drafts, prompt=kwargs["prompt"], created_by=None)

    monkeypatch.setattr(doc_runs, "start_run", start_run)
    try:
        with pytest.raises(ValueError, match="Nothing this document cites"):
            documentation.revise_document(document_id, 1, update_sources=True)

        store.update_statement_text(substrate, statement, "Exports run hourly.")
        substrate.commit()
        assert documentation.get_generated_document(document_id)["stale"]["status"] == (
            "out_of_date"
        )
        documentation.revise_document(document_id, 1, update_sources=True)
    finally:
        drafts_store.reset()
        store.reset_substrate()

    assert started["target_document_id"] == document_id
    assert statement in started["prompt"]
    assert "Exports run hourly." in started["prompt"]


@pytest.fixture
def media_db():
    conn = media_store.connect(":memory:")
    media_store.migrate(conn)
    media_store.use_connection(conn)
    yield conn
    media_store.reset()
    conn.close()


def _image(conn, media_id: str, *, updated_at: str, audiences: str | None = None):
    conn.execute(
        "INSERT INTO media_items (id, content_type, byte_size, sha256, "
        "content_updated_at, alt_text, origin, audiences, created_at, updated_at) "
        "VALUES (?, 'image/png', 1, 'x', ?, 'The export dialog', 'uploaded', ?, ?, ?)",
        (media_id, updated_at, audiences, updated_at, updated_at),
    )


def test_a_placed_image_replaced_or_deleted_since_makes_it_out_of_date(
    connections, media_db
):
    drafts, substrate = connections
    _image(media_db, "med_000000000001", updated_at="2020-01-01T00:00:00.000Z")
    body = "![a](media:med_000000000001)\n\n![b](media:med_000000000002)\n"
    document_id = _save(drafts, body, {})

    def freshness() -> Freshness:
        return document_freshness.for_documents(
            drafts, lambda: substrate, [document_id]
        )[document_id]

    assert freshness().media_changes == (
        MediaChange("med_000000000002", "deleted", ""),
    )
    media_db.execute(
        "UPDATE media_items SET content_updated_at = '2999-01-01T00:00:00.000Z'"
    )
    assert freshness() == Freshness(
        "out_of_date",
        (),
        (
            MediaChange("med_000000000001", "replaced", "The export dialog"),
            MediaChange("med_000000000002", "deleted", ""),
        ),
    )


def test_an_image_relabelled_away_from_the_audience_is_no_longer_visible(media_db):
    _image(media_db, "med_000000000001", updated_at="2020-01-01T00:00:00.000Z")
    _image(
        media_db,
        "med_000000000002",
        updated_at="2020-01-01T00:00:00.000Z",
        audiences='["external-technical"]',
    )
    items = {row["id"]: row for row in media_db.execute("SELECT * FROM media_items")}
    cited = _Cited(
        {},
        ("external-technical", False),
        ("med_000000000001", "med_000000000002"),
        "2026-01-01T00:00:00.000Z",
    )

    assert assess_media(cited, items) == (
        MediaChange("med_000000000001", "no_longer_visible", "The export dialog"),
    )


@pytest.fixture
def drafts(tmp_path):
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    yield conn
    conn.close()


FLOW_BODY = "A member asks for the file.\n\n```flow\nrequest-to-download\n```\n"


def _flow_document(drafts, corpus: Corpus, audience) -> tuple[str, StoredFlow]:
    """A document placing the export flow, drawn and saved for `audience`."""
    ctx = _context(audience)
    definition = FlowDefinition(
        name="request-to-download",
        title="From request to download",
        start=corpus.requested,
    )
    problem, [stored] = loop._submission_problem(
        ctx, "Exports", FLOW_BODY, [corpus.queued], [definition]
    )
    assert problem is None
    run = docs_store.create_run(drafts, prompt="Explain exports", created_by=None)
    drafts.execute(
        "UPDATE documentation_runs SET profile_snapshot = ? WHERE id = ?",
        (json.dumps({"audience": {"id": audience.id, "scope": audience.scope}}), run),
    )
    drafts.commit()
    cited = store.get_statement_texts(
        store.substrate_connection(), stored.drawing.statement_ids
    )
    document_id = docs_store.upsert_document(
        drafts,
        slug=f"exports-{audience.scope}",
        title="Exports",
        body=FLOW_BODY,
        guideline_set="developer-reference",
        document_type="entity-page",
        statement_ids=list(cited),
        cited_statements=cited,
        flows=[stored.model_dump(mode="json")],
        run_id=run,
    )
    return document_id, stored


def _fresh(drafts, document_id: str) -> Freshness:
    return document_freshness.for_documents(
        drafts, store.substrate_connection, [document_id]
    )[document_id]


def test_a_flow_whose_step_links_changed_makes_its_document_out_of_date(
    db,  # noqa: F811
    drafts,
    monkeypatch,
):
    corpus = _corpus(db)
    document_id, _stored = _flow_document(drafts, corpus, INTERNAL)
    # Listing compares stored links with current ones; it never draws.
    monkeypatch.setattr(flows, "draw_flow", lambda *_a, **_k: pytest.fail("redrawn"))

    assert _fresh(drafts, document_id) == Freshness("current")

    reminder = store.create_statement(db, "event", "A reminder is sent to the member.")
    store.insert_links(db, [(corpus.expired, reminder, "proceeds", None)])
    store.delete_links(db, [(corpus.queued, corpus.failed, "on-failure", None)])
    store.delete_links(
        db, [(corpus.queued, corpus.ready, "proceeds", {"statement_id": corpus.sso})]
    )
    store.insert_links(db, [(corpus.queued, corpus.ready, "proceeds", None)])
    db.commit()

    freshness = _fresh(drafts, document_id)

    def change(kind: str, link_type: str, source: str, target: str) -> FlowChange:
        return FlowChange(
            "request-to-download",
            "From request to download",
            kind,
            link_type,
            source,
            target,
        )

    assert freshness.status == "out_of_date" and freshness.changes == ()
    assert set(freshness.flow_changes) == {
        change(
            "step_added",
            "proceeds",
            "The download link of the workspace export expires.",
            "A reminder is sent to the member.",
        ),
        change(
            "step_removed",
            "on-failure",
            "The workspace export is queued.",
            "The workspace export fails on worker b.",
        ),
        change(
            "condition_changed",
            "proceeds",
            "The workspace export is queued.",
            "The workspace export is ready with every invoice.",
        ),
    }
    assert freshness.as_dict()["flow_changes"][0]["flow"] == "request-to-download"
    brief = document_freshness.revision_brief(
        freshness.changes, freshness.media_changes, freshness.flow_changes
    )
    assert "The steps of flow `request-to-download`" in brief
    assert "preview_flow" in brief
    assert (
        "  - step added: 'The download link of the workspace export expires.' "
        "now leads to 'A reminder is sent to the member.' (proceeds)."
    ) in brief
    assert (
        "  - step removed: 'The workspace export is queued.' no longer leads to "
        "'The workspace export fails on worker b.' (on-failure)."
    ) in brief
    assert (
        "  - condition changed on the step from 'The workspace export is queued.' "
        "to 'The workspace export is ready with every invoice.' (proceeds)."
    ) in brief


def test_flow_freshness_is_read_inside_the_documents_audience(db, drafts):  # noqa: F811
    corpus = _corpus(db)
    external, _stored = _flow_document(drafts, corpus, EXTERNAL)
    internal, _stored = _flow_document(drafts, corpus, INTERNAL)
    hidden = store.create_statement(db, "event", "Worker b retries the export.")
    store.insert_links(db, [(corpus.queued, hidden, "proceeds", None)])
    db.commit()

    # The new step is unlabelled, so only the internal page's flow changed.
    assert _fresh(drafts, external) == Freshness("current")
    assert [change.change for change in _fresh(drafts, internal).flow_changes] == [
        "step_added"
    ]

    store.audience_labels.set_label(
        db, hidden, [INTERNAL.id, EXTERNAL.id], source="ai", reason="r"
    )
    db.commit()

    [added] = _fresh(drafts, external).flow_changes
    assert (added.change, added.target_text) == (
        "step_added",
        "Worker b retries the export.",
    )


def test_a_document_without_flows_reads_no_links(db, drafts, monkeypatch):  # noqa: F811
    corpus = _corpus(db)
    document_id = docs_store.upsert_document(
        drafts,
        slug="plain",
        title="Plain",
        body="No flow.",
        statement_ids=[corpus.queued],
        cited_statements={corpus.queued: "The workspace export is queued."},
    )
    monkeypatch.setattr(
        store, "get_links_from", lambda *_a, **_k: pytest.fail("links were read")
    )

    assert _fresh(drafts, document_id) == Freshness("current")


def test_every_flow_asked_about_shares_one_read_of_links(db, drafts, monkeypatch):  # noqa: F811
    corpus = _corpus(db)
    first, _stored = _flow_document(drafts, corpus, EXTERNAL)
    second, _stored = _flow_document(drafts, corpus, INTERNAL)
    reads = []
    read = store.get_links_from

    def counted(conn, statement_ids):
        reads.append(list(statement_ids))
        return read(conn, statement_ids)

    monkeypatch.setattr(store, "get_links_from", counted)

    document_freshness.for_documents(
        drafts, store.substrate_connection, [first, second]
    )

    assert len(reads) == 1


def test_a_flow_change_withholds_a_step_the_audience_lost(db, drafts):  # noqa: F811
    corpus = _corpus(db)
    external, _stored = _flow_document(drafts, corpus, EXTERNAL)
    store.audience_labels.set_label(
        db, corpus.queued, [INTERNAL.id], source="ai", reason="r"
    )
    db.commit()

    changes = _fresh(drafts, external).flow_changes
    assert changes
    assert "The export is queued." not in {
        text for change in changes for text in (change.source_text, change.target_text)
    }
