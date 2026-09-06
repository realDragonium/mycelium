import json
import threading
from dataclasses import replace

import pytest
from pydantic import ValidationError

from mycelium import auth, github_credentials, prompt_store
from mycelium import product_settings as settings
from mycelium.ask.config import AskConfig, for_depth
from mycelium.model_capacity import Capacity
from test_internal_draft_review import running_app as running_app


@pytest.fixture
def db(tmp_path):
    conn = prompt_store.connect(tmp_path / "prompts.db")
    prompt_store.migrate(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS instance_settings_migrations(name TEXT PRIMARY KEY)"
    )
    conn.commit()
    prompt_store.use_connection(conn)
    prompt_store.save(
        conn,
        type="guideline-set",
        name="kb-authoring/guidance",
        text="Write useful documents.",
    )
    yield conn
    conn.close()


ADMIN = auth.Principal(id="admin", name="Admin", role="admin", type="human")


def save(body):
    current = settings.editable(body, prompt_store.connection())
    return settings.save(
        settings.SaveSettings(revision=current.revision, settings=body), ADMIN
    )


def test_import_once_preserves_runtime_budgets_and_ignores_later_environment(
    db, monkeypatch
):
    monkeypatch.setenv("MYCELIUM_ASK_WALL_CLOCK_S", "32.5")
    monkeypatch.setenv("MYCELIUM_INGEST_OP_CAP", "73")
    with prompt_store._writing(db):
        settings.initialize(db, import_environment=True)
    monkeypatch.setenv("MYCELIUM_ASK_WALL_CLOCK_S", "1000")
    with prompt_store._writing(db):
        settings.initialize(db, import_environment=True)
    assert settings.get(settings.AskSettings).wall_clock_s == 32.5
    assert settings.get(settings.IngestSettings).op_cap == 73
    assert settings.get(settings.ResearchSettings).op_cap == 150
    quick = for_depth(AskConfig.from_env(), "quick")
    assert (quick.op_cap, quick.wall_clock_s, quick.request_timeout_s) == (8, 25, 20)
    assert not quick.enforce_floor


def test_fresh_and_restored_instances_ignore_legacy_environment(db, monkeypatch):
    monkeypatch.setenv("MYCELIUM_ASK_OP_CAP", "999")
    db.execute(
        "INSERT INTO instance_settings_migrations VALUES ('environment-import-disabled')"
    )
    db.commit()
    with prompt_store._writing(db):
        settings.initialize(db, import_environment=True)
    assert settings.get(settings.AskSettings).op_cap == 25


def test_independent_cas_and_unchanged_save(db):
    one = save(settings.AskSettings(max_tokens=1000))
    save(settings.IngestSettings(max_tokens=2000))
    assert settings.get(settings.AskSettings).max_tokens == 1000
    assert save(one.settings).revision == one.revision
    with pytest.raises(settings.Conflict):
        settings.save(
            settings.SaveSettings(revision=0, settings=settings.AskSettings()), ADMIN
        )
    reader = replace(ADMIN, role="reader")
    with pytest.raises(auth.RoleRequired):
        settings.save(
            settings.SaveSettings(revision=1, settings=settings.AskSettings()), reader
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_tokens", 0),
        ("op_cap", -1),
        ("max_retries", -1),
        ("request_timeout_s", float("nan")),
        ("wall_clock_s", float("inf")),
        ("max_tokens", True),
    ],
)
def test_limits_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        settings.AskSettings.model_validate({field: value})


def test_invalid_import_stays_disabled_without_persisting_raw_input(db, monkeypatch):
    secret = "do-not-store-this-credential"
    monkeypatch.setenv("MYCELIUM_SOURCES", '{"token":"' + secret + '"}')
    with prompt_store._writing(db):
        settings.initialize(db, import_environment=True)
    assert (
        secret
        not in db.execute(
            "SELECT body_json FROM product_settings WHERE section = 'sources'"
        ).fetchone()[0]
    )
    with pytest.raises(settings.Unavailable):
        settings.get(settings.SourcesSettings)
    save(settings.SourcesSettings())
    assert settings.get(settings.SourcesSettings).sources == ()


