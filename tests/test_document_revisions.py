"""Document version authority and publishing receipts against isolated storage."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from mycelium import (
    doc_runs,
    docs_store,
    drafts_store,
    product_settings,
    prompt_store,
    server,
)
from mycelium.docgen.destinations import (
    Delivery,
    DeliveryDocument,
    DestinationConfig,
    DestinationError,
)
from mycelium.docgen.schema import RevisionTarget
from product_settings_helpers import import_product_environment


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = docs_store.connect(tmp_path / "drafts.db")
    docs_store.migrate(conn)
    drafts_store.configure(tmp_path / "drafts.db")
    drafts_store.use_connection(conn)
    yield conn
    doc_runs.wait_all()
    drafts_store.reset()
    conn.close()


def document(db: sqlite3.Connection, body: str = "First body") -> str:
    return docs_store.upsert_document(
        db,
        slug="policy",
        title="Policy",
        body=body,
        guideline_set="kb-authoring",
        document_type="reference",
        statement_ids=["stm_source"],
    )


def revise(db: sqlite3.Connection, document_id: str, body: str, revision: int) -> str:
    row = docs_store.require_revision(db, document_id, revision)
    return docs_store.upsert_document(
        db,
        slug=str(row["slug"]),
        title="Revised policy",
        body=body,
        guideline_set=str(row["guideline_set"]),
        document_type=str(row["document_type"]),
        statement_ids=["stm_revised"],
        updates=document_id,
        expected_revision=revision,
        replacing=docs_store.body_digest(str(row["body"])),
    )


def configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MYCELIUM_DOC_DESTINATIONS",
        json.dumps(
            {
                "docs": {
                    "type": "github",
                    "path_template": "docs/{slug}.md",
                    "config": {
                        "owner": "team",
                        "repo": "handbook",
                        "base_branch": "main",
                        "token_env": "DOCS_TOKEN",
                    },
                }
            }
        ),
    )
    monkeypatch.setenv("DOCS_TOKEN", "test-only-credential")
    import_product_environment()
    prompt_store.connection().commit()


def test_revisions_preserve_bodies_and_prevent_aba_replacement(
    db: sqlite3.Connection,
) -> None:
    document_id = document(db)
    revise(db, document_id, "Second body", 1)
    revise(db, document_id, "First body", 2)
    assert [
        (row["revision"], row["parent_revision"], row["body"])
        for row in docs_store.list_revisions(db, document_id)
    ] == [
        (3, 2, "First body"),
        (2, 1, "Second body"),
        (1, None, "First body"),
    ]
    with pytest.raises(docs_store.RevisionConflict):
        revise(db, document_id, "Stale replacement", 1)
    assert server.get_document_revision(document_id, 1)["body"] == "First body"
    assert server.get_generated_document(document_id)["current_revision"] == 3
    assert server.list_document_revisions(document_id)["revisions"]


def test_backfill_does_not_invent_old_bodies_or_claim_stale_delivery(
    db: sqlite3.Connection,
) -> None:
    document_id = document(db)
    db.execute("DELETE FROM generated_document_revisions")
    db.execute(
        "UPDATE generated_documents SET delivery_destination='docs', delivery_content_revision='old-remote-body' WHERE id=?",
        (document_id,),
    )
    db.commit()
    docs_store.migrate(db)
    docs_store.migrate(db)
    assert len(docs_store.list_revisions(db, document_id)) == 1
    assert docs_store.get_document(db, document_id)["published_revision"] is None


def test_selected_internal_revision_is_captured_and_concurrent_edit_keeps_failed_body(
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = document(db)
    entered = threading.Event()
    release = threading.Event()
    seen: list[RevisionTarget] = []

    def runner(
        prompt: str, *, revision_target: RevisionTarget | None = None, **kwargs: object
    ) -> dict[str, object]:
        assert revision_target is not None
        seen.append(revision_target)
        entered.set()
        assert release.wait(3)
        return {
            "outcome": "document_written",
            "slug": "wrong-slug",
            "title": "New title",
            "body": "Attempted revision",
            "statement_ids": ["stm_source"],
            "matched_document_id": "wrong-document",
            "guideline_set": "wrong-profile",
            "document_type": "wrong-type",
        }

    monkeypatch.setattr(doc_runs, "_default_runner", runner)
    run_id = doc_runs.start_run(
        prompt="Clarify this",
        guideline_set=None,
        document_type=None,
        created_by=None,
        conn=db,
        target_document_id=document_id,
        expected_revision=1,
    )
    try:
        assert entered.wait(3)
        revise(db, document_id, "Concurrent accepted revision", 1)
    finally:
        release.set()
    doc_runs.wait_all()
    assert seen[0].current.body == "First body"
    assert seen[0].document.id == document_id
    run = docs_store.get_run(db, run_id)
    assert (run["target_document_id"], run["target_revision"], run["outcome"]) == (
        document_id,
        1,
        "failed",
    )
    assert run["draft_body"] == "Attempted revision"
    assert (
        docs_store.get_document(db, document_id)["body"]
        == "Concurrent accepted revision"
    )
    with pytest.raises(docs_store.RevisionConflict):
        doc_runs.start_run(
            prompt="Stale",
            guideline_set=None,
            document_type=None,
            created_by=None,
            conn=db,
            target_document_id=document_id,
            expected_revision=1,
        )
    assert len(docs_store.list_runs(db)) == 1


def test_explicit_revision_preserves_identity_and_records_result_backlink(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = document(db)

    def runner(prompt: str, **kwargs: object) -> dict[str, object]:
        return {
            "outcome": "document_written",
            "slug": "changed",
            "title": "New title",
            "body": "Second body",
            "statement_ids": ["stm_source"],
            "guideline_set": "different",
            "document_type": "other",
        }

    monkeypatch.setattr(doc_runs, "_default_runner", runner)
    run_id = doc_runs.start_run(
        prompt="Clarify",
        guideline_set=None,
        document_type=None,
        created_by=None,
        conn=db,
        target_document_id=document_id,
        expected_revision=1,
    )
    doc_runs.wait_all()
    row = docs_store.get_document(db, document_id)
    assert (
        row["slug"],
        row["guideline_set"],
        row["document_type"],
        row["current_revision"],
    ) == ("policy", "kb-authoring", "reference", 2)
    assert docs_store.get_run(db, run_id)["result_revision"] == 2
    assert docs_store.get_revision(db, document_id, 2)["run_id"] == run_id


def test_publication_tracks_actual_revision_after_concurrent_generation_and_settings_edits(
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.docgen import destinations

    configure(monkeypatch)
    document_id = document(db)
    calls: list[tuple[DestinationConfig, DeliveryDocument]] = []

    def deliver(config: DestinationConfig, item: DeliveryDocument) -> Delivery:
        calls.append((config, item))
        if len(calls) == 1:
            revise(db, document_id, "Second body", 1)
        return Delivery(
            "docs",
            "docs/policy.md",
            "https://github.com/team/handbook/pull/7",
            f"remote-{len(calls)}",
        )

    monkeypatch.setattr(destinations, "deliver_document", deliver)
    result = server.deliver_document(document_id, "docs", expected_revision=1)
    assert result["revision"] == 1
    current = server.get_generated_document(document_id)
    assert (
        current["current_revision"],
        current["published_revision"],
        current["delivery_status"],
    ) == (2, 1, "changes_pending")
    assert server.get_document_revision(document_id, 1)["delivery"] is not None
    settings = product_settings.get(product_settings.DocumentationSettings)
    prompt_store.connection().execute(
        "UPDATE product_settings SET body_json=? WHERE section='documentation'",
        (settings.model_copy(update={"destinations": ()}).model_dump_json(),),
    )
    prompt_store.connection().commit()
    server.deliver_document(document_id, "docs", expected_revision=2)
    assert destinations.destination_coordinates(calls[1][0]) == {
        "host": "github.com",
        "owner": "team",
        "repo": "handbook",
        "base_branch": "main",
    }
    assert calls[1][1].delivered_path == "docs/policy.md"
    assert server.get_generated_document(document_id)["delivery_status"] == "published"
    with pytest.raises(docs_store.RevisionConflict):
        server.deliver_document(document_id, "docs", expected_revision=1)
    assert len(calls) == 2


def test_failed_publication_can_retry_and_binding_host_drift_is_rejected(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycelium.docgen import destinations

    configure(monkeypatch)
    document_id = document(db)
    calls = 0

    def deliver(config: DestinationConfig, item: DeliveryDocument) -> Delivery:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DestinationError("Simulated GitHub failure")
        return Delivery(
            "docs",
            "docs/policy.md",
            "https://github.com/team/handbook/pull/7",
            "remote",
        )

    monkeypatch.setattr(destinations, "deliver_document", deliver)
    with pytest.raises(ValueError, match="Simulated GitHub failure"):
        server.deliver_document(document_id, "docs", expected_revision=1)
    assert server.get_generated_document(document_id)["body"] == "First body"
    server.deliver_document(document_id, "docs", expected_revision=1)
    row = docs_store.get_document(db, document_id)
    monkeypatch.setenv(
        "MYCELIUM_GITHUB_CREDENTIALS",
        json.dumps(
            {
                row["delivery_binding"]: {
                    "host": "other.example",
                    "token_env": "DOCS_TOKEN",
                }
            }
        ),
    )
    with pytest.raises(ValueError, match="authorized"):
        server.deliver_document(document_id, "docs", expected_revision=1)
    assert calls == 2


def test_two_publications_cannot_complete_out_of_revision_order(
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.docgen import destinations

    configure(monkeypatch)
    document_id = document(db)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_entered = threading.Event()
    errors: list[Exception] = []

    def deliver(config: DestinationConfig, item: DeliveryDocument) -> Delivery:
        if item.body == "First body":
            first_entered.set()
            assert release_first.wait(3)
            revision = 1
        else:
            second_entered.set()
            revision = 2
        return Delivery(
            "docs",
            "docs/policy.md",
            "https://github.com/team/handbook/pull/7",
            f"remote-{revision}",
        )

    def publish(revision: int) -> None:
        try:
            if revision == 2:
                second_started.set()
            server.deliver_document(document_id, "docs", expected_revision=revision)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(destinations, "deliver_document", deliver)
    first = threading.Thread(target=publish, args=(1,))
    second = threading.Thread(target=publish, args=(2,))
    first.start()
    try:
        assert first_entered.wait(3), errors
        revise(db, document_id, "Second body", 1)
        second.start()
        assert second_started.wait(3)
        assert not second_entered.wait(0.05)
    finally:
        release_first.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert errors == []
    assert second_entered.is_set()
    assert server.get_generated_document(document_id)["published_revision"] == 2
    assert [
        row["revision"]
        for row in db.execute(
            "SELECT revision FROM generated_document_deliveries ORDER BY revision"
        )
    ] == [1, 2]


def test_first_publication_requests_share_one_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.docgen import destinations

    constructing = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    locks: list[threading.Lock] = []
    created: list[threading.Lock] = []

    class LockFactory:
        @staticmethod
        def Lock() -> threading.Lock:
            lock = threading.Lock()
            created.append(lock)
            constructing.set()
            assert release.wait(3)
            return lock

    def first_request() -> None:
        locks.append(destinations.publication_lock("first-publication-race"))

    def second_request() -> None:
        second_started.set()
        locks.append(destinations.publication_lock("first-publication-race"))

    monkeypatch.setattr(destinations, "threading", LockFactory)
    first = threading.Thread(target=first_request)
    second = threading.Thread(target=second_request)
    first.start()
    try:
        assert constructing.wait(3)
        second.start()
        assert second_started.wait(3)
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert len(created) == 1
    assert len(locks) == 2
    assert locks[0] is locks[1]
