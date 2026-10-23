"""Whether a generated document still says what its cited statements say."""

from __future__ import annotations

import pytest

from mycelium import doc_runs, docs_store, document_freshness, drafts_store, store
from mycelium.document_freshness import Freshness, StatementChange, assess
from mycelium.server import documentation


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
        with pytest.raises(ValueError, match="None of the statements"):
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
