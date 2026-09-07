from __future__ import annotations

import pytest

from mycelium import mention_candidates, store


@pytest.fixture
def conn():
    connection = store.connect(":memory:")
    store.migrate(connection)
    yield connection
    connection.close()


def test_alias_matches_remain_distinct_from_assertions(conn):
    entity = store.create_entity(conn, "authentication")
    store.create_name(conn, "single sign-on", entity)
    short = store.create_name(conn, "SSO", entity)
    first = store.create_statement(conn, "state", "Single sign-on is enabled")
    second = store.create_statement(conn, "state", "SSO is required")
    result = mention_candidates.find_candidates(conn, entity)
    assert [(m.statement_id, m.match) for m in result.matches] == [
        (first, "derived"),
        (second, "possible"),
    ]
    assert store.get_mentions(conn, second) == []
    conn.execute(
        "INSERT INTO pending_mentions "
        "(statement_id, name_id, created_at, approved_at) VALUES (?, ?, 'old', 'old')",
        (second, short),
    )
    assert (
        mention_candidates.find_candidates(conn, entity).matches[1].match == "approved"
    )


def test_bounded_scan_can_resume_after_empty_page(conn, monkeypatch):
    monkeypatch.setattr(mention_candidates, "SCAN_LIMIT", 2)
    entity = store.create_entity(conn, None)
    store.create_name(conn, "SSO", entity)
    store.create_statement(conn, "state", "unrelated first")
    store.create_statement(conn, "state", "unrelated second")
    sid = store.create_statement(conn, "state", "SSO is enabled")
    empty = mention_candidates.find_candidates(conn, entity)
    assert empty.matches == [] and empty.has_more and empty.scanned == 2
    result = mention_candidates.find_candidates(conn, entity, after=empty.next_after)
    assert [m.statement_id for m in result.matches] == [sid]
    assert not result.has_more


def test_pagination_and_longest_name_resolution(conn):
    general = store.create_entity(conn, "general")
    specific = store.create_entity(conn, "specific")
    store.create_name(conn, "account", general)
    store.create_name(conn, "service account", specific)
    store.create_statement(conn, "state", "The service account is enabled")
    one = store.create_statement(conn, "state", "The account is enabled")
    two = store.create_statement(conn, "state", "The account is disabled")
    first = mention_candidates.find_candidates(conn, general, limit=1)
    assert [m.statement_id for m in first.matches] == [one]
    assert first.has_more
    second = mention_candidates.find_candidates(conn, general, after=first.next_after)
    assert [m.statement_id for m in second.matches] == [two]
    assert not second.has_more


def test_move_or_remove_alias_immediately_changes_candidates(conn):
    old = store.create_entity(conn, "old")
    new = store.create_entity(conn, "new")
    name = store.create_name(conn, "SSO", old)
    sid = store.create_statement(conn, "state", "SSO is enabled")
    store.set_name_entity(conn, name, new)
    assert mention_candidates.find_candidates(conn, old).matches == []
    assert mention_candidates.find_candidates(conn, new).matches[0].statement_id == sid
    store.delete_name(conn, name)
    assert mention_candidates.find_candidates(conn, new).matches == []
