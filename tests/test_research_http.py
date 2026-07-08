import json
import types
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mycelium import auth, embed, research_runs, research_store, server


def fake_embed_factory():
    rng = np.random.default_rng(0)

    def fake_embed(text: str) -> list[float]:
        return rng.standard_normal(768).astype(np.float32).tolist()

    return fake_embed


def deterministic_embed(text: str) -> list[float]:
    """Same text -> same vector across processes (CRC seed, not hash())."""
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch, embedder):
    monkeypatch.setattr(embed, "embed", embedder)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    server._conn = None
    server._auth_conn = None
    server._drafts_conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    server._name_index = None
    server._name_index_path = None
    server._data_dir = None
    from mycelium.http import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_research_runner():
    yield
    research_runs.wait_all()
    research_runs.RUNNER = None
    research_runs._threads.clear()


def _draft_created_runner(topic, source=None):
    return types.SimpleNamespace(
        model_dump=lambda: {
            "outcome": "draft_created",
            "draft_id": "drf_x",
            "trace": {},
        }
    )


def test_start_research_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_SOURCES",
        json.dumps({"src-a": {"owner": "o", "repo": "r"}}),
    )
    research_runs.RUNNER = _draft_created_runner

    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/start-research", json={"topic": "t"})
        assert r.status_code == 200
        body = r.json()
        run_id = body["id"]
        assert run_id.startswith("rrn_")
        assert body["status"] in {"running", "draft_created"}

        research_runs.wait_all()

        r = client.get("/list-research-runs")
        assert r.status_code == 200
        runs = r.json()["runs"]
        run = next(row for row in runs if row["id"] == run_id)
        assert run["status"] == "draft_created"
        assert run["draft_id"] == "drf_x"

        r = client.post("/get-research-run", json={"run_id": run_id})
        assert r.status_code == 200
        assert r.json() == run


def test_start_research_source_rules(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_SOURCES",
        json.dumps(
            {
                "src-a": {"owner": "o", "repo": "r"},
                "src-b": {"owner": "o2", "repo": "r2"},
            }
        ),
    )
    research_runs.RUNNER = _draft_created_runner

    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/start-research", json={"topic": "t"})
        assert r.status_code == 400
        assert "src-a" in r.json()["detail"]
        assert "src-b" in r.json()["detail"]

        r = client.post(
            "/start-research",
            json={"topic": "t", "source": "missing"},
        )
        assert r.status_code == 400
        assert "unknown source 'missing'" in r.json()["detail"]

        r = client.post(
            "/start-research",
            json={"topic": "t", "source": "src-b"},
        )
        assert r.status_code == 200
        assert r.json()["source"] == "src-b"
        research_runs.wait_all()


def test_start_research_no_sources_400(tmp_path, monkeypatch):
    monkeypatch.delenv("MYCELIUM_SOURCES", raising=False)
    research_runs.RUNNER = _draft_created_runner

    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/start-research", json={"topic": "t"})
        assert r.status_code == 400
        assert "no research sources configured" in r.json()["detail"]


def test_start_research_capacity_400(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_SOURCES",
        json.dumps({"src-a": {"owner": "o", "repo": "r"}}),
    )
    monkeypatch.setenv("MYCELIUM_RESEARCH_MAX_ACTIVE", "0")
    research_runs.RUNNER = _draft_created_runner

    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/start-research", json={"topic": "t"})
        assert r.status_code == 400
        assert "max 0" in r.json()["detail"]


def test_get_research_run_unknown_400(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.post("/get-research-run", json={"run_id": "rrn_missing"})
        assert r.status_code == 400
        assert r.json()["detail"] == "research run not found: rrn_missing"


def test_list_research_sources_names_only(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_SOURCES",
        json.dumps(
            {
                "src-a": {
                    "owner": "o",
                    "repo": "r",
                    "ref": "main",
                    "token_env": "SECRET_TOKEN",
                }
            }
        ),
    )

    with _client(tmp_path, monkeypatch, deterministic_embed) as client:
        r = client.get("/list-research-sources")
        assert r.status_code == 200
        assert r.json() == {
            "sources": [
                {
                    "name": "src-a",
                    "owner": "o",
                    "repo": "r",
                    "ref": "main",
                }
            ]
        }
        source = r.json()["sources"][0]
        assert "token_env" not in source
        assert "token" not in source


def test_orphan_marking_on_init(tmp_path, monkeypatch):
    conn = research_store.connect(tmp_path / "mycelium-drafts.db")
    research_store.migrate(conn)
    run_id = research_store.create_run(
        conn,
        topic="orphan",
        source="src-a",
        created_by="u1",
    )
    research_store.mark_started(conn, run_id)
    conn.close()

    with _client(tmp_path, monkeypatch, fake_embed_factory()) as client:
        r = client.get("/list-research-runs")
        assert r.status_code == 200
        run = next(row for row in r.json()["runs"] if row["id"] == run_id)
        assert run["status"] == "failed"
        assert run["error"] == "orphaned by restart"


def test_role_gates(tmp_path, monkeypatch):
    assert server.start_research._mycelium_required_role == "drafter"
    assert auth.required_role_for("list_research_runs") == "reader"
    assert auth.required_role_for("get_research_run") == "reader"
    assert auth.required_role_for("list_research_sources") == "reader"
    monkeypatch.delenv("MYCELIUM_SOURCES", raising=False)

    token = auth.current_principal.set(
        auth.Principal(id="r", name="Reader", role="reader", type="human")
    )
    try:
        with pytest.raises(PermissionError):
            server.start_research("t")
    finally:
        auth.current_principal.reset(token)

    token = auth.current_principal.set(
        auth.Principal(id="d", name="Drafter", role="drafter", type="human")
    )
    server._drafts_conn = research_store.connect(":memory:")
    research_store.migrate(server._drafts_conn)
    server._data_dir = tmp_path
    try:
        with pytest.raises(ValueError, match="no research sources configured"):
            server.start_research("t")
    finally:
        auth.current_principal.reset(token)
        server._drafts_conn.close()
        server._drafts_conn = None
        server._data_dir = None


def test_research_tools_registered():
    names = {f.__name__ for f in server.TOOLS}
    assert {
        "start_research",
        "list_research_runs",
        "get_research_run",
        "list_research_sources",
    } <= names
