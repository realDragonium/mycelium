"""The database list a deployment restores, and the startup check that a
restore brought all of it back.

The first test keeps `databases.FILES` complete: it compares the list with the
files a populated instance actually wrote, so a database added anywhere fails
here until it is listed or declared in `_NOT_RESTORED` with a reason.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest

import instance_scenario
from mycelium import databases, embed, phrasing, server, store
from mycelium.http import app

_NOT_RESTORED = {
    "mycelium-ops.db": "bounded telemetry pruned on every start; losing it loses "
    "nothing",
}

_FIXTURES = sorted((Path(__file__).parent / "migration_fixtures").iterdir())
_PEERS = [name for name in databases.FILES if name != databases.SUBSTRATE]


@pytest.fixture
def populated(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", instance_scenario.embed)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    source = tmp_path / "source"
    instance_scenario.populate(source)
    store.set_actor(None)
    yield source
    server._ctx = None


def _restore(source: Path, target: Path, names: list[str]) -> None:
    """Copy databases the way a replica restore does: consistent snapshots of
    the named files into an empty directory, nothing else."""
    target.mkdir()
    for name in names:
        with (
            closing(sqlite3.connect(source / name)) as src,
            closing(sqlite3.connect(target / name)) as dst,
        ):
            src.backup(dst)


def _load(fixture: Path, data_dir: Path) -> None:
    data_dir.mkdir()
    for dump in fixture.glob("*.sql"):
        with closing(sqlite3.connect(data_dir / f"{dump.stem}.db")) as conn:
            conn.executescript(dump.read_text(encoding="utf-8"))


def _probe() -> list[str]:
    async def get() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://p") as c:
            return await c.get("/api/server-info")

    response = asyncio.run(get())
    assert response.status_code == 200
    return response.json()["partial_restore"]


def test_every_database_an_instance_writes_is_listed(populated):
    written = {path.name for path in populated.glob("*.db")}

    assert written - set(_NOT_RESTORED) == set(databases.FILES)


def test_a_complete_restore_starts_clean(populated, tmp_path, caplog):
    restored = tmp_path / "restored"
    _restore(populated, restored, list(databases.FILES))

    server._ctx = None
    with caplog.at_level(logging.ERROR, logger="mycelium.databases"):
        server.init(restored)

    assert server._context().partial_restore == ()
    assert _probe() == []
    assert not caplog.records


def test_a_restore_missing_the_prompts_database_starts_and_shouts(
    populated, tmp_path, caplog
):
    restored = tmp_path / "restored"
    _restore(
        populated, restored, [n for n in databases.FILES if n != "mycelium-prompts.db"]
    )

    server._ctx = None
    with caplog.at_level(logging.ERROR, logger="mycelium.databases"):
        server.init(restored)

    assert server._context().partial_restore == ("mycelium-prompts.db",)
    assert _probe() == ["mycelium-prompts.db"]
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "PARTIAL RESTORE" in record.getMessage()
    assert "mycelium-prompts.db" in record.getMessage()


def test_a_fresh_instance_is_not_a_partial_restore(tmp_path):
    assert databases.partial_restore(tmp_path) == ()


def test_a_substrate_without_knowledge_is_not_a_partial_restore(tmp_path):
    # A first start interrupted after creating the substrate, or an instance
    # nobody has written to yet: nothing is lost by recreating its peers.
    newest = _FIXTURES[-1]
    _load(newest, tmp_path / "data")
    with closing(sqlite3.connect(tmp_path / "data" / databases.SUBSTRATE)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("DELETE FROM statements; DELETE FROM entities;")
    for peer in _PEERS:
        (tmp_path / "data" / peer).unlink()

    assert databases.partial_restore(tmp_path / "data") == ()


def test_a_peer_holding_nothing_is_a_feature_never_used(tmp_path):
    _load(_FIXTURES[-1], tmp_path / "data")
    drafts = tmp_path / "data" / "mycelium-drafts.db"
    drafts.unlink()
    with closing(sqlite3.connect(drafts)) as conn:
        conn.execute("CREATE TABLE drafts (id TEXT)")

    assert databases.partial_restore(tmp_path / "data") == ()


@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda p: p.name)
def test_every_shipped_instance_upgrades_without_alarm(fixture, tmp_path):
    # v05 predates the prompts database; upgrading it is legitimate.
    _load(fixture, tmp_path / "data")

    assert databases.partial_restore(tmp_path / "data") == ()


@pytest.mark.parametrize("peer", _PEERS)
@pytest.mark.parametrize("how", ["deleted", "truncated"])
def test_any_missing_peer_beside_knowledge_is_a_partial_restore(peer, how, tmp_path):
    _load(_FIXTURES[-1], tmp_path / "data")
    target = tmp_path / "data" / peer
    if how == "deleted":
        target.unlink()
    else:
        target.write_bytes(b"")

    assert databases.partial_restore(tmp_path / "data") == (peer,)


def test_the_cli_prints_one_filename_per_line_for_an_entrypoint(monkeypatch, capsys):
    from mycelium import __main__

    monkeypatch.setattr("sys.argv", ["mycelium", "databases"])
    __main__.main()

    assert capsys.readouterr().out.splitlines() == list(databases.FILES)
