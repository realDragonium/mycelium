"""Prompt store semantics, retained read/retirement tools and startup seeding."""

import contextlib
import pathlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, prompt_store, server, store
from mycelium.server import runtime


def _conn() -> sqlite3.Connection:
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    return conn


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    prompt_store.reset()
    runtime._ctx = None


def _app(tmp_path, monkeypatch, *, auth_mode: str = "off"):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", auth_mode)
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-session-secret")
    _reset_server()
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import create_app

    return TestClient(create_app())


@contextlib.contextmanager
def _as(role: str):
    """Run the enclosed tool calls as a principal of `role`."""
    token = auth.current_principal.set(
        auth.Principal(id=role[0], name=role, role=role, type="human"),
    )
    try:
        yield
    finally:
        auth.current_principal.reset(token)


# --- store ------------------------------------------------------------------


def test_save_round_trip():
    conn = _conn()
    row = prompt_store.save(
        conn, type="doctrine", name="ingest", text="Be precise.", created_by="u1"
    )
    assert row["version"] == 1
    assert row["created_by"] == "u1"
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "Be precise."


def test_latest_wins_after_multiple_saves():
    """Each save appends; reads serve the newest version, and the earlier
    rows are still there untouched."""
    conn = _conn()
    for text in ("v1", "v2", "v3"):
        prompt_store.save(conn, type="doctrine", name="ingest", text=text)

    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "v3"
    assert prompt_store.latest(conn, "doctrine", "ingest")["version"] == 3
    assert [r["text"] for r in prompt_store.history(conn, "doctrine", "ingest")] == [
        "v3",
        "v2",
        "v1",
    ]


def test_history_is_ordered_newest_first():
    conn = _conn()
    for text in ("a", "b", "c"):
        prompt_store.save(conn, type="doctrine", name="ingest", text=text)
    versions = [r["version"] for r in prompt_store.history(conn, "doctrine", "ingest")]
    assert versions == [3, 2, 1]


def test_names_are_independent():
    """Versions count per (type, name) — two names never share a sequence,
    and a same-named text under another type is a different row."""
    conn = _conn()
    prompt_store.save(conn, type="doctrine", name="ingest", text="i1")
    prompt_store.save(conn, type="doctrine", name="ingest", text="i2")
    prompt_store.save(conn, type="doctrine", name="docgen", text="d1")
    prompt_store.save(conn, type="guidelines", name="ingest", text="g1")

    assert prompt_store.latest(conn, "doctrine", "docgen")["version"] == 1
    assert prompt_store.latest_text(conn, "guidelines", "ingest") == "g1"
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "i2"


def test_delete_hides_the_name_and_keeps_history():
    """The tombstone stops the name being served and listed; every earlier
    version stays readable, and the name can be saved again afterwards."""
    conn = _conn()
    prompt_store.save(conn, type="doctrine", name="ingest", text="v1")
    prompt_store.save(conn, type="doctrine", name="ingest", text="v2")

    assert prompt_store.delete(conn, type="doctrine", name="ingest") is True
    assert prompt_store.latest(conn, "doctrine", "ingest") is None
    assert prompt_store.list_current(conn) == []

    hist = prompt_store.history(conn, "doctrine", "ingest")
    assert [r["version"] for r in hist] == [3, 2, 1]
    assert bool(hist[0]["deleted"]) is True
    assert [r["text"] for r in hist[1:]] == ["v2", "v1"]

    revived = prompt_store.save(conn, type="doctrine", name="ingest", text="v3")
    assert revived["version"] == 4
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "v3"


def test_delete_unknown_name_is_false():
    conn = _conn()
    assert prompt_store.delete(conn, type="doctrine", name="nope") is False


