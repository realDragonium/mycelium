"""The curation work queue, over in-memory databases."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from mycelium import (
    agent_tasks,
    curation,
    drafts_store,
    knowledge_health,
    store,
    timestamps,
)

# Now rather than a fixed date: "connect next" filters claims by the clock.
NOW = datetime.now(UTC)


@pytest.fixture
def conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    for sid, kind, text in [
        ("stm_a", "event", "A user signs in with single sign-on."),
        ("stm_b", "state", "The workspace has single sign-on enabled."),
        ("stm_c", "rule", "An invoice export must finish within an hour."),
    ]:
        conn.execute(
            "INSERT INTO statements (id, kind, text, created_at) "
            "VALUES (?, ?, ?, '2026-08-01T00:00:00.000Z')",
            (sid, kind, text),
        )
    conn.execute("INSERT INTO entities (id) VALUES ('ent_sso')")
    conn.execute(
        "INSERT INTO names (id, text, entity_id) "
        "VALUES ('nam_sso', 'single sign-on', 'ent_sso')"
    )
    conn.execute("INSERT INTO statement_mentions VALUES ('stm_a', 'nam_sso')")
    return conn


@pytest.fixture
def drafts():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    drafts_store.migrate(conn)
    agent_tasks.migrate(conn)
    return conn


def _claim(conn, drafts, kind="isolated", *, who="agent-1", limit=5, now=NOW):
    chosen, renewed, _ = curation.claim(
        conn, drafts, kind, limit=limit, claimant=who, now=now
    )
    return [c.id for c in chosen], renewed


def test_claim_leases_items_nobody_else_holds(conn, drafts):
    first, _ = _claim(conn, drafts, limit=2)
    second, _ = _claim(conn, drafts, who="agent-2")

    assert first == ["stm_a", "stm_b"]
    assert second == ["stm_c"]
    assert _claim(conn, drafts, who="agent-1") == ([], ["stm_a", "stm_b"])


def test_an_expired_claim_frees_the_item(conn, drafts):
    _claim(conn, drafts, limit=1)

    later = NOW + curation.LEASE + timedelta(seconds=1)
    assert _claim(conn, drafts, who="agent-2", limit=1, now=later)[0] == ["stm_a"]


def test_item_carries_its_statement_and_concepts(conn, drafts):
    chosen, _, _ = curation.claim(
        conn, drafts, "isolated", limit=1, claimant="agent-1", now=NOW
    )

    assert chosen[0].statement is not None
    assert [c.model_dump() for c in chosen[0].statement.concepts] == [
        {"id": "ent_sso", "name": "single sign-on"}
    ]


def test_released_items_are_not_offered_again_until_they_change(conn, drafts):
    _claim(conn, drafts)
    curation.release(
        conn, ["stm_a"], "no_link", claimant="agent-1", now=NOW, reason="unrelated"
    )
    curation.release(conn, ["stm_b"], "skipped", claimant="agent-1", now=NOW)
    curation.release(conn, ["stm_c"], "proposed", claimant="agent-1", now=NOW)

    assert _claim(conn, drafts)[0] == ["stm_b"]
    conn.execute(
        "UPDATE statements SET text = 'A member signs in with single sign-on.', "
        "updated_at = ? WHERE id = 'stm_a'",
        (timestamps.of(NOW + timedelta(minutes=1)),),
    )
    assert _claim(conn, drafts)[0] == ["stm_a"]


def test_the_connect_pass_shares_the_memory(conn, drafts):
    knowledge_health.record_attempts(conn, {"stm_a": []})

    assert _claim(conn, drafts, limit=1)[0] == ["stm_b"]
    listed = knowledge_health.to_connect(conn, drafts, "isolated", limit=50)
    assert [i.id for i in listed.items] == ["stm_c"]


def test_release_refuses_items_the_caller_does_not_hold(conn, drafts):
    _claim(conn, drafts, limit=1)

    with pytest.raises(ValueError, match="not held by you: stm_a"):
        curation.release(conn, ["stm_a"], "skipped", claimant="agent-2", now=NOW)


def test_gaps_split_into_rephrase_requests_and_the_rest(conn, drafts):
    rephrase = store.create_knowledge_gap(
        conn,
        knowledge_health.REPHRASE_GAP_PREFIX + "say what the export is",
        statement_id="stm_c",
    )
    other = store.create_knowledge_gap(conn, "How are invoices numbered?")

    assert _claim(conn, drafts, "rephrase")[0] == [rephrase]
    assert _claim(conn, drafts, "gap")[0] == [other]


def test_a_proposed_gap_waits_on_its_draft(conn, drafts):
    gap = store.create_knowledge_gap(conn, "How are invoices numbered?")
    draft = drafts_store.create_draft(drafts, created_by="agent-1", session_id="s")
    _claim(conn, drafts, "gap")

    curation.release(
        conn, [gap], "proposed", claimant="agent-1", now=NOW, draft_id=draft
    )

    assert store.get_knowledge_gap(conn, gap)["draft_id"] == draft
    later = NOW + timedelta(days=1)
    assert _claim(conn, drafts, "gap", now=later)[0] == []


def _waiting_for_answer(drafts, *, changed=False):
    draft = drafts_store.create_draft(drafts, created_by="agent-1", session_id="s")
    drafts_store.set_submitted(drafts, draft)
    revision = drafts.execute(
        "SELECT revision FROM drafts WHERE id = ?", (draft,)
    ).fetchone()[0]
    drafts.execute(
        "UPDATE drafts SET review_assessment_json = json_object("
        "'application', 'needs_human', 'draft_revision', ?) WHERE id = ?",
        (revision - 1 if changed else revision, draft),
    )
    return draft


def test_questions_are_the_newest_gap_of_a_draft_waiting_for_an_answer(conn, drafts):
    waiting = _waiting_for_answer(drafts)
    changed = _waiting_for_answer(drafts, changed=True)
    store.create_knowledge_gap(conn, "Asked first.", draft_id=waiting)
    conn.execute("UPDATE knowledge_gaps SET created_at = '2026-01-01T00:00:00.000Z'")
    asked = store.create_knowledge_gap(conn, "Asked again.", draft_id=waiting)
    store.create_knowledge_gap(conn, "Asked of a changed draft.", draft_id=changed)

    assert _claim(conn, drafts, "question")[0] == [asked]
    assert _claim(conn, drafts, "gap", who="agent-2")[0] == []


def test_gap_outcomes_change_its_status_as_the_agent(conn, drafts):
    numbered = store.create_knowledge_gap(conn, "How are invoices numbered?")
    exported = store.create_knowledge_gap(conn, "Which exports exist?")
    _claim(conn, drafts, "gap")

    curation.release(
        conn, [numbered], "resolved", claimant="agent-1", now=NOW, draft_id="drf_1"
    )
    curation.release(
        conn,
        [exported],
        "not_applicable",
        claimant="agent-1",
        now=NOW,
        reason="Exports are documented elsewhere.",
    )

    resolved = store.get_knowledge_gap(conn, numbered)
    assert (resolved["resolved_by"], resolved["draft_id"]) == ("agent-1", "drf_1")
    dismissed = store.get_knowledge_gap(conn, exported)
    assert dismissed["dismissed_by"] == "agent-1"
    assert dismissed["closing_reason"] == "Exports are documented elsewhere."
    store.set_knowledge_gap_status(conn, exported, "reopen", "writer-1")
    assert _claim(conn, drafts, "gap", who="agent-2")[0] == [exported]
    store.set_knowledge_gap_status(conn, exported, "dismiss", "writer-1")
    assert store.get_knowledge_gap(conn, exported)["closing_reason"] is None


def test_an_outcome_its_kind_does_not_take_is_refused(conn, drafts):
    _claim(conn, drafts, limit=1)

    with pytest.raises(ValueError, match="isolated items cannot be released as"):
        curation.release(
            conn, ["stm_a"], "not_applicable", claimant="agent-1", now=NOW, reason="x"
        )


def test_summaries_count_holders_and_outcomes(conn, drafts):
    knowledge_health.record_attempts(conn, {"stm_c": []})
    _claim(conn, drafts, limit=1)
    curation.release(
        conn, ["stm_a"], "no_link", claimant="agent-1", now=NOW, reason="unrelated"
    )
    _claim(conn, drafts, who="agent-2", limit=1)

    isolated = curation.summaries(conn, drafts, NOW)[0]
    assert isolated.kind == "isolated"
    assert [(h.claimed_by, h.items) for h in isolated.claims] == [("agent-2", 1)]
    assert isolated.outcomes == {"looked": 1, "no_link": 1}
    assert isolated.attempted == 2
    assert curation.free(conn, "isolated", "agent-2") == 1


@pytest.fixture
def app(tmp_path, monkeypatch):
    from test_reviewed_application import _app

    with _app(tmp_path, monkeypatch) as client:
        yield client


def _as(role):
    from mycelium import auth

    return auth.current_principal.set(
        auth.Principal(id=f"{role}-1", name=role, role=role, type="human")
    )


def test_a_reader_cannot_claim_work(app):
    from mycelium import auth, server

    token = _as("reader")
    try:
        with pytest.raises(auth.RoleRequired):
            server.claim_curation_work("isolated")
    finally:
        auth.current_principal.reset(token)


def test_a_drafter_claims_proposes_with_evidence_and_releases(app):
    from mycelium import auth, server

    first = server.upsert_statement("event", "A user signs in.", [])["statement_id"]
    second = server.upsert_statement("state", "The user is signed in.", [])[
        "statement_id"
    ]
    token = _as("drafter")
    try:
        batch = server.claim_curation_work("isolated", limit=2)
        assert [i["id"] for i in batch["items"]] == sorted([first, second])
        assert [n["id"] for n in batch["items"][0]["neighbours"]] == [
            batch["items"][1]["id"]
        ]
        assert any(t["link_type"] == "establishes" for t in batch["link_types"])

        queued = server.add_links(
            links=[{"from_id": first, "to_id": second, "link_type": "establishes"}]
        )
        evidence = {
            "kind": "code",
            "path": "app/auth/session.py",
            "lines": "10-14",
            "excerpt": "session.signed_in = True",
            "claim": "Signing in sets the signed-in state.",
        }
        server.set_operation_evidence(
            queued["draft_id"], queued["operation_ref"], [evidence], queued["revision"]
        )
        server.release_curation_work([first], "proposed", draft_id=queued["draft_id"])
        server.release_curation_work([second], "no_link", reason="covered by first")
        draft = server.get_draft(queued["draft_id"])
    finally:
        auth.current_principal.reset(token)

    assert draft["ops"][0]["evidence"] == [evidence]
    token = _as("drafter")
    try:
        assert server.claim_curation_work("isolated", limit=2)["items"] == []
    finally:
        auth.current_principal.reset(token)


def test_only_the_creator_sets_operation_evidence(app):
    from mycelium import auth, server

    token = _as("drafter")
    try:
        queued = server.upsert_entity(name="Workspace", description="A tenant.")
    finally:
        auth.current_principal.reset(token)
    token = _as("writer")
    try:
        with pytest.raises(auth.RoleRequired, match="creator"):
            server.set_operation_evidence(
                queued["draft_id"], queued["operation_ref"], [], queued["revision"]
            )
    finally:
        auth.current_principal.reset(token)


@pytest.mark.parametrize(
    "evidence",
    [
        {"kind": "code", "excerpt": "x", "claim": "Shows it."},
        {"kind": "code", "path": "/etc/app.py", "claim": "Shows it."},
        {"kind": "code", "path": "../app.py", "claim": "Shows it."},
        {"kind": "ui", "url": "https://example.test/a", "claim": "two\nlines"},
        {"kind": "code", "path": "a.py", "excerpt": "x" * 1501, "claim": "Long."},
    ],
)
def test_evidence_must_be_located_short_and_one_line(evidence):
    with pytest.raises(ValueError):
        drafts_store.Evidence.model_validate(evidence)


@pytest.mark.parametrize("role", ["writer", "admin"])
def test_health_shows_holders_and_only_an_admin_frees_them(app, role):
    from mycelium import auth, server
    from mycelium.server import runtime

    server.upsert_statement("event", "A user signs in.", [])
    conn = runtime._auth_db()
    with store.transaction(conn):
        agent = auth.create_user(
            conn, name="Code agent", role="drafter", type="service"
        )
        user = auth.create_user(conn, name=role, role=role, type="human")
        raw, _ = auth.issue_token(conn, user_id=user, name="Fixture", scope=role)
    token = auth.current_principal.set(
        auth.Principal(id=agent, name="Code agent", role="drafter", type="service")
    )
    try:
        server.claim_curation_work("isolated")
    finally:
        auth.current_principal.reset(token)
    headers = {"Authorization": f"Bearer {raw}"}

    view = app.get("/api/knowledge-health", headers=headers).json()
    assert view["curation"][0]["claims"][0]["name"] == "Code agent"
    freed = app.post(
        "/api/knowledge-health/claims/free",
        json={"kind": "isolated", "claimed_by": agent},
        headers=headers,
    )
    assert freed.status_code == (200 if role == "admin" else 403)
