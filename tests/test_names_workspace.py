from __future__ import annotations

import json
import sqlite3

import pytest

from mycelium import auth, backup, embed, mention_worker, server, store
from mycelium import names_workspace as names
from test_auth import _app


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", lambda text: [1.0] + [0.0] * 767)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    store.reset_substrate()
    server._ctx = None
    server.init(tmp_path)
    return server


def entity(label: str) -> str:
    return server.upsert_entity(name=label, description=label + " description")[
        "entity_id"
    ]


def alias(entity_id: str, text: str) -> str:
    return server.upsert_name(text, entity_id)["name_id"]


def apply(action: names.Action) -> names.Applied:
    view = names.preview(server._db(), action)
    return names.apply(
        names.ApplyRequest(action=action, expected_revision=view.revision)
    )


def test_preferred_name_changes_all_readers_and_survives_backup(srv, tmp_path):
    eid = entity("Accounts")
    preferred = alias(eid, "Workspaces")
    apply(names.PreferName(kind="prefer", entity_id=eid, name_id=preferred))
    conn = srv._db()
    assert names.concept(conn, eid).label == "Workspaces"
    assert store.list_entities(conn)[0]["primary_name"] == "Workspaces"
    assert store.substrate_dump(conn)["entities"][0]["name"] == "Workspaces"
    assert srv.get_entity(eid)["names"][0]["text"] == "Workspaces"
    assert srv.search_entities("Accounts")["entities"][0]["name"] == "Workspaces"
    archive = tmp_path / "snapshot.tar.gz"
    backup.export_substrate(tmp_path, archive)
    restored = tmp_path / "restored"
    backup.import_substrate(archive, restored)
    with store.connect(restored / "mycelium.db") as fresh:
        assert names.concept(fresh, eid).label == "Workspaces"
        assert fresh.execute("PRAGMA foreign_key_check").fetchall() == []


def test_correction_removes_old_matching_and_generates_new_plural(srv):
    eid = entity("dashboard")
    name_id = store.get_name_by_text(srv._db(), "dashboard")["id"]
    statement_id = srv.upsert_statement(
        kind="state", text="The dashboard contains dashboards.", links=[]
    )["statement_id"]
    apply(
        names.CorrectAlias(
            kind="correct", entity_id=eid, name_id=name_id, text="workbench"
        )
    )
    mention_worker.drain(srv._db())
    assert store.get_name_by_text(srv._db(), "dashboard") is None
    assert store.get_name_by_text(srv._db(), "dashboards") is None
    assert store.get_name_by_text(srv._db(), "workbenches") is not None
    assert store.get_mentions(srv._db(), statement_id) == []
    assert (
        store.get_statement(srv._db(), statement_id)["text"]
        == "The dashboard contains dashboards."
    )


def test_move_and_remove_follow_generated_plural_and_clear_preference(srv):
    source = entity("dashboard")
    target = entity("Workspaces")
    name_id = store.get_name_by_text(srv._db(), "dashboard")["id"]
    apply(names.PreferName(kind="prefer", entity_id=source, name_id=name_id))
    apply(
        names.MoveAlias(
            kind="move", entity_id=source, name_id=name_id, target_entity_id=target
        )
    )
    assert names.concept(srv._db(), source).preferred_name_id is None
    assert store.get_name_by_text(srv._db(), "dashboards")["entity_id"] == target
    apply(names.PreferName(kind="prefer", entity_id=target, name_id=name_id))
    apply(names.RemoveAlias(kind="remove", entity_id=target, name_id=name_id))
    assert names.concept(srv._db(), target).label == "Workspaces"
    assert store.get_name_by_text(srv._db(), "dashboards") is None


def test_split_leaves_source_description_and_relationships(srv):
    source = entity("Workspaces")
    moved = alias(source, "dashboard")
    other = entity("Organizations")
    store.insert_entity_links(srv._db(), [(source, other, "belongs_to")])
    srv._db().commit()
    result = apply(
        names.SplitConcept(
            kind="split",
            entity_id=source,
            name_ids=[moved],
            preferred_name_id=moved,
            description="A separate overview",
        )
    )
    assert result.entity_id != source
    assert names.concept(srv._db(), result.entity_id).label == "dashboard"
    assert (
        store.get_name_by_text(srv._db(), "dashboards")["entity_id"] == result.entity_id
    )
    assert store.get_entity_links_outgoing(srv._db(), source) == [(other, "belongs_to")]
    assert store.get_entity_links_outgoing(srv._db(), result.entity_id) == []
    assert names.concept(srv._db(), source).description == "Workspaces description"