def test_list_current_filters_by_type():
    conn = _conn()
    prompt_store.save(conn, type="doctrine", name="ingest", text="i")
    prompt_store.save(conn, type="doctrine", name="docgen", text="d")
    prompt_store.save(conn, type="guidelines", name="tutorial", text="t")
    prompt_store.save(conn, type="doctrine", name="ingest", text="i2")

    everything = [(r["type"], r["name"]) for r in prompt_store.list_current(conn)]
    assert everything == [
        ("doctrine", "docgen"),
        ("doctrine", "ingest"),
        ("guidelines", "tutorial"),
    ]

    doctrines = prompt_store.list_current(conn, "doctrine")
    assert [r["name"] for r in doctrines] == ["docgen", "ingest"]
    assert [r["version"] for r in doctrines] == [1, 2]
    assert prompt_store.list_current(conn, "unknown-type") == []


def test_save_if_absent_never_overwrites():
    """The seeding path: it fills an empty name, leaves an edited one alone,
    and seeds again once the name has been retired."""
    conn = _conn()
    seeded = prompt_store.save_if_absent(
        conn, type="doctrine", name="ingest", text="packaged"
    )
    assert seeded["version"] == 1

    prompt_store.save(conn, type="doctrine", name="ingest", text="operator edit")
    assert (
        prompt_store.save_if_absent(
            conn, type="doctrine", name="ingest", text="packaged"
        )
        is None
    )
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "operator edit"

    prompt_store.delete(conn, type="doctrine", name="ingest")
    reseeded = prompt_store.save_if_absent(
        conn, type="doctrine", name="ingest", text="packaged"
    )
    # Continues the sequence past the tombstone rather than restarting.
    assert reseeded["version"] == 4
    assert prompt_store.latest_text(conn, "doctrine", "ingest") == "packaged"


def test_blank_key_or_text_rejected():
    conn = _conn()
    with pytest.raises(ValueError):
        prompt_store.save(conn, type="  ", name="ingest", text="x")
    with pytest.raises(ValueError):
        prompt_store.save(conn, type="doctrine", name="", text="x")
    with pytest.raises(ValueError):
        prompt_store.save(conn, type="doctrine", name="ingest", text="   ")


# --- tools ------------------------------------------------------------------
#
# The tool tests write under `preamble`/`guidelines`, not `doctrine`: startup
# seeds the two real doctrines (see the seeding section below), so a generic
# tool test that used those names would be editing live instance config and
# counting its versions from 2.


def test_tool_round_trip(tmp_path, monkeypatch):
    """Prompt edits reach the read tools without a restart."""
    client = _app(tmp_path, monkeypatch)
    with client:
        saved = prompt_store.save(
            prompt_store.connection(), type="preamble", name="ask", text="Be precise."
        )
        assert saved["version"] == 1 and not saved["deleted"]

        assert server.get_prompt_text("preamble", "ask")["text"] == "Be precise."

        prompt_store.save(
            prompt_store.connection(),
            type="preamble",
            name="ask",
            text="Be very precise.",
        )
        assert server.get_prompt_text("preamble", "ask")["text"] == "Be very precise."

        listed = server.list_prompt_texts(type="preamble")["prompt_texts"]
        assert listed == [
            {
                "type": "preamble",
                "name": "ask",
                "version": 2,
                "chars": len("Be very precise."),
                "created_at": listed[0]["created_at"],
                "created_by": None,
            }
        ]

        versions = prompt_store.history(prompt_store.connection(), "preamble", "ask")
        assert [v["text"] for v in versions] == ["Be very precise.", "Be precise."]


