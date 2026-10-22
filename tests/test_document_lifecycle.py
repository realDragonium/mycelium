"""A generated document after it leaves Mycelium: its identity, its pull
request, and the text people edit at the destination."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from mycelium import docs_store

TARGET = json.dumps(
    {"host": "github.com", "owner": "acme", "repo": "handbook", "base_branch": "main"}
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(connection)
    yield connection
    connection.close()


def _document(
    conn: sqlite3.Connection,
    *,
    slug: str = "sso",
    anchor: str | None = None,
    body: str = "# SSO\n",
) -> str:
    return docs_store.upsert_document(
        conn,
        slug=slug,
        title="SSO",
        body=body,
        guideline_set="kb",
        document_type="how-to",
        statement_ids=["stm_1"],
        anchor_entity_id=anchor,
    )


def _deliver(
    conn: sqlite3.Connection, document_id: str, *, number: int | None = 17
) -> None:
    docs_store.record_delivery(
        conn,
        document_id,
        destination="docs",
        target=TARGET,
        path="docs/sso.md",
        reference=f"https://github.com/acme/handbook/pull/{number or 1}",
        content_revision="a" * 40,
        revision=int(docs_store.get_document(conn, document_id)["current_revision"]),
        pull_request_number=number,
    )


def _serialized(conn: sqlite3.Connection, document_id: str) -> dict[str, object]:
    row = docs_store.get_document(conn, document_id)
    assert row is not None
    return docs_store.serialize_document(row)


# --- identity ---------------------------------------------------------------


def test_an_anchor_identifies_one_document_per_set_and_type(conn):
    document_id = _document(conn, anchor="ent_sso")

    found = docs_store.find_by_anchor(conn, "kb", "how-to", "ent_sso")

    assert found is not None and found["id"] == document_id
    assert docs_store.find_by_anchor(conn, "kb", "reference", "ent_sso") is None
    with pytest.raises(ValueError, match="already holds anchor 'ent_sso'"):
        _document(conn, slug="other", anchor="ent_sso")


def test_an_anchored_document_takes_a_free_slug_beside_a_same_titled_page(conn):
    unanchored = _document(conn)
    second = _document(conn, anchor="ent_okta", body="# Okta SSO\n")
    third = _document(conn, anchor="ent_entra", body="# Entra SSO\n")

    slugs = {
        document_id: docs_store.get_document(conn, document_id)["slug"]
        for document_id in (unanchored, second, third)
    }
    assert slugs == {unanchored: "sso", second: "sso-2", third: "sso-3"}
    assert docs_store.get_document(conn, unanchored)["body"] == "# SSO\n"


def test_an_unanchored_title_collision_is_still_refused(conn):
    _document(conn)

    with pytest.raises(ValueError, match="would replace a stored body"):
        _document(conn, body="# Different\n")


# --- pull request tracking --------------------------------------------------


def test_delivery_records_an_open_pull_request_and_the_sync_point(conn):
    document_id = _document(conn)
    _deliver(conn, document_id)

    document = _serialized(conn, document_id)
    pull_request = document["pull_request"]
    assert isinstance(pull_request, dict)
    assert (pull_request["number"], pull_request["state"]) == (17, "open")
    assert pull_request["url"] == "https://github.com/acme/handbook/pull/17"
    assert document["delivery_status"] == "published"
    assert document["revision_source_content_revision"] == "a" * 40


@pytest.mark.parametrize("state", ["merged", "closed"])
def test_a_finished_pull_request_shows_in_the_delivery_status(conn, state):
    document_id = _document(conn)
    _deliver(conn, document_id)

    docs_store.record_pull_request_state(conn, document_id, 17, state)

    assert _serialized(conn, document_id)["delivery_status"] == state


def test_a_newer_internal_revision_outranks_a_merged_pull_request(conn):
    document_id = _document(conn)
    _deliver(conn, document_id)
    docs_store.record_pull_request_state(conn, document_id, 17, "merged")
    docs_store.upsert_document(
        conn,
        slug="sso",
        title="SSO",
        body="# SSO, revised\n",
        guideline_set="kb",
        document_type="how-to",
        updates=document_id,
        replacing=docs_store.body_digest("# SSO\n"),
        expected_revision=1,
    )

    document = _serialized(conn, document_id)
    assert document["delivery_status"] == "changes_pending"
    pull_request = document["pull_request"]
    assert isinstance(pull_request, dict) and pull_request["state"] == "merged"


def test_a_state_read_for_a_replaced_pull_request_is_discarded(conn):
    document_id = _document(conn)
    _deliver(conn, document_id, number=17)
    _deliver(conn, document_id, number=18)

    docs_store.record_pull_request_state(conn, document_id, 17, "merged")

    pull_request = _serialized(conn, document_id)["pull_request"]
    assert isinstance(pull_request, dict)
    assert (pull_request["number"], pull_request["state"]) == (18, "open")


def test_an_unknown_pull_request_state_is_refused(conn):
    document_id = _document(conn)
    _deliver(conn, document_id)

    with pytest.raises(ValueError, match="invalid pull request state"):
        docs_store.record_pull_request_state(conn, document_id, 17, "draft")


def test_upgrade_reads_the_pull_request_number_back_from_the_review_url(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = docs_store.connect(path)
    docs_store.migrate(legacy)
    document_id = _document(legacy)
    _deliver(legacy, document_id, number=None)
    legacy.execute(
        "UPDATE generated_documents SET delivery_reference = ?",
        ("https://github.com/acme/handbook/pull/42",),
    )
    for column in (
        "pull_request_number",
        "pull_request_state",
        "pull_request_refreshed_at",
    ):
        legacy.execute(f"ALTER TABLE generated_documents DROP COLUMN {column}")
    legacy.commit()

    docs_store.migrate(legacy)

    pull_request = _serialized(legacy, document_id)["pull_request"]
    assert isinstance(pull_request, dict)
    assert (pull_request["number"], pull_request["state"]) == (42, None)
    legacy.close()