def test_legacy_sources_and_destinations_import_bindings_without_tokens(
    db, monkeypatch
):
    monkeypatch.setenv("GITHUB_TEST_TOKEN", "fixture-private-token")
    monkeypatch.setenv(
        "MYCELIUM_SOURCES",
        json.dumps(
            {
                "api": {
                    "owner": "acme",
                    "repo": "api",
                    "ref": "dev",
                    "token_env": "GITHUB_TEST_TOKEN",
                }
            }
        ),
    )
    monkeypatch.setenv(
        "MYCELIUM_DOC_DESTINATIONS",
        json.dumps(
            {
                "docs": {
                    "path_template": "docs/{slug}.md",
                    "config": {
                        "owner": "acme",
                        "repo": "docs",
                        "base_branch": "main",
                        "token_env": "GITHUB_TEST_TOKEN",
                    },
                }
            }
        ),
    )
    with prompt_store._writing(db):
        settings.initialize(db, import_environment=True)
    source = settings.get(settings.SourcesSettings).sources[0]
    destination = settings.get(settings.DocumentationSettings).destinations[0]
    assert source.binding == destination.binding
    assert source.ref == "dev"
    assert destination.destination().settings == {
        "owner": "acme",
        "repo": "docs",
        "base_branch": "main",
        "host": "github.com",
        "token_env": "GITHUB_TEST_TOKEN",
    }
    assert "fixture-private-token" not in settings.archive(db).model_dump_json()
    monkeypatch.delenv("MYCELIUM_SOURCES")
    monkeypatch.delenv("MYCELIUM_DOC_DESTINATIONS")
    from mycelium.research.sources import load_sources

    assert load_sources()["api"].repo == "api"


def test_binding_requires_deployment_owned_reference(db, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_GITHUB_CREDENTIALS",
        json.dumps(
            {"github": {"host": "github.com", "token_env": "GITHUB_TEST_TOKEN"}}
        ),
    )
    monkeypatch.setenv("GITHUB_TEST_TOKEN", "fixture-private-token")
    source = settings.SourceSettings(
        name="api", owner="acme", repo="api", binding="unknown"
    )
    with pytest.raises(ValueError, match="binding is unavailable"):
        save(settings.SourcesSettings(sources=(source,)))
    save(
        settings.SourcesSettings(
            sources=(
                source.model_copy(
                    update={"binding": "github", "host": "other.example"}
                ),
            )
        )
    )
    from mycelium.research.sources import load_sources

    assert load_sources()["api"].host == "github.com"
    assert github_credentials.choices()[0].model_dump() == {
        "name": "github",
        "host": "github.com",
        "available": True,
    }


def test_capacity_shrinks_and_grows_without_replacing_active_slots():
    limit = 2
    gate = Capacity(lambda: limit)
    assert gate.acquire(False) and gate.acquire(False)
    limit = 1
    gate.changed()
    gate.release()
    assert not gate.acquire(False)
    gate.release()
    assert gate.acquire(False)
    waiting = threading.Event()
    entered = threading.Event()

    def worker():
        waiting.set()
        gate.acquire()
        entered.set()
        gate.release()

    thread = threading.Thread(target=worker)
    thread.start()
    assert waiting.wait(1)
    limit = 2
    gate.changed()
    assert entered.wait(1)
    thread.join(1)
    gate.release()


def test_archive_round_trip_and_corruption_fails_closed(db, tmp_path):
    save(settings.AskSettings(max_tokens=123))
    archived = settings.archive(db)
    other = prompt_store.connect(tmp_path / "other.db")
    prompt_store.migrate(other)
    with prompt_store._writing(other):
        settings.restore(
            other, settings.Archive.model_validate_json(archived.model_dump_json())
        )
    assert settings.get(settings.AskSettings, conn=other).max_tokens == 123
    db.execute("UPDATE product_settings SET body_json = '{}' WHERE section = 'ask'")
    db.commit()
    with pytest.raises(ValidationError):
        settings.archive(db)
    other.close()


