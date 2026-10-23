"""Documentation audiences: configuration, statement labels, the labeller and
the hard read boundary a documentation run sees."""

from __future__ import annotations

import json

import pytest

from mycelium import (
    ai,
    audience_labelling,
    audiences,
    auth,
    prompt_store,
    store,
)
from mycelium.audiences import Audience
from product_settings_helpers import connection as product_connection

ADMIN = auth.Principal(id="a", name="admin", role="admin", type="human")
WRITER = auth.Principal(id="w", name="writer", role="writer", type="human")

INTERNAL = Audience("internal-technical", "Internal technical", "internal", "All.", 1)
EXTERNAL = Audience(
    "external-technical", "External technical", "external", "Integrators.", 1
)


@pytest.fixture
def prompts():
    conn = product_connection()
    audiences.seed(conn)
    return conn


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    store.use_substrate_connection(conn)
    try:
        yield conn
    finally:
        store.reset_substrate()
        conn.close()


def _queued(conn) -> set[str]:
    return {
        row["statement_id"]
        for row in conn.execute("SELECT statement_id FROM audience_label_queue")
    }


# --- configuration -------------------------------------------------------------


def test_seed_runs_once_and_never_resurrects_a_retired_audience(prompts):
    assert [item.id for item in audiences.live(prompts)][:2] == [
        "internal-non-technical",
        "internal-technical",
    ]
    audiences.retire("external-technical", audiences.RetireAudience(revision=1), ADMIN)
    audiences.seed(prompts)
    assert "external-technical" not in {item.id for item in audiences.live(prompts)}


def test_edits_keep_history_and_only_admins_make_them(prompts):
    request = audiences.SaveAudience(
        name="Partners", scope="external", description="Partner developers.", revision=1
    )
    with pytest.raises(auth.RoleRequired):
        audiences.save("external-technical", request, WRITER)
    saved = audiences.save("external-technical", request, ADMIN)
    assert saved.version == 2
    assert len(prompt_store.history(prompts, audiences.TYPE, "external-technical")) == 2
    with pytest.raises(audiences.Conflict):
        audiences.save("external-technical", request, ADMIN)


def test_the_last_internal_audience_cannot_be_retired_or_made_external(prompts):
    audiences.retire(
        "internal-non-technical", audiences.RetireAudience(revision=1), ADMIN
    )
    with pytest.raises(ValueError, match="at least one internal"):
        audiences.retire(
            "internal-technical", audiences.RetireAudience(revision=1), ADMIN
        )
    with pytest.raises(ValueError, match="at least one internal"):
        audiences.save(
            "internal-technical",
            audiences.SaveAudience(
                name="Everyone", scope="external", description="x", revision=1
            ),
            ADMIN,
        )


def test_a_profile_without_a_choice_writes_for_the_default_and_a_retired_choice_refuses():
    live = (EXTERNAL, INTERNAL)
    assert audiences.resolve(None, live) == INTERNAL
    assert audiences.resolve("external-technical", live) == EXTERNAL
    assert audiences.resolve("gone", live) is None


# --- statement labels ----------------------------------------------------------


def test_new_statements_are_queued_and_unlabelled_ones_fail_closed(db):
    sid = store.create_statement(db, "state", "the invoice is paid")
    assert _queued(db) == {sid}
    assert store.visible_statement_ids(db, INTERNAL.id, True) == {sid}
    assert store.visible_statement_ids(db, EXTERNAL.id, False) == frozenset()


def test_a_text_change_drops_the_ai_label_but_not_a_curator_decision(db):
    ai_id = store.create_statement(db, "state", "exports run nightly")
    curated = store.create_statement(db, "state", "workspaces have owners")
    store.audience_labels.set_label(
        db, ai_id, [EXTERNAL.id], source="ai", reason="public", model="m"
    )
    store.audience_labels.set_label(
        db, curated, [EXTERNAL.id], source="curator", reason="checked"
    )
    store.update_statement_text(db, ai_id, "exports run hourly")
    store.update_statement_text(db, curated, "workspaces have one owner")
    assert store.audience_labels.get_label(db, ai_id) is None
    assert store.audience_labels.get_label(db, curated)["source"] == "curator"
    assert _queued(db) == {ai_id}


def test_the_ai_never_overwrites_a_curator(db):
    sid = store.create_statement(db, "state", "sso uses saml")
    store.audience_labels.set_label(db, sid, [], source="curator", reason="no")
    assert not store.audience_labels.apply_ai_label(
        db, sid, [EXTERNAL.id], reason="yes", model="m", cost_usd=None
    )
    assert (
        store.audience_labels.label_audiences(store.audience_labels.get_label(db, sid))
        == []
    )


