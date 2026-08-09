"""Guideline sets as prompt-text rows — the seeded set and the variant story.

Two layers, matching how the convention in `docs/GUIDELINE_SETS.md` is meant
to hold. The seed tests drive `scripts/seed_guideline_sets.py` against an
in-memory prompts DB and pin its naming, its idempotency against the
append-only store, and what the stored guidance may assume its reader can
reach. The variant test adds a second set through the management
tools and nothing else — no seeder, no source files, no code — which is the
claim the convention makes about new documentation variants.
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from mycelium import auth_store, prompt_store, server, store

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_guideline_sets.py"

_KB_ROWS = [
    "kb-authoring/explanation",
    "kb-authoring/guidance",
    "kb-authoring/how-to",
    "kb-authoring/reference",
    "kb-authoring/troubleshooting",
    "kb-authoring/tutorial",
]

# The second variant set, verbatim as it was saved through the tools. Three
# rows, deliberately minimal: this is the proof that a variant is data, not
# a template suite of its own.
_INTERNAL_DOC = {
    "internal-doc/guidance": (
        "Internal notes for the team. Terse over warm: state the fact, skip "
        "the welcome.\n\nEvery product claim traces to a substrate statement. "
        "Mark anything the substrate does not support with `needs "
        "verification` rather than filling it in.\n\nOne document, one type.\n"
    ),
    "internal-doc/how-to": (
        "---\ntitle:\ntype: how-to\naudience: internal\n---\n\n"
        "# {Task}\n\n**When you need this:** {trigger}\n\n"
        "## Steps\n\n1. {One action per step.}\n\n"
        "## If it goes wrong\n\n- {Symptom} - {what to do}\n"
    ),
    "internal-doc/reference": (
        "---\ntitle:\ntype: reference\naudience: internal\n---\n\n"
        "# {Thing}\n\n| Field | Value | Notes |\n|---|---|---|\n\n"
        "## Notes\n\n{Only what the table cannot carry.}\n"
    ),
}


def _seed_script():
    """Load the seed script by file path (`scripts/` isn't a package)."""
    spec = importlib.util.spec_from_file_location("seed_guideline_sets", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _conn() -> sqlite3.Connection:
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    return conn


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    store.reset_substrate()
    auth_store.reset()
    prompt_store.reset()
    server._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import app

    return TestClient(app)


# --- the seeded kb-authoring set --------------------------------------------


def test_seed_writes_the_named_rows():
    """Six rows under one type, each named `<set>/<slot>` and carrying its
    source file verbatim."""
    seed = _seed_script()
    conn = _conn()
    rows = seed.read_rows(seed.REPO_ROOT)

    assert seed.seed(conn, rows) != []

    listed = prompt_store.list_current(conn, "guideline-set")
    assert [r["name"] for r in listed] == _KB_ROWS
    assert {r["version"] for r in listed} == {1}
    assert {r["created_by"] for r in listed} == {"system:seed-guideline-sets"}


def test_seeded_text_is_the_source_file():
    """The seed is a copier: every row is its source file byte for byte, so
    what a run reads is what a reviewer read in the diff. The guidance is
    written for the store and has its own source, which is why the copy can
    stay verbatim — the adaptation lives in a file, not in a transform."""
    seed = _seed_script()
    conn = _conn()
    seed.seed(conn, seed.read_rows(seed.REPO_ROOT))

    for slot, rel in seed.SOURCES.items():
        stored = prompt_store.latest_text(conn, "guideline-set", f"kb-authoring/{slot}")
        assert stored == (seed.REPO_ROOT / rel).read_text(encoding="utf-8")

    guidance = prompt_store.latest_text(conn, "guideline-set", "kb-authoring/guidance")
    assert "Knowledge-Base Authoring from Substrate" in guidance
    assert "> ⚠️ needs verification:" in guidance


def test_stored_guidance_addresses_a_run_that_has_only_the_store():
    """What the guidance may assume its reader can reach. It names each
    template as the sibling row it is — every name resolves to a row that
    was seeded, and every seeded template is named — reaches for no file,
    and carries none of the frontmatter that dispatches a local skill."""
    seed = _seed_script()
    conn = _conn()
    seed.seed(conn, seed.read_rows(seed.REPO_ROOT))

    guidance = prompt_store.latest_text(conn, "guideline-set", "kb-authoring/guidance")
    seeded = {r["name"] for r in prompt_store.list_current(conn, "guideline-set")}

    named = set(re.findall(r"kb-authoring/[a-z-]+", guidance))
    assert named == seeded - {"kb-authoring/guidance"}

    assert re.findall(r"[\w./-]+\.md", guidance) == []
    assert ".claude" not in guidance

    assert not guidance.startswith("---")
    assert "description:" not in guidance
    assert "Use this skill" not in guidance


def test_reseeding_unchanged_sources_appends_nothing():
    """The append-only store makes this the whole idempotency story: the
    seed compares against the latest version and writes no second one."""
    seed = _seed_script()
    conn = _conn()
    rows = seed.read_rows(seed.REPO_ROOT)
    seed.seed(conn, rows)

    assert seed.outdated(conn, rows) == []
    assert seed.seed(conn, rows) == []

    for name in _KB_ROWS:
        assert len(prompt_store.history(conn, "guideline-set", name)) == 1


def test_changed_source_appends_only_that_row():
    """Idempotency is a text comparison, not a seeded-once flag — an edited
    source still lands, and only it does."""
    seed = _seed_script()
    conn = _conn()
    rows = seed.read_rows(seed.REPO_ROOT)
    seed.seed(conn, rows)

    rows["kb-authoring/how-to"] += "\nAlways link the matching explanation.\n"
    assert seed.seed(conn, rows) == ["kb-authoring/how-to"]

    assert (
        prompt_store.latest(conn, "guideline-set", "kb-authoring/how-to")["version"]
        == 2
    )
    assert (
        prompt_store.latest(conn, "guideline-set", "kb-authoring/tutorial")["version"]
        == 1
    )


def test_dry_run_leaves_no_database_behind(tmp_path):
    """`--dry-run` reports; it must not be the thing that creates an
    instance's prompts DB."""
    seed = _seed_script()
    db_path = tmp_path / "mycelium-prompts.db"
    rows = seed.read_rows(seed.REPO_ROOT)

    assert seed.pending(db_path, rows) == list(rows)
    assert not db_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_dry_run_does_not_write_to_an_existing_database(tmp_path):
    """Nor may it write to one that is already there. The file is byte-for-
    byte what it was — no appended version, and no rewritten journal mode
    either, which an ordinary `prompt_store.connect` would have done."""
    seed = _seed_script()
    db_path = tmp_path / "mycelium-prompts.db"
    rows = seed.read_rows(seed.REPO_ROOT)

    conn = prompt_store.connect(db_path)
    prompt_store.migrate(conn)
    seed.seed(conn, rows)
    conn.close()
    before = db_path.read_bytes()

    assert seed.pending(db_path, rows) == []
    assert db_path.read_bytes() == before

    reopened = prompt_store.connect(db_path)
    assert {r["version"] for r in prompt_store.list_current(reopened)} == {1}
    reopened.close()


# --- the second variant set, added through the tools alone ------------------


def test_variant_set_is_added_through_tools_only(tmp_path, monkeypatch):
    """`internal-doc` reaches the store by `save_prompt_text` and nothing
    else, and comes back out listable by its type and readable by name."""
    client = _app(tmp_path, monkeypatch)
    with client:
        for name, text in _INTERNAL_DOC.items():
            saved = server.save_prompt_text("guideline-set", name, text)
            assert saved["version"] == 1

        listed = server.list_prompt_texts(type="guideline-set")["prompt_texts"]
        assert [p["name"] for p in listed] == sorted(_INTERNAL_DOC)

        for name, text in _INTERNAL_DOC.items():
            assert server.get_prompt_text("guideline-set", name)["text"] == text


def test_sets_share_the_type_and_separate_by_prefix(tmp_path, monkeypatch):
    """What the convention buys: one listing is the index of every set, and
    the `<set>/` prefix is what tells them apart in it."""
    seed = _seed_script()
    client = _app(tmp_path, monkeypatch)
    with client:
        seed.seed(server._prompts_db(), seed.read_rows(seed.REPO_ROOT))
        for name, text in _INTERNAL_DOC.items():
            server.save_prompt_text("guideline-set", name, text)

        names = [
            p["name"]
            for p in server.list_prompt_texts(type="guideline-set")["prompt_texts"]
        ]
        assert names == sorted(_KB_ROWS + list(_INTERNAL_DOC))

        sets = sorted({n.split("/")[0] for n in names})
        assert sets == ["internal-doc", "kb-authoring"]
