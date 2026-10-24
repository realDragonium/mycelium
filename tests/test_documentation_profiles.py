"""Profile configuration stays versioned, atomic, and available through dedicated HTTP routes."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

import pytest

from mycelium import ai_prompts, audiences, auth, guidelines, prompt_store, server
from mycelium import documentation_profiles as profiles
from mycelium.server import runtime
from test_prompt_texts import _app


@pytest.fixture
def db():
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    audiences.seed(conn)
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


def test_profile_and_prompt_routes_share_versions_and_validation(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch) as client:
        assert (
            client.put(
                "/api/documentation/prompts",
                json={
                    "type": guidelines.TYPE,
                    "name": "internal/guidance",
                    "text": "First step",
                    "revision": 0,
                },
            ).status_code
            == 200
        )
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
        assert (
            client.put(
                "/api/documentation/prompts",
                json={
                    "type": guidelines.TYPE,
                    "name": "internal/reference",
                    "text": "Updated template",
                    "revision": 1,
                },
            ).status_code
            == 200
        )
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
        assert [item["text"] for item in history] == ["Updated template", "Template"]
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
        assert client.get("/api/ai-instructions").json()["names"] == list(
            ai_prompts.ACTIONS
        )


@pytest.mark.parametrize("role, expected", [("writer", 200), ("drafter", 403)])
def test_prompt_routes_require_a_real_writer(tmp_path, monkeypatch, role, expected):
    from mycelium.http.authentication import AuthMiddleware

    async def resolve(*_):
        return principal(role)

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    with _app(tmp_path, monkeypatch, auth_mode="on") as client:
        prompt_store.save(
            prompt_store.connection(),
            type="doctrine",
            name="ingest",
            text="Edited instructions",
        )
        response = client.post(
            "/api/documentation/prompts/restore",
            json={"type": "doctrine", "name": "ingest", "version": 1, "revision": 2},
        )
        assert response.status_code == expected
        if expected == 200:
            assert response.json()["version"] == 3
            assert response.json()["created_by"] == role
        assert (
            client.request(
                "DELETE",
                "/api/documentation/profiles/kb-authoring",
                json={"revision": profiles.read("kb-authoring").revision},
            ).status_code
            == 403
        )


def test_read_only_http_cannot_save_or_restore(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch, auth_mode="on") as client:
        owner = auth.create_user(
            runtime._auth_db(), name="Read only", role="reader", type="human"
        )
        token, _ = auth.issue_token(
            runtime._auth_db(), user_id=owner, name="reader", scope="reader"
        )
        runtime._auth_db().commit()
        response = client.put(
            "/api/documentation/profiles/internal",
            headers={"Authorization": f"Bearer {token}"},
            json={"revision": "", "guidance": "Denied"},
        )
        assert response.status_code == 403
        restore = client.post(
            "/api/documentation/prompts/restore",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "doctrine", "name": "ingest", "version": 1, "revision": 1},
        )
        assert restore.status_code == 403
        assert server.get_prompt_text("doctrine", "ingest")["version"] == 1


def test_versioned_prompt_retirement_rejects_stale_heads_and_preserves_legacy_calls(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch) as client:
        first = client.put(
            "/api/documentation/prompts",
            json={
                "type": guidelines.TYPE,
                "name": "internal/reference",
                "text": "Version one",
                "revision": 0,
            },
        ).json()
        assert (
            client.put(
                "/api/documentation/prompts",
                json={
                    "type": guidelines.TYPE,
                    "name": "internal/reference",
                    "text": "Version two",
                    "revision": 1,
                },
            ).status_code
            == 200
        )
        body = {
            "type": guidelines.TYPE,
            "name": "internal/reference",
            "expected_version": first["version"],
        }
        response = client.post("/retire-prompt-text", json=body)
        assert response.status_code == 409
        assert (
            server.get_prompt_text(guidelines.TYPE, "internal/reference")["text"]
            == "Version two"
        )
        body["expected_version"] = 2
        assert client.post("/retire-prompt-text", json=body).json() == {"retired": True}
        assert client.post("/retire-prompt-text", json=body).status_code == 409
        body["expected_version"] = 3
        assert client.post("/retire-prompt-text", json=body).json() == {
            "retired": False
        }
        assert (
            client.post(
                "/api/documentation/prompts/restore",
                json={
                    "type": guidelines.TYPE,
                    "name": "internal/reference",
                    "version": 1,
                    "revision": 3,
                },
            ).status_code
            == 200
        )
        assert client.post("/retire-prompt-text", json=body).status_code == 409
        assert server.retire_prompt_text(guidelines.TYPE, "internal/reference") == {
            "retired": True
        }


def _with_audience(revision: str, audience: str | None) -> profiles.SaveProfile:
    return profiles.SaveProfile(
        revision=revision,
        guidance="Use known facts.",
        exposure="Keep internal.",
        audience=audience,
        templates=(profiles.Template(name="reference", text="Write a reference."),),
    )


def test_a_profile_writes_for_one_audience_and_only_admins_change_it(db):
    first = save()
    assert first.audience is None
    assert first.effective_audience == "internal-technical"
    with pytest.raises(auth.RoleRequired):
        profiles.save(
            "internal",
            _with_audience(first.revision, "external-technical"),
            principal("writer"),
        )
    with pytest.raises(ValueError, match="not live"):
        profiles.save(
            "internal", _with_audience(first.revision, "nobody"), principal("admin")
        )
    changed = profiles.save(
        "internal",
        _with_audience(first.revision, "external-technical"),
        principal("admin"),
    )
    assert changed.effective_audience == "external-technical"
    assert profiles.capture(db).audience("internal").id == "external-technical"
    kept = profiles.save(
        "internal",
        _with_audience(changed.revision, "external-technical").model_copy(
            update={"guidance": "Use only known facts."}
        ),
        principal("writer"),
    )
    assert kept.audience == "external-technical"


def test_a_retired_audience_leaves_its_profiles_not_ready(db):
    created = profiles.save(
        "partners",
        _with_audience("", "external-technical"),
        principal("writer"),
    )
    assert created.ready
    with pytest.raises(ValueError, match="Profiles still write"):
        audiences.retire(
            "external-technical",
            audiences.RetireAudience(revision=1),
            principal("admin"),
        )
    db.execute(
        "INSERT INTO prompt_texts (type, name, version, text, deleted, created_at) "
        "VALUES ('audience', 'external-technical', 2, '', 1, '2026-01-01')"
    )
    stale = profiles.read("partners")
    assert not stale.ready and stale.effective_audience is None
    assert profiles.capture(db).audience("partners") is None


def test_a_writer_sets_the_automation_policies_and_turns_them_off(db):
    first = save()
    assert (first.maintenance, first.plan_review, first.delivery) == (
        "manual",
        "person",
        "people",
    )

    def with_policy(
        revision: str,
        policy: profiles.Maintenance,
        planning: profiles.Planning = "off",
        **automation: str,
    ):
        return profiles.save(
            "internal",
            profiles.SaveProfile(
                revision=revision,
                guidance="Use known facts.",
                exposure="Keep internal.",
                maintenance=policy,
                planning=planning,
                templates=(
                    profiles.Template(name="reference", text="Write a reference."),
                ),
                **automation,
            ),
            principal("writer"),
        )

    automatic = with_policy(first.revision, "auto-revise")
    assert automatic.maintenance == "auto-revise"
    assert profiles.capture(db).profiles[0].maintenance == "auto-revise"
    assert profiles.capture(db).catalogue() == {"internal": ["reference"]}
    planned = with_policy(automatic.revision, "manual", "write")
    assert (planned.maintenance, planned.planning) == ("manual", "write")
    assert profiles.capture(db).profiles[0].planning == "write"
    assert profiles.capture(db).catalogue() == {"internal": ["reference"]}
    reviewed = with_policy(
        planned.revision, "manual", plan_review="ai", delivery="agents"
    )
    assert (reviewed.plan_review, reviewed.delivery) == ("ai", "agents")
    snapshot = profiles.capture(db).profiles[0]
    assert (snapshot.plan_review, snapshot.delivery) == ("ai", "agents")
    assert profiles.capture(db).catalogue() == {"internal": ["reference"]}
    off = with_policy(reviewed.revision, "manual")
    assert (off.planning, off.plan_review, off.delivery) == ("off", "person", "people")
    with pytest.raises(ValueError, match="Maintenance must be one of"):
        profiles.save_text(
            guidelines.TYPE, "internal/maintenance", "always", principal("writer")
        )
    with pytest.raises(ValueError, match="Planning must be one of"):
        profiles.save_text(
            guidelines.TYPE, "internal/planning", "always", principal("writer")
        )
    with pytest.raises(ValueError, match="Delivery must be one of"):
        profiles.save_text(
            guidelines.TYPE, "internal/delivery", "always", principal("writer")
        )