def test_deleting_a_statement_removes_its_label_and_queue_row(db):
    sid = store.create_statement(db, "state", "the dashboard renders")
    store.audience_labels.set_label(db, sid, [EXTERNAL.id], source="ai", reason="r")
    store.audience_labels.enqueue(db, [sid])
    store.delete_statement(db, sid)
    assert (
        db.execute("SELECT COUNT(*) FROM statement_audience_labels").fetchone()[0] == 0
    )
    assert _queued(db) == set()


def test_backfill_queues_unlabelled_and_optionally_ai_labels_never_curated(db):
    unlabelled, ai_id, curated = (
        store.create_statement(db, "state", text)
        for text in ("a login fails", "a login locks", "a login expires")
    )
    db.execute("DELETE FROM audience_label_queue")
    store.audience_labels.set_label(db, ai_id, [], source="ai", reason="r")
    store.audience_labels.set_label(db, curated, [], source="curator", reason="r")
    assert store.audience_labels.enqueue_backfill(db, relabel_ai=False) == 1
    assert _queued(db) == {unlabelled}
    assert store.audience_labels.enqueue_backfill(db, relabel_ai=True) == 2
    assert _queued(db) == {unlabelled, ai_id}


# --- the labeller --------------------------------------------------------------


def _answer(*decisions: tuple[str, list[str]]):
    calls: list[str] = []

    def call(task, config):
        calls.append(task.prompt)
        return (
            audience_labelling.Labelling(
                labels=[
                    audience_labelling.Decision(
                        statement_id=sid, audiences=granted, reason="because"
                    )
                    for sid, granted in decisions
                ]
            ),
            ai.Usage(input_tokens=1000, output_tokens=100),
        )

    return call, calls


def test_a_batch_stores_known_audiences_and_retries_what_the_model_skipped(db, prompts):
    first = store.create_statement(db, "state", "webhooks retry three times")
    second = store.create_statement(db, "state", "webhooks are signed")
    call, calls = _answer((first, ["external-technical", "made-up"]))

    assert audience_labelling.label_batch(db, call=call) == 1

    label = store.audience_labels.get_label(db, first)
    assert store.audience_labels.label_audiences(label) == ["external-technical"]
    assert label["source"] == "ai" and label["reason"] == "because"
    sent = json.loads(calls[0])
    assert {item["statement_id"] for item in sent["statements"]} == {first, second}
    assert "external-technical" in {item["id"] for item in sent["audiences"]}
    retry = db.execute(
        "SELECT attempts, next_attempt_at FROM audience_label_queue"
    ).fetchone()
    assert retry["attempts"] == 1 and retry["next_attempt_at"] is not None
    assert audience_labelling.label_batch(db, call=call) is None


def test_a_failed_batch_leaves_statements_unlabelled_and_backs_off(db, prompts):
    sid = store.create_statement(db, "state", "exports are csv")

    def failing(task, config):
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        audience_labelling.label_batch(db, call=failing)
    assert store.audience_labels.get_label(db, sid) is None
    assert store.audience_labels.queue_counts(db) == (1, 0, "provider down")


# --- HTTP ----------------------------------------------------------------------


def test_curators_override_labels_and_the_filter_finds_them(tmp_path, monkeypatch):
    from mycelium import server
    from test_prompt_texts import _app

    client = _app(tmp_path, monkeypatch)
    with client:
        conn = server._db()
        with store.transaction(conn):
            public = store.create_statement(conn, "state", "invoices can be exported")
            store.create_statement(conn, "state", "the billing queue drains hourly")

        listed = client.get("/api/audiences").json()
        assert {item["id"] for item in listed["audiences"]} >= {
            "internal-technical",
            "external-technical",
        }
        external = next(
            item for item in listed["audiences"] if item["id"] == "external-technical"
        )
        assert external["visible_statements"] == 0
        assert listed["unlabelled"] == 2

        saved = client.put(
            f"/api/statements/{public}/audiences",
            json={"audiences": ["external-technical"], "reason": "Public feature."},
        ).json()
        assert saved["label"]["source"] == "curator"
        assert {item["id"] for item in saved["audiences"] if item["visible"]} == {
            "external-technical"
        }

        found = client.get(
            "/api/audiences/statements",
            params={"audience": "external-technical", "visibility": "visible"},
        ).json()
        assert [item["id"] for item in found["statements"]] == [public]
        assert (
            client.get(
                "/api/audiences/statements", params={"state": "unlabelled"}
            ).json()["total"]
            == 1
        )

        assert (
            client.post(
                "/api/audiences/labelling/backfill", json={"relabel_ai": False}
            ).json()["queued"]
            == 1
        )
        # A page opened later still finds the backfill and its progress.
        progress = client.get("/api/audiences/labelling").json()["backfill"]
        assert (progress["queued"], progress["labelled"]) == (1, 0)
        assert (
            client.put(
                f"/api/statements/{public}/audiences",
                json={"audiences": ["no-such-audience"]},
            ).status_code
            == 400
        )
