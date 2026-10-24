"""Persistent retry limits shared by automatic work."""

from datetime import UTC, datetime, timedelta

import pytest

from mycelium import automation_stops, store

NOW = datetime(2026, 10, 24, tzinfo=UTC)


@pytest.fixture
def conn():
    connection = store.connect(":memory:")
    store.migrate(connection)
    return connection


def test_fail_counts_matching_inputs_and_stops_after_the_retry_limit(conn):
    assert not automation_stops.fail(
        conn,
        "connect",
        "stm_export",
        "Exports include invoices.",
        "The connect run failed.",
        retries=1,
        now=NOW,
    )
    assert automation_stops.fail(
        conn,
        "connect",
        "stm_export",
        "Exports include invoices.",
        "The connect run failed again.",
        retries=1,
        now=NOW + timedelta(minutes=1),
    )

    assert automation_stops.stops(conn) == [
        automation_stops.Stop(
            kind="connect",
            item_id="stm_export",
            failures=2,
            reason="The connect run failed again.",
            updated_at="2026-10-24T00:01:00.000Z",
        )
    ]


def test_changed_inputs_reset_failures(conn):
    automation_stops.fail(
        conn,
        "connect",
        "stm_export",
        "Exports include invoices.",
        "Failed.",
        retries=1,
        now=NOW,
    )

    assert not automation_stops.fail(
        conn,
        "connect",
        "stm_export",
        "Exports include invoices and receipts.",
        "Failed after the edit.",
        retries=1,
        now=NOW,
    )


def test_prune_removes_missing_and_changed_items(conn):
    for item_id, inputs in (("stm_login", "Login works."), ("stm_sso", "SSO works.")):
        automation_stops.fail(
            conn,
            "connect",
            item_id,
            inputs,
            "Failed.",
            retries=2,
            now=NOW,
        )

    automation_stops.prune(conn, "connect", {"stm_login": "Login changed."})

    assert conn.execute("SELECT COUNT(*) FROM automation_stops").fetchone()[0] == 0


def test_retry_marks_the_exact_stopped_item_for_one_person_retry(conn):
    automation_stops.stop(
        conn,
        "gap_follow_up",
        "gap_exports",
        "Which exports exist?",
        "Three proposals were rejected.",
        failures=3,
        now=NOW,
    )

    assert automation_stops.retry(conn, "gap_follow_up", "gap_exports")
    assert automation_stops.retried(
        conn, "gap_follow_up", "gap_exports", "Which exports exist?"
    )
    assert automation_stops.stops(conn) == []
    assert not automation_stops.retry(conn, "gap_follow_up", "gap_exports")


def test_stops_lists_only_stopped_rows_newest_first(conn):
    automation_stops.fail(
        conn,
        "audience_review",
        "grants:stm_login:external",
        '["label","Login supports SSO."]',
        "No valid decision.",
        retries=2,
        now=NOW,
    )
    automation_stops.stop(
        conn,
        "connect",
        "stm_export",
        "Exports include invoices.",
        "The connect run failed.",
        failures=3,
        now=NOW + timedelta(minutes=2),
    )

    assert [item.item_id for item in automation_stops.stops(conn)] == ["stm_export"]
