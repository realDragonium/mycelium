"""Profile configuration stays versioned, atomic, and shared by HTTP and MCP."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

import pytest

from mycelium import auth, guidelines, prompt_store, server
from mycelium import documentation_profiles as profiles
from test_prompt_texts import _app, _as


@pytest.fixture
def db():
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    prompt_store.use_connection(conn)
    yield conn
    prompt_store.reset()
    conn.close()


def principal(role: str) -> auth.Principal:
    return auth.Principal(id=role, name=role, role=role, type="human")


def save(name="internal", *, revision="", text="Write a reference.", user=None):
    return profiles.save(
        name,
        profiles.SaveProfile(
            revision=revision,
            guidance="Use known facts.",
            exposure="Keep internal.",
            templates=(profiles.Template(name="reference", text=text),),
        ),
        user or principal("writer"),
    )


def test_atomic_save_noop_cas_and_snapshot(db):
    first = save()
    captured = profiles.capture(db)
    refs = captured.references("internal", "reference")
    assert captured.catalogue() == {"internal": ["reference"]}
    assert asdict(refs["reference"])["version"] == 1
    assert captured.texts("internal", "reference") == (
        "Use known facts.",
        "Keep internal.",
        "Write a reference.",
    )
    assert save(revision=first.revision).revision == first.revision
    changed = save(revision=first.revision, text="Revised template.")
    assert changed.revision != first.revision
    assert captured.texts("internal", "reference")[2] == "Write a reference."
    with pytest.raises(profiles.Conflict):
        save(revision=first.revision)
    assert (
        profiles.capture(db).references("internal", "reference")["reference"].version
        == 2
    )


def test_atomic_save_rolls_back_all_slots_on_failure(db):
    first = save()
    db.execute(
        "CREATE TRIGGER reject_template BEFORE INSERT ON prompt_texts WHEN NEW.name = 'internal/reference' BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )
    request = profiles.SaveProfile(
        revision=first.revision,
        guidance="Changed guidance.",
        exposure="Changed disclosure.",
        templates=(profiles.Template(name="reference", text="Changed template."),),
    )
    with pytest.raises(sqlite3.IntegrityError):
        profiles.save("internal", request, principal("writer"))
    assert profiles.read("internal").revision == first.revision


def test_retirement_and_restore_keep_history_and_invalidate_old_revision(db):
    first = save()
    retired = profiles.retire("internal", first.revision, principal("admin"))
    assert retired.retired and retired.retired_templates == ("reference",)
    assert profiles.capture(db).catalogue() == {}
    restored = profiles.restore_text(
        profiles.RestoreText(
            type=guidelines.TYPE, name="internal/reference", version=1, revision=2
        ),
        principal("writer"),
    )
    assert restored.version == 3
    assert not profiles.read("internal").retired
    with pytest.raises(profiles.Conflict):
        save(revision=first.revision)
    with pytest.raises(ValueError, match="saved text version"):
        profiles.restore_text(
            profiles.RestoreText(
                type=guidelines.TYPE, name="internal/reference", version=2, revision=3
            ),
            principal("writer"),
        )


def test_writer_cannot_remove_existing_slots_and_drafter_cannot_save(db):
    first = save()
    with pytest.raises(auth.RoleRequired):
        profiles.save(
            "internal",
            profiles.SaveProfile(revision=first.revision, guidance="Only guidance"),
            principal("writer"),
        )
    with pytest.raises(auth.RoleRequired):
        save("denied", user=principal("drafter"))
    with pytest.raises(auth.RoleRequired):
        profiles.restore_text(
            profiles.RestoreText(
                type=guidelines.TYPE, name="internal/reference", version=1, revision=1
            ),
            principal("reader"),
        )
    assert profiles.read("internal").revision == first.revision


def test_default_profile_and_last_template_are_protected_from_both_paths(db):
    first = save("kb-authoring")
    with pytest.raises(ValueError, match="another default"):
        profiles.retire("kb-authoring", first.revision, principal("admin"))
    with pytest.raises(ValueError, match="another default"):
        profiles.retire_text(
            guidelines.TYPE, "kb-authoring/reference", principal("admin")
        )
    with pytest.raises(ValueError, match="another default"):
        profiles.save(
            "kb-authoring",
            profiles.SaveProfile(revision=first.revision, guidance="Keep guidance"),
            principal("admin"),
        )
    assert profiles.read("kb-authoring").revision == first.revision


def test_staged_prompt_saves_remain_compatible_and_invalidate_editor(db):
    profiles.save_text(
        guidelines.TYPE, "internal/guidance", "First step.", principal("writer")
    )
    incomplete = profiles.read("internal")
    assert not incomplete.ready
    assert any("Add a template" in issue for issue in incomplete.issues)
    profiles.save_text(
        guidelines.TYPE, "internal/reference", "Second step.", principal("writer")
    )
    assert profiles.read("internal").ready
    with pytest.raises(profiles.Conflict):
        save(revision=incomplete.revision)


def test_starter_seeding_respects_any_history_including_retirement(db):
    profiles.seed_starters(db)
    for row in prompt_store.list_current(db, guidelines.TYPE):
        prompt_store.delete(db, type=guidelines.TYPE, name=row["name"])
    count = db.execute("SELECT COUNT(*) FROM prompt_texts").fetchone()[0]
    profiles.seed_starters(db)
    assert db.execute("SELECT COUNT(*) FROM prompt_texts").fetchone()[0] == count
    assert profiles.capture(db).catalogue() == {}


def test_ui_and_mcp_share_versions_validation_and_roles(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch) as client:
        with _as("writer"):
            server.save_prompt_text(guidelines.TYPE, "internal/guidance", "First step")
        listing = client.get("/api/documentation/profiles").json()
        profile = next(
            item for item in listing["profiles"] if item["name"] == "internal"
        )
        assert not profile["ready"]
        body = {
            "revision": profile["revision"],
            "guidance": "First step",
            "exposure": "",
            "templates": [{"name": "reference", "text": "Template"}],
        }
        response = client.put("/api/documentation/profiles/internal", json=body)
        assert response.status_code == 200
        with _as("writer"):
            server.save_prompt_text(guidelines.TYPE, "internal/reference", "MCP update")
        assert (
            client.put("/api/documentation/profiles/internal", json=body).status_code
            == 409
        )
        assert (
            client.put(
                "/api/documentation/prompts",
                json={
                    "type": "protocol",
                    "name": "anything",
                    "text": "No",
                    "revision": 0,
                },
            ).status_code
            == 400
        )
        history = client.get(
            "/api/documentation/prompts/history",
            params={"type": guidelines.TYPE, "name": "internal/reference"},
        ).json()["versions"]
        assert [item["text"] for item in history] == ["MCP update", "Template"]
        restored = client.post(
            "/api/documentation/prompts/restore",
            json={
                "type": guidelines.TYPE,
                "name": "internal/reference",
                "version": 1,
                "revision": 2,
            },
        )
        assert restored.status_code == 200 and restored.json()["version"] == 3
        assert client.get("/api/ai-instructions").json()["names"] == [
            "ingest",
            "research",
            "docgen",
        ]


def test_generic_mcp_restore_preserves_writer_permission(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        with _as("writer"):
            server.save_prompt_text("doctrine", "ingest", "Edited instructions")
            restored = server.restore_prompt_text("doctrine", "ingest", 1, 2)
            assert restored["version"] == 3
        with _as("drafter"), pytest.raises(auth.RoleRequired):
            server.restore_prompt_text("doctrine", "ingest", 1, 3)
        with _as("writer"), pytest.raises(auth.RoleRequired):
            server.retire_documentation_profile(
                "kb-authoring", profiles.read("kb-authoring").revision
            )


def test_read_only_http_cannot_save_or_restore(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, auth_mode="on") as client:
        owner = auth.create_user(
            server._auth_db(), name="Read only", role="reader", type="human"
        )
        token, _ = auth.issue_token(
            server._auth_db(), user_id=owner, name="reader", scope="reader"
        )
        server._auth_db().commit()
        response = client.put(
            "/api/documentation/profiles/internal",
            headers={"Authorization": f"Bearer {token}"},
            json={"revision": "", "guidance": "Denied"},
        )
        assert response.status_code == 403
