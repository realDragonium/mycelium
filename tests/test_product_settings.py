import json
import threading
from dataclasses import replace

import pytest
from pydantic import ValidationError

from mycelium import auth, github_credentials, prompt_store
from mycelium import product_settings as settings
from mycelium.ask.config import AskConfig, for_depth
from mycelium.model_capacity import Capacity


@pytest.fixture
def db(tmp_path):
    conn = prompt_store.connect(tmp_path / "prompts.db")
    prompt_store.migrate(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS instance_settings_migrations(name TEXT PRIMARY KEY)"
    )
    conn.commit()
    prompt_store.use_connection(conn)
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
