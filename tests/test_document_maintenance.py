"""Out-of-date documents under each maintenance policy: proposed as plan
items, revised by themselves within guard rails, and reported to people."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from mycelium import (
    doc_runs,
    docs_store,
    document_freshness,
    document_maintenance,
    store,
    timestamps,
)
from mycelium.docgen import publication

#: Recent, because the list leaves out entries older than a month.
T0 = datetime.now(UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from test_prompt_texts import _app

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")

    def runner(prompt, *, guideline_set, document_type):
        from mycelium import server

        texts = store.get_statement_texts(server._db(), [*_cited])
        return {
            "outcome": "document_written",
            "slug": "export-invoices",
            "title": "Export invoices",
            "body": "# Export invoices\n\n" + "\n".join(texts.values()) + "\n",
            "statement_ids": list(texts),
            "cited_statements": texts,
        }

    doc_runs.RUNNER = runner
    try:
        with _app(tmp_path, monkeypatch) as client:
            yield client
    finally:
        doc_runs.wait_all()
        doc_runs.RUNNER = None


_cited: list[str] = []


def _profile(maintenance: str | None, audience: str | None = None) -> None:
    from mycelium import guidelines, prompt_store

    slots = {"guidance": "Plain words.", "how-to": "Numbered steps."}
    if maintenance is not None:
        slots["maintenance"] = maintenance
    if audience is not None:
        slots["audience"] = audience
    for slot, text in slots.items():
        prompt_store.save(
            prompt_store.connection(),
            type=guidelines.TYPE,
            name=f"public/{slot}",
            text=text,
        )


def _document(text: str = "Admins can export invoices as CSV.") -> tuple[str, str]:
    """A document of the `public` profile citing one statement, written by
    a run that recorded the profile's audience."""
    from mycelium import server

    conn = server._db()
    with store.transaction(conn):
        statement = store.create_statement(conn, "capability", text)
    _cited[:] = [statement]
    drafts = server._drafts_db()
    run = docs_store.create_run(drafts, prompt="Export invoices", created_by=None)
    snapshot = {
        "audience": {
            "id": "external-technical",
            "name": "External technical",
            "scope": "external",
        }
    }
    drafts.execute(
        "UPDATE documentation_runs SET profile_snapshot = ? WHERE id = ?",
        (json.dumps(snapshot), run),
    )
    drafts.commit()
    document = docs_store.upsert_document(
        drafts,
        slug="export-invoices",
        title="Export invoices",
        body=f"# Export invoices\n\n{text}\n",
        guideline_set="public",
        document_type="how-to",
        statement_ids=[statement],
        cited_statements={statement: text},
        run_id=run,
    )
    docs_store.finish_run(drafts, run, outcome="document_written", document_id=document)
    with store.transaction(conn):
        store.audience_labels.set_label(
            conn, statement, ["external-technical"], source="curator", reason="public"
        )
    return document, statement


def _edit(statement: str, text: str) -> None:
    from mycelium import server

    with store.transaction(server._db()):
        store.update_statement_text(server._db(), statement, text)


def _sweep(at: datetime) -> list[str]:
    started = document_maintenance.sweep(at)
    doc_runs.wait_all()
    return started


def _revision(document: str) -> int:
    from mycelium import server

    row = docs_store.get_document(server._drafts_db(), document)
    assert row is not None
    return int(row["current_revision"])


def test_manual_profiles_are_left_alone(client):
    _profile(None)
    document, statement = _document()
    _edit(statement, "Admins can export invoices as CSV or PDF.")

    assert _sweep(T0 + timedelta(days=1)) == []
    assert client.get("/api/documentation/maintenance").json() == {"entries": []}
    plan = client.get("/api/documentation/plans/public").json()
    assert [item["document_id"] for item in plan["stale"]] == [document]


