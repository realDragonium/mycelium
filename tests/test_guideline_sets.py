"""Guideline sets as prompt-text rows: profiles are instance data.

No profile ships with the package: a fresh instance boots with none, and a
profile exists once someone saves it through the editor or the tools.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from mycelium import auth_store, prompt_store, server, store
from mycelium.server import runtime

# The second variant set, verbatim as it was saved through the tools. Four
# rows, deliberately minimal: this is the proof that a variant is data, not
# a template suite of its own.
_INTERNAL_DOC = {
    "internal-doc/guidance": (
        "Internal notes for the team. Terse over warm: state the fact, skip "
        "the welcome.\n\nEvery product claim traces to a substrate statement. "
        "Mark anything the substrate does not support with `needs "
        "verification` rather than filling it in.\n\nOne document, one type.\n"
    ),
    "internal-doc/exposure": (
        "These notes are for staff. Internal hostnames may be stated when "
        "useful and supported. Service and repository names, infrastructure "
        "topology, ticket IDs, staff names, and unreleased work may be stated "
        "too. This inverts the external boundary: the question is not whether "
        "a reader is outside the company, but whether the material is secret "
        "whoever is reading.\n\nWithhold live credentials, tokens, and private "
        "keys; personal data about an identifiable person; and material a "
        "third party gave us in confidence. A secret is a secret whoever is "
        "reading.\n"
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


def _conn() -> sqlite3.Connection:
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    return conn


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    prompt_store.reset()
    runtime._ctx = None


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    _reset_server()
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda t: [0.0] * 768)
    from mycelium.http import create_app

    return TestClient(create_app())


def test_a_fresh_instance_has_no_writing_profile(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    with client:
        assert server.list_prompt_texts(type="guideline-set")["prompt_texts"] == []
        assert server.list_writing_profiles()["profiles"] == []


def test_variant_set_is_added_through_prompt_routes(tmp_path, monkeypatch):
    """A profile saved through HTTP is listable and readable through tools."""
    client = _app(tmp_path, monkeypatch)
    with client:
        for name, text in _INTERNAL_DOC.items():
            response = client.put(
                "/api/documentation/prompts",
                json={
                    "type": "guideline-set",
                    "name": name,
                    "text": text,
                    "revision": 0,
                },
            )
            assert response.status_code == 200
            saved = response.json()
            assert saved["version"] == 1

        listed = server.list_prompt_texts(type="guideline-set")["prompt_texts"]
        variant = [p["name"] for p in listed if p["name"].startswith("internal-doc/")]
        assert variant == sorted(_INTERNAL_DOC)

        for name, text in _INTERNAL_DOC.items():
            assert server.get_prompt_text("guideline-set", name)["text"] == text


def test_sets_share_the_type_and_separate_by_prefix(tmp_path, monkeypatch):
    """One listing is the index of every set; the `<set>/` prefix is what
    tells them apart in it."""
    client = _app(tmp_path, monkeypatch)
    with client:
        public = {
            name.replace("internal-doc/", "public-doc/"): text
            for name, text in _INTERNAL_DOC.items()
        }
        for name, text in {**_INTERNAL_DOC, **public}.items():
            prompt_store.save(
                prompt_store.connection(), type="guideline-set", name=name, text=text
            )

        names = [
            p["name"]
            for p in server.list_prompt_texts(type="guideline-set")["prompt_texts"]
        ]
        assert names == sorted([*_INTERNAL_DOC, *public])
        assert sorted({n.split("/")[0] for n in names}) == [
            "internal-doc",
            "public-doc",
        ]
