"""Every schema and archive this repository has shipped carries forward.

Each directory in `migration_fixtures/` is a populated instance captured from
a historical build by `scripts/capture_migration_fixture.py`, plus an archive
that build exported. The current build starts on a copy of the instance
exactly as a deploy would (`server.init`), and the result must:

- reach the current substrate version with every database's schema equal to
  a fresh instance's, so a column added to a schema without a migration fails;
- keep every row it had, apart from rewrites declared in `REWRITES`;
- pass SQLite's integrity and foreign-key checks; and
- serve the captured statements through search and hydration.

The archive is restored into a fresh data directory — the path for a change
too awkward to migrate in place — and must keep every row the old build
archived and serve the same statements. Dropping a column breaks this for
older archives until the importer learns to discard it.

`test_newest_fixture_has_the_current_schema` keeps the set complete: change
any schema and it fails until a fixture of the new shape is captured, so the
shape the next migration starts from is always on hand.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

import instance_scenario
from mycelium import backup, embed, migrations, server, store
from mycelium.server import runtime


def _captured(fixture: Path) -> tuple[int, str]:
    meta = json.loads((fixture / "fixture.json").read_text(encoding="utf-8"))
    return meta["schema_version"], meta["captured_at"]


# Oldest first; one substrate version can have several fixtures when an
# auxiliary database changed shape under it.
FIXTURES = sorted(
    (p for p in (Path(__file__).parent / "migration_fixtures").iterdir() if p.is_dir()),
    key=_captured,
)

# (database, table) whose rows a migration deliberately rewrites or drops,
# with the reason. Rows elsewhere must survive the upgrade unchanged.
REWRITES: dict[tuple[str, str], str] = {
    ("mycelium.db", "entity_statement_links"): (
        "v14 drops the table once its rows are rescued; startup refuses otherwise"
    ),
    ("mycelium.db", "link_type_alias_embed_queue"): (
        "v15 drops the queue; nothing has drained it since the connect pipeline"
    ),
    ("mycelium.db", "statement_kind_glossary"): (
        "v17 rewrites the untouched seeded `rule` definition"
    ),
    ("mycelium.db", "entity_link_type_glossary"): (
        "v19 rewrites the untouched seeded `sub-type` definition"
    ),
    ("mycelium.db", "kind_link_matrix"): (
        "v18 drops the matrix; nothing has read it since the connect pipeline"
    ),
    ("mycelium.db", "connect_attempts"): (
        "v24 moves its rows into curation_attempts as the connect pass's looks"
    ),
    ("mycelium-prompts.db", "product_settings"): (
        "startup lifts a saved ingest wall clock still at the old 120 s default "
        "and drops the removed AI budget section"
    ),
    ("mycelium-drafts.db", "research_runs"): (
        "the drafts store drops the removed research feature's run history"
    ),
}


def _research_doctrine(row: dict) -> bool:
    return (row["type"], row["name"]) == ("doctrine", "research")


# Rows a store deliberately drops or rewrites, picked out by predicate. Every
# other row of these tables must still survive. The prompts store removes what
# the research feature left behind: its doctrine, model selection, settings
# sections and concurrency limit, and raises an ingest or documentation output
# budget still at its old default.
DROPPED_ROWS: dict[tuple[str, str], Callable[[dict], bool]] = {
    ("mycelium-prompts.db", "prompt_texts"): _research_doctrine,
    ("mycelium-prompts.db", "shipped_prompt_texts"): _research_doctrine,
    ("mycelium-prompts.db", "model_settings"): lambda row: row["action"] == "research",
    ("mycelium-prompts.db", "product_settings"): lambda row: (
        row["section"] in ("research", "sources")
        or "research_runs" in row["body_json"]
        or (row["section"], json.loads(row["body_json"]).get("max_tokens"))
        in (("ingest", 8000), ("docgen", 12000))
    ),
}

# Columns a migration deliberately removes, with the reason. Any other
# column a fixture had must still be there afterwards.
DROPPED_COLUMNS: dict[tuple[str, str, str], str] = {
    ("mycelium.db", "when_nodes", "link_kind"): (
        "v14 removes the discriminator once only statement conditions remain"
    ),
    ("mycelium.db", "link_type_aliases", "embedding"): (
        "v15 removes alias embeddings; only the connect pipeline read them"
    ),
    ("mycelium-auth.db", "users", "audience_id"): (
        "audiences no longer scope principals; the auth store drops the column"
    ),
    ("mycelium-auth.db", "mcp_tokens", "audience_id"): (
        "audiences no longer scope principals; the auth store drops the column"
    ),
    ("mycelium-auth.db", "oauth_codes", "audience_id"): (
        "audiences no longer scope principals; the auth store drops the column"
    ),
}


def _load(fixture: Path, data_dir: Path) -> None:
    data_dir.mkdir()
    for dump in fixture.glob("*.sql"):
        with closing(sqlite3.connect(data_dir / f"{dump.stem}.db")) as conn:
            conn.executescript(dump.read_text(encoding="utf-8"))


def _start(data_dir: Path) -> None:
    runtime._ctx = None
    server.init(data_dir)


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        name
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _schema(path: Path) -> dict:
    """Columns, keys, indexes and triggers, independent of the DDL's history
    (ALTER TABLE appends columns and keeps the original statement text)."""
    with closing(sqlite3.connect(path)) as conn:
        tables = {}
        for table in _tables(conn):
            indexes = set()
            for _, name, unique, origin, partial in conn.execute(
                f"PRAGMA index_list({table})"
            ):
                columns = tuple(
                    r[2] for r in conn.execute(f"PRAGMA index_info({name})")
                )
                sql = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
                ).fetchone()[0]
                indexes.add(
                    (unique, origin, partial, columns, " ".join((sql or "").split()))
                )
            table_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0]
            tables[table] = {
                "checks": _checks(table_sql),
                "columns": sorted(
                    tuple(row[1:])
                    for row in conn.execute(f"PRAGMA table_xinfo({table})")
                ),
                "foreign_keys": sorted(
                    tuple(row[2:])
                    for row in conn.execute(f"PRAGMA foreign_key_list({table})")
                ),
                "indexes": sorted(indexes),
            }
        triggers = sorted(
            " ".join(sql.split())
            for (sql,) in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger'"
            )
        )
    return {"tables": tables, "triggers": triggers}


def _checks(table_sql: str) -> list[str]:
    """Every CHECK expression in a CREATE TABLE statement, whitespace-
    normalized. Columns move when ALTER TABLE appends them, so the statement
    text cannot be compared whole; its constraints can."""
    checks = []
    upper = table_sql.upper()
    start = upper.find("CHECK")
    while start != -1:
        open_at = table_sql.index("(", start)
        depth, end = 0, open_at
        for end in range(open_at, len(table_sql)):
            depth += {"(": 1, ")": -1}.get(table_sql[end], 0)
            if depth == 0:
                break
        checks.append(" ".join(table_sql[open_at : end + 1].split()))
        start = upper.find("CHECK", end)
    return sorted(checks)


def _rows(path: Path) -> dict[str, list[dict]]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in _tables(conn)
        }


def _projected(rows: list[dict], columns: set[str]) -> Counter:
    return Counter(
        json.dumps({c: row[c] for c in sorted(columns)}, default=repr) for row in rows
    )


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(embed, "embed", instance_scenario.embed)
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    yield
    runtime._ctx = None


@pytest.fixture(scope="module")
def fresh_schema(tmp_path_factory) -> dict[str, dict]:
    data_dir = tmp_path_factory.mktemp("fresh")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(embed, "embed", instance_scenario.embed)
        mp.setenv("MYCELIUM_AUTH", "off")
        _start(data_dir)
        runtime._ctx = None
    return {db.name: _schema(db) for db in sorted(data_dir.glob("*.db"))}


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_upgrades_to_the_current_build(fixture, tmp_path, fresh_schema):
    data_dir = tmp_path / "data"
    _load(fixture, data_dir)
    before = {db.name: _rows(db) for db in data_dir.glob("*.db")}

    _start(data_dir)

    with closing(sqlite3.connect(data_dir / "mycelium.db")) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == migrations.CURRENT_VERSION
    assert {db.name: _schema(db) for db in sorted(data_dir.glob("*.db"))} == (
        fresh_schema
    ), "upgraded schema differs from a fresh instance's: a migration is missing"

    for db in sorted(data_dir.glob("*.db")):
        with closing(sqlite3.connect(db)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    _assert_rows_kept(before, data_dir)
    _assert_serves(before["mycelium.db"]["statements"])


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_archive_restores_into_a_fresh_instance(fixture, tmp_path):
    source = tmp_path / "source"
    _load(fixture, source)
    before = {db.name: _rows(db) for db in source.glob("*.db")}
    restored = tmp_path / "restored"

    manifest = backup.import_substrate(fixture / "export.tar.gz", restored)
    _start(restored)

    archived = set(manifest["row_counts"])
    _assert_rows_kept(
        {
            db: {t: rows for t, rows in tables.items() if t in archived}
            for db, tables in before.items()
        },
        restored,
    )
    _assert_serves(before["mycelium.db"]["statements"])


def _assert_rows_kept(before: dict[str, dict[str, list[dict]]], data_dir: Path) -> None:
    for db_name, tables in before.items():
        after = _rows(data_dir / db_name) if tables else {}
        for table, rows in tables.items():
            if (db_name, table) in REWRITES:
                continue
            dropped_row = DROPPED_ROWS.get((db_name, table))
            if dropped_row is not None:
                rows = [row for row in rows if not dropped_row(row)]
            assert table in after, f"{db_name}:{table} was dropped"
            with closing(sqlite3.connect(data_dir / db_name)) as conn:
                kept = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            columns = set(rows[0]) if rows else set()
            dropped = {
                c for c in columns - kept if (db_name, table, c) not in DROPPED_COLUMNS
            }
            assert not dropped, (
                f"{db_name}:{table} lost columns {sorted(dropped)}; if a migration "
                "removes them on purpose, declare them in DROPPED_COLUMNS"
            )
            columns &= kept
            missing = _projected(rows, columns) - _projected(after[table], columns)
            assert not missing, (
                f"{db_name}:{table} lost rows; if a migration rewrites them on "
                f"purpose, declare it in REWRITES: {missing}"
            )


def _assert_serves(statements: list[dict]) -> None:
    unnamed = store.substrate_connection().execute(
        "SELECT id FROM entities WHERE preferred_name_id IS NULL"
    )
    assert unnamed.fetchall() == []
    ids = {row["text"]: row["id"] for row in statements}
    hydrated = server.get_statements(list(ids.values()))
    assert hydrated["missing"] == []
    assert {s["id"]: s["text"] for s in hydrated["statements"]} == {
        i: t for t, i in ids.items()
    }
    for text, statement_id in ids.items():
        hits = server.search_statements(text, limit=1, name_boost=0.0)
        assert [hit["id"] for hit in hits] == [statement_id]


def test_fixtures_cover_every_version_up_to_the_current_one():
    versions = {_captured(f)[0] for f in FIXTURES}
    assert versions == set(range(min(versions), migrations.CURRENT_VERSION + 1)), (
        "capture a fixture of the current build: "
        "uv run python scripts/capture_migration_fixture.py"
    )


def test_newest_fixture_has_the_current_schema(tmp_path, fresh_schema):
    data_dir = tmp_path / "data"
    _load(FIXTURES[-1], data_dir)
    assert {db.name: _schema(db) for db in sorted(data_dir.glob("*.db"))} == (
        fresh_schema
    ), (
        "the schema changed since the newest migration fixture; once the "
        "migration is written, capture the new shape with "
        "`uv run python scripts/capture_migration_fixture.py`"
    )


def test_upgrade_keeps_every_action_on_its_model_and_seeds_the_catalog(
    tmp_path, caplog
):
    """This build has no built-in models. An instance captured before the
    later actions existed ran them on the old defaults; the upgrade saves
    those explicitly, and the catalog offers every saved model."""
    from mycelium import model_settings

    fixture = next(f for f in FIXTURES if f.name == "v20-docgen-run-summary")
    data_dir = tmp_path / "data"
    _load(fixture, data_dir)

    with caplog.at_level("WARNING", logger="mycelium.model_settings"):
        _start(data_dir)

    assert {
        action: model_settings.get(action).model for action in model_settings.ACTIONS
    } == {
        "ask": "claude-haiku-4-5",
        "ingest": "claude-sonnet-4-6",
        "docgen": "claude-sonnet-4-6",
        "draft_review": "",
        "alias_discovery": "claude-sonnet-4-6",
        "audience_labelling": "claude-haiku-5-5",
        "documentation_planning": "claude-sonnet-4-6",
        "connect": "claude-sonnet-4-6",
    }
    assert all(
        model_settings.get(action).source == "saved"
        for action in model_settings.ACTIONS
    )
    assert model_settings.catalog() == {
        "claude": ("claude-sonnet-4-6", "claude-haiku-4-5", "claude-haiku-5-5"),
        "openai": (),
    }
    assert (
        "Audience labelling" in caplog.text and "Connecting statements" in caplog.text
    )


def test_runs_finished_before_the_upgrade_are_not_retried_or_published(tmp_path):
    """Turning on automatic recovery or delivery acts only on runs that
    finish afterwards."""
    fixture = next(f for f in FIXTURES if f.name == "v27-gap-outcomes")
    data_dir = tmp_path / "data"
    _load(fixture, data_dir)

    _start(data_dir)

    with closing(sqlite3.connect(data_dir / "mycelium-drafts.db")) as conn:
        assert conn.execute(
            "SELECT DISTINCT recovery, delivery, attempt FROM documentation_runs"
        ).fetchall() == [("none", "none", 0)]