def test_propose_adds_one_update_item_briefed_with_the_change(client):
    _profile("propose", "external-technical")
    document, statement = _document()
    _edit(statement, "Admins can export invoices as CSV or PDF.")

    _sweep(T0)
    _sweep(T0 + timedelta(minutes=5))

    plan = client.get("/api/documentation/plans/public").json()
    assert plan["stale"] == []
    (item,) = plan["items"]
    assert (item["action"], item["document_id"], item["maintenance"]) == (
        "update",
        document,
        True,
    )
    assert "Now: 'Admins can export invoices as CSV or PDF.'" in item["rationale"]
    (entry,) = client.get("/api/documentation/maintenance").json()["entries"]
    assert (entry["state"], entry["waiting"]) == ("proposed", True)

    approved = client.post(
        "/api/documentation/plan-items/approve", json={"item_ids": [item["id"]]}
    ).json()
    assert (
        "Now: 'Admins can export invoices as CSV or PDF.'"
        in (approved[0]["run"]["prompt"])
    )
    doc_runs.wait_all()
    assert _revision(document) == 2
    assert client.get("/api/documentation/plans/public").json()["items"] == []
    (entry,) = client.get("/api/documentation/maintenance").json()["entries"]
    assert (entry["state"], entry["waiting"]) == ("approved", False)


def test_auto_revise_waits_for_credentials(client, monkeypatch):
    _profile("auto-revise", "external-technical")
    document, statement = _document()
    _edit(statement, "Admins can export invoices as CSV or PDF.")
    _sweep(T0)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(
        document_maintenance.model_settings,
        "claude_configuration_error",
        lambda: "Configure Anthropic credentials on the server.",
    )

    assert _sweep(T0 + timedelta(hours=1)) == []
    assert _revision(document) == 1

    monkeypatch.setattr(
        document_maintenance.model_settings, "claude_configuration_error", lambda: None
    )
    assert len(_sweep(T0 + timedelta(hours=2))) == 1
    assert _revision(document) == 2


def test_auto_revise_waits_for_quiet_and_revises_once(client):
    _profile("auto-revise", "external-technical")
    document, statement = _document()

    _edit(statement, "Admins can export invoices as CSV or PDF.")
    assert _sweep(T0) == []
    _edit(statement, "Admins can export invoices as CSV, PDF or XLSX.")
    # The second edit restarts the quiet period (30 minutes by default).
    assert _sweep(T0 + timedelta(minutes=20)) == []
    assert _sweep(T0 + timedelta(minutes=45)) == []

    (run_id,) = _sweep(T0 + timedelta(minutes=51))
    assert _revision(document) == 2
    # A later sweep, as after a restart, does not start it again.
    assert _sweep(T0 + timedelta(hours=2)) == []

    (entry,) = client.get("/api/documentation/maintenance").json()["entries"]
    assert (entry["state"], entry["run_id"], entry["new_revision"]) == (
        "revised",
        run_id,
        2,
    )
    assert [change["new_text"] for change in entry["changes"]] == [
        "Admins can export invoices as CSV, PDF or XLSX."
    ]
    diff = client.get(
        f"/api/documentation/documents/{document}/revisions/2/diff"
    ).json()
    assert (diff["from_revision"], diff["to_revision"]) == (1, 2)
    assert {"op": "-", "text": "Admins can export invoices as CSV."} in diff["lines"]
    assert {
        "op": "+",
        "text": "Admins can export invoices as CSV, PDF or XLSX.",
    } in diff["lines"]


def test_auto_revise_stops_at_the_daily_cap(client):
    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile("auto-revise", "external-technical")
    set_product(product_settings.DocumentationMaintenanceSettings(revisions_per_day=1))
    _document_id, statement = _document()

    _edit(statement, "Admins can export invoices as CSV or PDF.")
    _sweep(T0)
    assert len(_sweep(T0 + timedelta(hours=1))) == 1
    _edit(statement, "Admins can export invoices as PDF.")
    _sweep(T0 + timedelta(hours=2))

    assert _sweep(T0 + timedelta(hours=3)) == []
    (started,) = _sweep(T0 + timedelta(hours=26))
    assert docs_store.get_run(server._drafts_db(), started)["target_revision"] == 2