def test_merge_preview_matches_applied_relationships_and_chosen_description(srv):
    source = entity("Workspaces")
    target = entity("Organizations")
    third = entity("Accounts")
    preferred = store.get_name_by_text(srv._db(), "Workspaces")["id"]
    conn = srv._db()
    store.insert_entity_links(
        conn, [(source, target, "related_to"), (source, third, "belongs_to")]
    )
    store.insert_entity_links(conn, [(target, third, "belongs_to")])
    conn.commit()
    action = names.MergeConcepts(
        kind="merge",
        entity_id=source,
        target_entity_id=target,
        preferred_name_id=preferred,
        description="Chosen description",
    )
    view = names.preview(conn, action)
    result = apply(action)
    assert result.entity_id == target
    assert store.get_entity_by_id(conn, source) is None
    assert names.concept(conn, target).label == "Workspaces"
    assert names.concept(conn, target).description == "Chosen description"
    assert names.detail(conn, target).relationships == view.relationships_after
    history = names.detail(conn, target).history
    assert any(
        json.loads(row.context_json or "{}").get("vocabulary_action", {}).get("kind")
        == "merge"
        for row in history
    )


@pytest.mark.parametrize("changed", ["alias", "statement", "relationship"])
def test_stale_preview_refuses_changes_atomically(srv, changed):
    eid = entity("Workspaces")
    action = names.AddAlias(kind="add", entity_id=eid, text="Projects")
    view = names.preview(srv._db(), action)
    if changed == "alias":
        alias(eid, "Teams")
    elif changed == "statement":
        srv.upsert_statement(
            kind="state", text="Projects contain workspaces.", links=[]
        )
    else:
        target = entity("Accounts")
        store.insert_entity_links(srv._db(), [(eid, target, "belongs_to")])
        srv._db().commit()
    with pytest.raises(names.Conflict):
        names.apply(names.ApplyRequest(action=action, expected_revision=view.revision))
    assert store.get_name_by_text(srv._db(), "Projects") is None


def test_generated_names_cannot_be_independently_edited(srv):
    eid = entity("dashboard")
    generated = store.get_name_by_text(srv._db(), "dashboards")["id"]
    for action in [
        names.RemoveAlias(kind="remove", entity_id=eid, name_id=generated),
        names.PreferName(kind="prefer", entity_id=eid, name_id=generated),
    ]:
        with pytest.raises(ValueError, match="source name"):
            names.preview(srv._db(), action)


def test_ambiguous_short_names_remain_visible_as_candidates(srv):
    eid = entity("SSO")
    sid = srv.upsert_statement(
        kind="state", text="SSO is required for administrators.", links=[]
    )["statement_id"]
    detail = names.detail(srv._db(), eid)
    assert detail.example_count == 1
    assert detail.examples[0].id == sid


@pytest.mark.parametrize("role", ["reader", "drafter"])
def test_writer_authorization_enforced_for_preview_and_apply(
    tmp_path, monkeypatch, role
):
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "names-workspace-test-secret")
    with _app(tmp_path, monkeypatch, auth_mode="on") as client:
        user_id = auth.create_user(
            server._auth_db(), name=role, role=role, type="human"
        )
        token, _ = auth.issue_token(
            server._auth_db(), user_id=user_id, name=role, scope=role
        )
        server._auth_db().commit()
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            client.get("/api/names-workspace", headers=headers).json()["can_write"]
            is False
        )
        action = {"kind": "add", "entity_id": "ent_missing", "text": "Denied"}
        assert (
            client.post(
                "/api/names-workspace/preview", json={"action": action}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/names-workspace/apply",
                json={"action": action, "expected_revision": "x"},
                headers=headers,
            ).status_code
            == 403
        )


def test_http_applies_only_previewed_revision_and_validates_action(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch) as client:
        eid = client.post(
            "/upsert-entity", json={"name": "Accounts", "description": ""}
        ).json()["entity_id"]
        action = {"kind": "add", "entity_id": eid, "text": "Workspaces"}
        preview = client.post("/api/names-workspace/preview", json={"action": action})
        assert preview.status_code == 200
        body = {"action": action, "expected_revision": preview.json()["revision"]}
        assert client.post("/api/names-workspace/apply", json=body).status_code == 200
        assert client.post("/api/names-workspace/apply", json=body).status_code == 409
        assert (
            client.post(
                "/api/names-workspace/preview", json={"action": {**action, "text": " "}}
            ).status_code
            == 422
        )
        assert (
            client.get("/api/names-workspace?q=workspace").json()["entities"][0]["id"]
            == eid
        )


def test_preferred_name_migration_preserves_legacy_names():
    from mycelium.migrations import _migration_v13_preferred_names

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE entities(id TEXT PRIMARY KEY, description TEXT); CREATE TABLE names(id TEXT PRIMARY KEY, text TEXT, entity_id TEXT);"
    )
    conn.execute("INSERT INTO entities VALUES ('ent_old', 'Old description')")
    conn.execute("INSERT INTO names VALUES ('nam_old', 'Old name', 'ent_old')")
    _migration_v13_preferred_names(conn)
    assert conn.execute("SELECT preferred_name_id FROM entities").fetchone()[0] is None
    assert conn.execute("SELECT text FROM names").fetchone()[0] == "Old name"
