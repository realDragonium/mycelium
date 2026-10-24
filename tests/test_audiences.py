"""Documentation audiences: configuration, statement labels, the labeller and
the hard read boundary a documentation run sees."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from functools import partial

import pytest

from mycelium import (
    ai,
    audience_labelling,
    audiences,
    auth,
    product_settings,
    prompt_store,
    store,
)
from mycelium.audiences import Audience
from product_settings_helpers import connection as product_connection
from product_settings_helpers import set_product

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


def test_older_instances_get_the_seeded_includes_once(prompts):
    for audience_id, body in audiences.SEEDS:
        prompt_store._append(
            prompts,
            type=audiences.TYPE,
            name=audience_id,
            text=body.model_dump_json(exclude={"includes"}),
            deleted=0,
            created_by="seed",
        )
    assert all(not item.includes for item in audiences.live(prompts))

    audiences.seed(prompts)
    audiences.seed(prompts)

    live = {item.id: item for item in audiences.live(prompts)}
    assert live["external-technical"].sees == {
        "external-technical",
        "external-non-technical",
    }
    assert live["internal-technical"].sees == set(live)
    assert len(prompt_store.history(prompts, audiences.TYPE, "external-technical")) == 3


def test_includes_refuse_cycles_and_external_audiences_reaching_internal_ones(
    prompts,
):
    def includes(audience_id: str, *included: str, revision: int = 1) -> None:
        current = next(i for i in audiences.live(prompts) if i.id == audience_id)
        audiences.save(
            audience_id,
            audiences.SaveAudience(
                name=current.name,
                scope=current.scope,
                description=current.description,
                includes=list(included),
                revision=revision,
            ),
            ADMIN,
        )

    with pytest.raises(ValueError, match="include itself"):
        includes("external-non-technical", "external-technical")
    with pytest.raises(ValueError, match="internal"):
        includes("external-non-technical", "internal-non-technical")
    with pytest.raises(ValueError, match="internal"):
        audiences.save(
            "internal-technical",
            audiences.SaveAudience(
                name="Everyone",
                scope="external",
                description="x",
                includes=["internal-non-technical"],
                revision=1,
            ),
            ADMIN,
        )
    includes("internal-non-technical", "external-technical")
    assert audiences.sees_of("internal-non-technical") == {
        "internal-non-technical",
        "external-technical",
        "external-non-technical",
    }


def test_a_profile_without_a_choice_writes_for_the_default_and_a_retired_choice_refuses():
    live = (EXTERNAL, INTERNAL)
    assert audiences.resolve(None, live) == INTERNAL
    assert audiences.resolve("external-technical", live) == EXTERNAL
    assert audiences.resolve("gone", live) is None


# --- statement labels ----------------------------------------------------------


def test_new_statements_are_queued_and_unlabelled_ones_fail_closed(db):
    sid = store.create_statement(db, "state", "the invoice is paid")
    assert _queued(db) == {sid}
    assert store.visible_statement_ids(db, frozenset({INTERNAL.id}), True) == {sid}
    assert (
        store.visible_statement_ids(db, frozenset({EXTERNAL.id}), False) == frozenset()
    )


def test_an_audience_sees_what_the_audiences_it_includes_see(db, prompts):
    general = store.create_statement(db, "capability", "users can export invoices")
    technical = store.create_statement(db, "capability", "the export api pages")
    for sid, granted in (
        (general, "external-non-technical"),
        (technical, "external-technical"),
    ):
        store.audience_labels.set_label(
            db, sid, [granted], source="curator", reason="r", labelled_by="c"
        )

    def visible(audience_id: str) -> frozenset[str]:
        return store.visible_statement_ids(
            db, audiences.sees_of(audience_id), audience_id.startswith("internal")
        )

    assert visible("external-non-technical") == {general}
    assert visible("external-technical") == {general, technical}
    assert visible("internal-non-technical") == {general}
    assert visible("internal-technical") == {general, technical}


def test_a_text_change_drops_the_ai_label_and_flags_a_curator_decision(db):
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
    kept = store.audience_labels.get_label(db, curated)
    assert kept["source"] == "curator"
    assert kept["text_changed_at"] is not None
    assert _queued(db) == {ai_id}

    assert store.audience_labels.confirm_label(db, curated, labelled_by="c")
    assert store.audience_labels.get_label(db, curated)["text_changed_at"] is None
    assert not store.audience_labels.confirm_label(db, ai_id, labelled_by="c")


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


def test_backfill_progress_is_read_from_the_queue(db, prompts):
    """Nothing is held in memory, so a restarted server shows the same run."""
    first, second = (
        store.create_statement(db, "state", text)
        for text in ("a login fails", "a login locks")
    )
    db.execute("DELETE FROM audience_label_queue")
    assert audience_labelling.status(db).backfill is None
    store.audience_labels.enqueue_backfill(db, relabel_ai=False)
    store.audience_labels.apply_ai_label(
        db, first, [], reason="r", model="m", cost_usd=0.01
    )

    progress = audience_labelling.status(db).backfill
    assert progress is not None
    assert (progress.queued, progress.labelled, progress.cost_usd) == (2, 1, 0.01)
    assert _queued(db) == {second}


# --- the labeller --------------------------------------------------------------


def _answer(*decisions: tuple[str, list[str]], narrowing: str = ""):
    calls: list[str] = []

    def call(task, config):
        calls.append(task.prompt)
        return (
            audience_labelling.Labelling(
                labels=[
                    audience_labelling.Decision(
                        statement_id=sid,
                        audiences=granted,
                        reason="because",
                        narrowing_reason=narrowing,
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
    assert store.audience_labels.label_pending(label) == ["external-technical"]
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


def test_without_credentials_the_worker_leaves_the_queue_untouched(
    db, prompts, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        audience_labelling.model_settings,
        "claude_configuration_error",
        lambda: "Configure Anthropic credentials on the server.",
    )
    store.create_statement(db, "state", "exports are csv")
    call, calls = _answer()

    assert audience_labelling.drain(db, call=call) == 0
    assert calls == []
    assert store.audience_labels.queue_counts(db) == (1, 0, None)


@pytest.mark.parametrize(
    "interruption", ["failure", "exhausted", "paused", "credentials"]
)
def test_backfill_continues_on_later_polls_until_nothing_is_waiting(
    db, prompts, monkeypatch, interruption
):
    at = datetime(2026, 10, 23, tzinfo=UTC)
    monkeypatch.setattr(
        store.audience_labels,
        "due_batch",
        partial(store.audience_labels.due_batch, now=at),
    )
    monkeypatch.setattr(
        store.audience_labels,
        "record_failure",
        partial(store.audience_labels.record_failure, now=at),
    )
    set_product(
        product_settings.AudienceLabellingSettings(automatic=False, batch_size=1)
    )
    first = store.create_statement(db, "state", "Workspaces have owners.")
    second = store.create_statement(db, "state", "Invoices can be exported.")
    blocked = True
    calls = []

    def call(task, config):
        sid = json.loads(task.prompt)["statements"][0]["statement_id"]
        calls.append(sid)
        if blocked:
            if interruption == "paused":
                raise ai.usage.Paused("Paused: monthly AI budget reached.")
            raise ai.ModelError("Provider unavailable.")
        answer, _ = _answer((sid, [EXTERNAL.id]))
        return answer(task, config)

    drain = audience_labelling.drain
    monkeypatch.setattr(
        audience_labelling, "drain", lambda conn: drain(conn, call=call)
    )
    monkeypatch.setattr(
        audience_labelling.model_settings,
        "credentials_error",
        lambda action: (
            "Missing credentials" if blocked and interruption == "credentials" else None
        ),
    )
    monkeypatch.setattr(audience_labelling, "_forced", threading.Event())
    assert audience_labelling.backfill(relabel_ai=False).queued == 2
    if interruption == "exhausted":
        db.execute(
            "UPDATE audience_label_queue SET attempts = ?",
            (store.audience_labels.MAX_ATTEMPTS - 1,),
        )

    audience_labelling.labelling_pass(db)
    assert audience_labelling._forced.is_set()
    assert store.audience_labels.due_batch(db, 1)
    if interruption in {"paused", "credentials"}:
        assert store.audience_labels.queue_counts(db) == (2, 0, None)
    else:
        assert len(calls) == 1
    blocked = False

    audience_labelling.labelling_pass(db)
    # A statement waiting out its backoff keeps the backfill going.
    assert audience_labelling._forced.is_set() == (interruption == "failure")
    assert not store.audience_labels.due_batch(db, 1)
    assert store.audience_labels.get_label(db, second if calls[0] == first else first)
    if interruption in {"paused", "credentials"}:
        assert _queued(db) == set()
    else:
        assert _queued(db) == {calls[0]}
        assert store.audience_labels.queue_counts(db)[:2] == (
            (0, 1) if interruption == "exhausted" else (1, 0)
        )
    store.create_statement(db, "state", "Login supports SSO.")

    audience_labelling.labelling_pass(db)
    # Only a backfill still in progress labels the new statement.
    assert bool(store.audience_labels.due_batch(db, 1)) == (interruption != "failure")


def test_a_statement_written_during_a_backfill_is_labelled_before_its_backlog(db):
    store.create_statement(db, "state", "Workspaces have owners.")
    store.create_statement(db, "state", "Login supports SSO.")
    db.execute("UPDATE audience_label_queue SET enqueued_at = '2026-10-23T00:00:00Z'")
    written = store.create_statement(db, "state", "Invoices can be exported.")

    assert [row["id"] for row in store.audience_labels.due_batch(db, 1)] == [written]


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
        # Internal technical includes external technical, so it sees it too.
        assert {item["id"] for item in saved["audiences"] if item["visible"]} == {
            "external-technical",
            "internal-technical",
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
        with store.transaction(conn):
            store.update_statement_text(conn, public, "invoices can be exported as CSV")
        changed = client.get(
            "/api/audiences/statements", params={"state": "text_changed"}
        ).json()
        assert [item["id"] for item in changed["statements"]] == [public]
        confirmed = client.post(f"/api/statements/{public}/audiences/confirm").json()
        assert confirmed["label"]["text_changed_at"] is None
        assert confirmed["label"]["audiences"] == ["external-technical"]
        assert (
            client.put(
                f"/api/statements/{public}/audiences",
                json={"audiences": ["no-such-audience"]},
            ).status_code
            == 400
        )


def test_an_edit_keeps_the_previous_audiences_unless_the_labeller_says_why(db, prompts):
    labels = store.audience_labels
    sid = store.create_statement(db, "rule", "an export holds 100 rows")
    labels.apply_ai_label(
        db, sid, ["external-non-technical"], reason="r", model="m", cost_usd=None
    )
    store.update_statement_text(db, sid, "an export holds 500 rows")
    store.update_statement_text(db, sid, "an export holds 1000 rows")
    narrower = (sid, ["internal-non-technical"])

    call, prompts_sent = _answer(narrower)
    audience_labelling.label_batch(db, call=call)

    sent = json.loads(prompts_sent[0])["statements"][0]
    assert sent["previous"]["text"] == "an export holds 100 rows"
    assert sent["previous"]["audiences"] == ["external-non-technical"]
    row = labels.get_label(db, sid)
    assert row is not None
    # Kept, though changed text still waits for a curator before it is external.
    assert labels.label_pending(row) == ["external-non-technical"]
    assert labels.label_audiences(row) == ["internal-non-technical"]
    assert labels.label_narrowed(row) is None

    store.update_statement_text(db, sid, "an export holds 1000 rows on the ledger")
    call, _ = _answer(narrower, narrowing="Names the internal ledger service.")
    audience_labelling.label_batch(db, call=call)

    row = labels.get_label(db, sid)
    assert row is not None
    assert labels.label_audiences(row) == ["internal-non-technical"]
    assert labels.label_narrowed(row) == {
        "previous": ["external-non-technical", "internal-non-technical"],
        "lost": ["external-non-technical", "external-technical"],
        "reason": "Names the internal ledger service.",
    }