def test_http_saves_typed_lists_and_rejects_invalid_input(running_app, monkeypatch):
    client, _ = running_app
    monkeypatch.setenv(
        "MYCELIUM_GITHUB_CREDENTIALS",
        json.dumps({"github": {"token_env": "GITHUB_TEST_TOKEN"}}),
    )
    initial = client.get("/api/product-settings")
    assert initial.status_code == 200
    current = next(
        item
        for item in initial.json()["sections"]
        if item["settings"]["kind"] == "sources"
    )
    body = {
        "revision": current["revision"],
        "settings": {
            "kind": "sources",
            "sources": [
                {"name": "api", "owner": "acme", "repo": "api", "binding": "github"}
            ],
        },
    }
    response = client.patch("/api/product-settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["sources"][0]["binding"] == "github"
    assert client.patch("/api/product-settings", json=body).status_code == 409
    assert (
        client.patch(
            "/api/product-settings",
            json={"revision": 1, "settings": {"kind": "ask", "max_tokens": 0}},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/product-settings",
            json={
                "revision": 1,
                "settings": {
                    "kind": "sources",
                    "sources": [{"name": "bad", "owner": "../acme", "repo": "api"}],
                },
            },
        ).status_code
        == 422
    )


def test_research_runner_keeps_admitted_source_and_limits(db, tmp_path, monkeypatch):
    from mycelium import research, research_runs

    source = settings.SourceSettings(
        name="api", owner="acme", repo="original", ref="main"
    )
    save(settings.SourcesSettings(sources=(source,)))
    save(settings.ResearchSettings(max_tokens=1234))
    runner = research_runs._default_runner(str(tmp_path), "api")
    save(
        settings.SourcesSettings(
            sources=(
                settings.SourceSettings(
                    name="api", owner="acme", repo="replacement", ref="dev"
                ),
            )
        )
    )
    save(settings.ResearchSettings(max_tokens=9876))
    observed = []

    def execute(topic, source, *, config, emitter):
        observed.append((source.repo, source.ref, config.max_tokens))

    monkeypatch.setattr(research, "run_research", execute)
    runner("topic", source="api")
    assert observed == [("original", "main", 1234)]


def test_document_destination_change_refuses_old_delivery_coordinates(db, monkeypatch):
    from mycelium import doc_runs, docs_store
    from mycelium.docgen import destinations
    from mycelium.docgen.schema import CurrentDocument

    monkeypatch.setenv(
        "MYCELIUM_GITHUB_CREDENTIALS",
        json.dumps({"github": {"token_env": "GITHUB_TEST_TOKEN"}}),
    )
    original = settings.DestinationSettings(
        name="docs",
        owner="acme",
        repo="original",
        base_branch="main",
        path_template="docs/{slug}.md",
        binding="github",
    )
    save(settings.DocumentationSettings(destinations=(original,)))
    admitted = destinations.load_destinations()
    conn = docs_store.connect(":memory:")
    docs_store.migrate(conn)
    document_id = docs_store.upsert_document(
        conn, slug="page", title="Page", body="Old"
    )
    docs_store.record_delivery(
        conn,
        document_id,
        destination="docs",
        path="docs/page.md",
        reference="https://github.com/acme/original/pull/1",
        content_revision="a" * 40,
        target=destinations.target_identity(admitted["docs"]),
    )
    changed = settings.DestinationSettings(
        name="docs",
        owner="acme",
        repo="replacement",
        base_branch="main",
        path_template="docs/{slug}.md",
        binding="github",
    )
    save(settings.DocumentationSettings(destinations=(changed,)))
    observed = []

    def read(config, *args):
        observed.append(destinations.destination_coordinates(config)["repo"])
        return CurrentDocument(body="Remote")

    monkeypatch.setattr(destinations, "read_document", read)
    assert doc_runs._load_current_document(conn, document_id, admitted).body == "Remote"
    assert observed == ["original"]
    with pytest.raises(destinations.DestinationError, match="destination has changed"):
        doc_runs._load_current_document(conn, document_id)
    conn.close()


def test_invalid_bindings_do_not_disable_unrelated_settings(db, monkeypatch):
    monkeypatch.setenv("MYCELIUM_GITHUB_CREDENTIALS", "invalid")
    view = settings.view(ADMIN)
    assert view.github_bindings == []
    assert view.github_configuration_error
    assert len(view.sections) == len(settings.DEFAULTS)
    save(settings.AskSettings(max_tokens=99))
    assert settings.get(settings.AskSettings).max_tokens == 99


def test_documentation_default_must_name_existing_guidelines(db):
    with pytest.raises(ValueError, match="existing guideline set"):
        save(settings.DocumentationSettings(guideline_set="misspelled"))
    assert settings.view(ADMIN).guideline_sets == ["kb-authoring"]


def test_http_concurrency_save_updates_existing_request_limiter(running_app):
    from mycelium import server

    client, _ = running_app
    assert client.portal is not None
    limiter = client.portal.call(server._model_loop_limiter)
    response = client.patch(
        "/api/product-settings",
        json={"revision": 1, "settings": {"kind": "concurrency", "model_loops": 3}},
    )
    assert response.status_code == 200, response.text
    assert limiter.total_tokens == 3
    assert client.portal.call(server._model_loop_limiter) is limiter
    response = client.patch(
        "/api/product-settings",
        json={"revision": 2, "settings": {"kind": "concurrency", "model_loops": 2}},
    )
    assert response.status_code == 200, response.text


def test_backup_preserves_disabled_legacy_settings_and_restore_provenance(
    tmp_path, monkeypatch
):
    from mycelium import backup
    from test_backup import _seed_substrate

    source = tmp_path / "source"
    source.mkdir()
    _seed_substrate(source)
    conn = prompt_store.connect(source / backup.PROMPTS_DB_NAME)
    prompt_store.migrate(conn)
    conn.execute(
        "INSERT INTO product_settings VALUES ('ingest', 7, ?)",
        (settings.IngestSettings(max_tokens=1234).model_dump_json(),),
    )
    secret = "invalid-legacy-credential-sentinel"
    monkeypatch.setenv("MYCELIUM_SOURCES", '{"token":"' + secret + '"}')
    prompt_store.initialize_settings(conn, import_environment=True)
    before = settings.archive(conn)
    assert secret not in before.model_dump_json()
    conn.close()

    archive_path = tmp_path / "settings.tar.gz"
    manifest = backup.export_substrate(source, archive_path)
    assert manifest["includes_product_settings"] is True
    monkeypatch.setenv(
        "MYCELIUM_SOURCES", '{"ambient":{"owner":"other","repo":"unrelated"}}'
    )
    target = tmp_path / "restored"
    backup.import_substrate(archive_path, target)
    restored = prompt_store.connect(target / backup.PROMPTS_DB_NAME)
    try:
        prompt_store.initialize_settings(restored, import_environment=True)
        assert settings.archive(restored) == before
        assert restored.execute(
            "SELECT 1 FROM instance_settings_migrations "
            "WHERE name = 'environment-import-disabled'"
        ).fetchone()
        with pytest.raises(settings.Unavailable):
            settings.get(settings.SourcesSettings, conn=restored)
        editable = settings.editable(settings.SourcesSettings(), restored)
        assert editable.configuration_error
        assert editable.revision == 1
        assert settings.get(settings.IngestSettings, conn=restored).max_tokens == 1234
        prompt_store.use_connection(restored)
        recovered = save(settings.SourcesSettings())
        assert recovered.revision == 2
        assert recovered.configuration_error is None
        assert settings.get(settings.SourcesSettings).sources == ()
    finally:
        prompt_store.reset()
        restored.close()


@pytest.mark.parametrize(
    "body_json",
    [
        "{}",
        '{"kind":"unknown","invalid_legacy_configuration":true}',
        '{"kind":"sources","invalid_legacy_configuration":false}',
        '{"kind":"sources","invalid_legacy_configuration":1}',
        '{"kind":"sources","invalid_legacy_configuration":"true"}',
        '{"kind":"sources","invalid_legacy_configuration":null}',
        '{"kind":"sources","invalid_legacy_configuration":true,"secret":"hidden"}',
        '{"kind":"sources","invalid_legacy_configuration":true,"sources":[]}',
    ],
)
def test_archive_rejects_corruption_and_inexact_disabled_markers(db, body_json):
    db.execute("INSERT INTO product_settings VALUES ('sources', 1, ?)", (body_json,))
    with pytest.raises(ValidationError):
        settings.archive(db)
    archive_json = (
        '{"sections":[{"revision":1,"settings":'
        + body_json
        + '}],"github_bindings":{}}'
    )
    with pytest.raises(ValidationError):
        settings.Archive.model_validate_json(archive_json)


def test_archive_rejects_marker_for_different_stored_section(db):
    marker = settings.InvalidLegacySettings(
        kind="sources", invalid_legacy_configuration=True
    )
    db.execute(
        "INSERT INTO product_settings VALUES ('ask', 1, ?)",
        (marker.model_dump_json(),),
    )
    with pytest.raises(ValueError, match="section does not match"):
        settings.archive(db)


def test_archived_marker_cannot_enter_admin_save_payload():
    with pytest.raises(ValidationError):
        settings.SaveSettings.model_validate_json(
            '{"revision":1,"settings":'
            '{"kind":"sources","invalid_legacy_configuration":true}}'
        )


def test_existing_valid_archive_payload_remains_compatible():
    original = {
        "sections": [
            settings.Snapshot(
                revision=4, settings=settings.AskSettings(max_tokens=321)
            ).model_dump(mode="json")
        ],
        "github_bindings": {},
    }
    archived = settings.Archive.model_validate_json(json.dumps(original))
    assert archived.model_dump(mode="json") == original
    assert isinstance(archived.sections[0].settings, settings.AskSettings)