def test_tool_list_by_type(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        prompt_store.save(
            prompt_store.connection(), type="preamble", name="ask", text="a"
        )
        prompt_store.save(
            prompt_store.connection(), type="guidelines", name="tutorial", text="t"
        )

        names = [
            p["name"] for p in server.list_prompt_texts(type="preamble")["prompt_texts"]
        ]
        assert names == ["ask"]


def test_tool_retire(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        prompt_store.save(
            prompt_store.connection(), type="preamble", name="ask", text="v1"
        )
        assert server.retire_prompt_text("preamble", "ask") == {"retired": True}
        assert server.retire_prompt_text("preamble", "ask") == {"retired": False}

        assert server.list_prompt_texts(type="preamble")["prompt_texts"] == []
        with pytest.raises(ValueError):
            server.get_prompt_text("preamble", "ask")

        # History survives the tombstone.
        versions = prompt_store.history(prompt_store.connection(), "preamble", "ask")
        assert [v["deleted"] for v in versions] == [True, False]


def test_unknown_name_raises(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        with pytest.raises(ValueError):
            server.get_prompt_text("doctrine", "nope")
        assert prompt_store.history(prompt_store.connection(), "doctrine", "nope") == []


def test_drafter_cannot_retire_prompt_texts(tmp_path, monkeypatch):
    """A drafter clears writer/admin gates only because their substrate
    writes get redirected onto a draft. Retirement is outside that
    machinery, so it rejects them and queues nothing; reads
    still work."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        prompt_store.save(
            prompt_store.connection(), type="preamble", name="ask", text="v1"
        )

        with _as("drafter"):
            with pytest.raises(auth.RoleRequired):
                server.retire_prompt_text("preamble", "ask")
            assert server.get_prompt_text("preamble", "ask")["text"] == "v1"
            assert server.list_my_drafts() == []


def test_rest_mirror(tmp_path, monkeypatch):
    """Dedicated prompt saves are visible through the read tool routes."""
    client = _app(tmp_path, monkeypatch)
    with client:
        r = client.put(
            "/api/documentation/prompts",
            json={
                "type": "guideline-set",
                "name": "internal/reference",
                "text": "v1",
                "revision": 0,
            },
        )
        assert r.status_code == 200 and r.json()["version"] == 1

        r = client.post(
            "/get-prompt-text",
            json={"type": "guideline-set", "name": "internal/reference"},
        )
        assert r.json()["text"] == "v1"

        r = client.post("/list-prompt-texts", json={"type": "guideline-set"})
        assert "internal/reference" in [p["name"] for p in r.json()["prompt_texts"]]


def test_rest_rejects_drafter_with_403(tmp_path, monkeypatch):
    """Prompt edits and retirement require real writer/admin roles."""
    client = _app(tmp_path, monkeypatch, auth_mode="on")
    with client:
        conn = runtime._auth_db()
        uid = auth.create_user(
            conn, name="D", role="drafter", type="human", email="d@x.com"
        )
        conn.commit()
        raw, _ = auth.issue_token(conn, user_id=uid, name="k", scope="drafter")
        conn.commit()
        h = {"Authorization": f"Bearer {raw}"}

        r = client.put(
            "/api/documentation/prompts",
            json={"type": "doctrine", "name": "ingest", "text": "v1", "revision": 1},
            headers=h,
        )
        assert r.status_code == 403
        assert "writer" in r.json()["detail"]

        r = client.post(
            "/retire-prompt-text",
            json={"type": "doctrine", "name": "ingest"},
            headers=h,
        )
        assert r.status_code == 403


# --- startup seeding --------------------------------------------------------
#
# Startup puts every packaged loop doctrine in the store so they are editable
# from the first run. The files stay the seed and the fallback; the store is
# what the loops read (tests/test_ingest.py, test_docgen.py).

#: Every doctrine startup seeds, in the order `list_prompt_texts` returns them.
DOCTRINES = ("docgen", "ingest")


def _doctrine_file(name: str) -> str:
    from mycelium.docgen.config import _DEFAULT_DOCTRINE_PATH as DOCGEN_PATH
    from mycelium.ingest.config import _DEFAULT_DOCTRINE_PATH as INGEST_PATH

    path = {"docgen": DOCGEN_PATH, "ingest": INGEST_PATH}[name]
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_startup_seeds_every_doctrine(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        seeded = server.list_prompt_texts(type="doctrine")["prompt_texts"]
        assert [p["name"] for p in seeded] == list(DOCTRINES)
        assert [p["version"] for p in seeded] == [1] * len(DOCTRINES)
        assert [p["created_by"] for p in seeded] == ["seed"] * len(DOCTRINES)

        for name in DOCTRINES:
            stored = server.get_prompt_text("doctrine", name)["text"]
            assert stored == _doctrine_file(name)


def test_seeding_leaves_an_edit_alone_and_adds_no_versions(tmp_path, monkeypatch):
    """Idempotency: restarting re-runs the seed, and a store that already has
    a doctrine keeps it — same version, same text, no duplicate row."""
    client = _app(tmp_path, monkeypatch)
    with client:
        prompt_store.save(
            prompt_store.connection(),
            type="doctrine",
            name="ingest",
            text="operator edit",
        )

    _reset_server()
    client = _app(tmp_path, monkeypatch)  # restart against the same data dir
    with client:
        assert server.get_prompt_text("doctrine", "ingest")["text"] == "operator edit"
        assert (
            len(prompt_store.history(prompt_store.connection(), "doctrine", "ingest"))
            == 2
        )
        docgen = prompt_store.history(prompt_store.connection(), "doctrine", "docgen")
        assert len(docgen) == 1  # untouched by the second startup


def test_an_unreadable_doctrine_file_does_not_block_startup(tmp_path, monkeypatch):
    """Seeding is best-effort: a missing file leaves that doctrine unseeded —
    the loop falls back to the same file and records a note — and the other
    doctrines, and the rest of startup, are unaffected."""
    monkeypatch.setenv(
        "MYCELIUM_INGEST_DOCTRINE_PATH", str(tmp_path / "nope" / "doctrine.md")
    )
    client = _app(tmp_path, monkeypatch)
    with client:
        names = [
            p["name"] for p in server.list_prompt_texts(type="doctrine")["prompt_texts"]
        ]
        assert names == [n for n in DOCTRINES if n != "ingest"]


def test_retiring_a_seeded_doctrine_is_refused(tmp_path, monkeypatch):
    """Startup re-seeds these names, so retiring one would undo itself. The
    tool says so at the moment of the attempt and appends no tombstone; the
    REST mirror turns the same refusal into a 400 carrying the reason."""
    client = _app(tmp_path, monkeypatch)
    with client:
        for name in DOCTRINES:
            with pytest.raises(ValueError, match="seeded at startup"):
                server.retire_prompt_text("doctrine", name)
            assert server.get_prompt_text("doctrine", name)["text"] == _doctrine_file(
                name
            )
            versions = prompt_store.history(prompt_store.connection(), "doctrine", name)
            assert [v["deleted"] for v in versions] == [False]

        r = client.post(
            "/retire-prompt-text", json={"type": "doctrine", "name": "ingest"}
        )
        assert r.status_code == 400
        assert "seeded at startup" in r.json()["detail"]
        assert "Settings → Prompts" in r.json()["detail"]


def test_an_unseeded_doctrine_is_still_retirable(tmp_path, monkeypatch):
    """The refusal is per name, not per type: a doctrine startup does not
    seed is an ordinary prompt text."""
    client = _app(tmp_path, monkeypatch)
    with client:
        prompt_store.save(
            prompt_store.connection(), type="doctrine", name="curation", text="v1"
        )
        assert server.retire_prompt_text("doctrine", "curation") == {"retired": True}
        assert [
            p["name"] for p in server.list_prompt_texts(type="doctrine")["prompt_texts"]
        ] == list(DOCTRINES)


def test_a_seeded_doctrine_survives_a_restart_after_a_refused_retire(
    tmp_path, monkeypatch
):
    """The restart case: an operator retires a seeded doctrine, is refused,
    and the restart finds exactly what was there before — same version, same
    text, no seed row added on top."""
    client = _app(tmp_path, monkeypatch)
    with client:
        prompt_store.save(
            prompt_store.connection(),
            type="doctrine",
            name="ingest",
            text="operator edit",
        )
        with pytest.raises(ValueError, match="seeded at startup"):
            server.retire_prompt_text("doctrine", "ingest")

    _reset_server()
    client = _app(tmp_path, monkeypatch)  # restart against the same data dir
    with client:
        assert server.get_prompt_text("doctrine", "ingest")["text"] == "operator edit"
        versions = prompt_store.history(prompt_store.connection(), "doctrine", "ingest")
        assert [v["version"] for v in versions] == [2, 1]


def test_a_store_level_tombstone_is_refilled_by_the_next_start(tmp_path, monkeypatch):
    """Why the tool refuses. The store is ignorant of what is special, so a
    tombstone written straight into it reads as "no live text" and the next
    startup seeds the packaged default again at a new version."""
    client = _app(tmp_path, monkeypatch)
    with client:
        assert (
            prompt_store.delete(runtime._prompts_db(), type="doctrine", name="ingest")
            is True
        )
        with pytest.raises(ValueError):
            server.get_prompt_text("doctrine", "ingest")

    _reset_server()
    client = _app(tmp_path, monkeypatch)  # restart against the same data dir
    with client:
        revived = server.get_prompt_text("doctrine", "ingest")
        assert revived["text"] == _doctrine_file("ingest")
        assert revived["version"] == 3  # seed, tombstone, re-seed
        assert revived["created_by"] == "seed"


def test_a_restore_brings_back_the_edits_instead_of_re_seeding(tmp_path, monkeypatch):
    """The whole instance round trip. An operator edits a doctrine and
    retires an unseeded text; the archive is restored into a fresh data dir
    and started. The doctrine reads as the operator left it — startup finds
    a live row and adds no seed version on top — and the retired name is
    still retired rather than resurrected by the restore."""
    from mycelium import backup

    src, dst = tmp_path / "src", tmp_path / "dst"
    client = _app(src, monkeypatch)
    with client:
        prompt_store.save(
            prompt_store.connection(),
            type="doctrine",
            name="ingest",
            text="operator edit",
        )
        prompt_store.save(
            prompt_store.connection(), type="preamble", name="ask", text="v1"
        )
        assert server.retire_prompt_text("preamble", "ask") == {"retired": True}

    archive = tmp_path / "snap.tar.gz"
    backup.export_substrate(src, archive)
    backup.import_substrate(archive, dst)

    _reset_server()
    client = _app(dst, monkeypatch)  # a fresh instance on the restored dir
    with client:
        assert server.get_prompt_text("doctrine", "ingest")["text"] == "operator edit"
        versions = prompt_store.history(prompt_store.connection(), "doctrine", "ingest")
        assert [v["version"] for v in versions] == [2, 1]
        assert [v["created_by"] for v in versions] == [None, "seed"]

        # The packaged docgen doctrine came back too, unduplicated.
        docgen = prompt_store.history(prompt_store.connection(), "doctrine", "docgen")
        assert [v["version"] for v in docgen] == [1]
        assert docgen[0]["text"] == _doctrine_file("docgen")

        with pytest.raises(ValueError):
            server.get_prompt_text("preamble", "ask")
        retired = prompt_store.history(prompt_store.connection(), "preamble", "ask")
        assert [v["deleted"] for v in retired] == [True, False]


def test_a_malformed_saved_loop_setting_does_not_block_startup(tmp_path, monkeypatch):
    """Resolving where a doctrine comes from parses that loop's whole config,
    so an unrelated bad tunable must degrade to an unseeded doctrine rather
    than abort the server."""
    conn = prompt_store.connect(tmp_path / "mycelium-prompts.db")
    prompt_store.migrate(conn)
    conn.execute(
        "INSERT INTO product_settings VALUES ('ingest', 1, ?)",
        ('{"kind":"ingest","op_cap":"not-a-number"}',),
    )
    conn.close()
    client = _app(tmp_path, monkeypatch)
    with client:
        names = [
            p["name"] for p in server.list_prompt_texts(type="doctrine")["prompt_texts"]
        ]
        assert names == [n for n in DOCTRINES if n != "ingest"]