def test_a_published_document_is_republished_for_a_person_to_merge(client, monkeypatch):
    from mycelium import server

    _profile("auto-revise", "external-technical")
    document, statement = _document()
    server._drafts_db().execute(
        "UPDATE generated_documents SET delivery_destination = 'docs', "
        "pull_request_number = 7, pull_request_state = 'open' WHERE id = ?",
        (document,),
    )
    server._drafts_db().commit()
    published = []
    monkeypatch.setattr(
        publication,
        "publish",
        lambda conn, document_id, destination, revision: published.append(
            (document_id, destination, revision)
        ),
    )
    _edit(statement, "Admins can export invoices as CSV or PDF.")
    _sweep(T0)
    _sweep(T0 + timedelta(hours=1))
    _sweep(T0 + timedelta(hours=1, minutes=1))
    _sweep(T0 + timedelta(hours=1, minutes=2))

    assert published == [(document, "docs", 2)]
    (entry,) = client.get("/api/documentation/maintenance").json()["entries"]
    assert (entry["delivery"], entry["waiting"]) == ("published", True)


def test_a_dismissed_document_is_not_revised(client):
    _profile("auto-revise", "external-technical")
    document, statement = _document()
    _edit(statement, "Admins can export invoices as CSV or PDF.")
    client.post(
        f"/api/documentation/plans/public/stale/{document}/dismiss",
        json={"revision": 1},
    )

    _sweep(T0)
    assert _sweep(T0 + timedelta(hours=1)) == []


def test_an_interrupted_claim_is_reported_not_repeated(client):
    from mycelium import server

    _profile("auto-revise", "external-technical")
    _document_id, statement = _document()
    _edit(statement, "Admins can export invoices as CSV or PDF.")
    _sweep(T0)
    server._drafts_db().execute(
        "UPDATE document_maintenance SET action = 'auto-revise', acted_at = ?",
        (timestamps.of(T0),),
    )
    server._drafts_db().commit()

    document_maintenance.mark_interrupted(server._drafts_db())

    assert _sweep(T0 + timedelta(hours=1)) == []
    (entry,) = client.get("/api/documentation/maintenance").json()["entries"]
    assert (entry["state"], entry["waiting"]) == ("failed", True)
    assert "interrupted by restart" in entry["error"]


def test_a_cited_statement_hidden_from_the_audience_makes_it_out_of_date(client):
    from mycelium import server

    _profile(None, "external-technical")
    document, statement = _document()
    stale = client.get(f"/api/documentation/documents/{document}").json()["stale"]
    assert stale["status"] == "current"

    with store.transaction(server._db()):
        store.audience_labels.set_label(
            server._db(),
            statement,
            ["internal-technical"],
            source="curator",
            reason="internal",
        )

    stale = client.get(f"/api/documentation/documents/{document}").json()["stale"]
    assert stale["status"] == "out_of_date"
    assert [change["change"] for change in stale["changes"]] == ["no_longer_visible"]
    assert "no longer visible to this audience" in document_freshness.revision_brief(
        document_freshness.for_documents(server._drafts_db(), server._db, [document])[
            document
        ].changes
    )


def test_an_edit_waits_for_its_new_label_and_its_confirmation_instead_of_reading_as_hidden(
    client,
):
    from mycelium import server

    _profile("propose", "external-technical")
    _document_id, statement = _document()
    with store.transaction(server._db()):
        store.audience_labels.set_label(
            server._db(), statement, ["external-technical"], source="ai", reason="ai"
        )
    _edit(statement, "Admins can export invoices as CSV or PDF.")

    _sweep(T0)
    assert client.get("/api/documentation/plans/public").json()["items"] == []

    with store.transaction(server._db()):
        store.audience_labels.apply_ai_label(
            server._db(),
            statement,
            ["external-technical"],
            reason="ai",
            model="fixture",
            cost_usd=None,
            hold={"external-technical"},
        )
    _sweep(T0 + timedelta(minutes=1))
    assert client.get("/api/documentation/plans/public").json()["items"] == []

    with store.transaction(server._db()):
        store.audience_labels.decide_pending(
            server._db(), statement, "external-technical", confirm=True, by="c"
        )
    _sweep(T0 + timedelta(minutes=2))
    (item,) = client.get("/api/documentation/plans/public").json()["items"]
    assert "Now: 'Admins can export invoices as CSV or PDF.'" in item["rationale"]
