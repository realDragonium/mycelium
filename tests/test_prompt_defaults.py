"""Shipped prompt defaults reach untouched texts and never override an edit."""

from __future__ import annotations

import logging
from contextlib import closing
from pathlib import Path

import pytest

import instance_scenario
from mycelium import ai_prompts, embed, prompt_store, server
from mycelium.prompt_defaults import Plan, Version, digest, plan
from mycelium.server import runtime

NOW = "2026-10-22T12:00:00.000Z"


def seed(text: str, at: str = "2026-09-01T00:00:00.000Z") -> Version:
    return Version(text, False, at, "seed")


def edit(text: str, at: str) -> Version:
    return Version(text, False, at, "user-1")


@pytest.mark.parametrize(
    ("history", "seen", "expected"),
    [
        pytest.param(
            [seed("new")],
            {},
            Plan(False, "2026-09-01T00:00:00.000Z", None),
            id="current-seed-backfills-its-own-date",
        ),
        pytest.param(
            [seed("old")],
            {},
            Plan(True, NOW, None),
            id="untouched-seed-follows-release",
        ),
        pytest.param(
            [edit("mine", "2026-09-05T00:00:00.000Z"), seed("old")],
            {},
            Plan(False, NOW, NOW),
            id="edit-against-an-old-default-is-behind",
        ),
        pytest.param(
            [edit("mine", "2026-09-05T00:00:00.000Z"), seed("new")],
            {},
            Plan(False, "2026-09-01T00:00:00.000Z", None),
            id="edit-against-the-current-default-is-not-behind",
        ),
        pytest.param(
            [edit("mine", "2026-10-23T00:00:00.000Z")],
            {digest("new"): "2026-10-22T00:00:00.000Z"},
            Plan(False, None, None),
            id="saving-after-the-default-appeared-clears-it",
        ),
        pytest.param(
            [edit("mine", "2026-09-05T00:00:00.000Z")],
            {},
            Plan(False, "2026-09-05T00:00:00.000Z", None),
            id="override-without-seed-history-is-assumed-current",
        ),
        pytest.param(
            [edit("mine", "2026-09-05T00:00:00.000Z")],
            {digest("old"): "2026-09-01T00:00:00.000Z"},
            Plan(False, NOW, NOW),
            id="override-is-behind-a-default-that-changed-later",
        ),
        pytest.param(
            [edit("new", "2026-09-05T00:00:00.000Z"), seed("old")],
            {},
            Plan(False, NOW, None),
            id="an-edit-equal-to-the-default-is-current",
        ),
        pytest.param(
            [Version("", True, "2026-09-05T00:00:00.000Z", "user-1"), seed("old")],
            {},
            Plan(False, NOW, None),
            id="retired-text-serves-the-default",
        ),
    ],
)
def test_plan(history, seen, expected):
    assert plan(history, seen, "new", NOW) == expected


def _versions(data_dir: Path, name: str) -> list[tuple[str, str | None]]:
    with closing(prompt_store.connect(data_dir / "mycelium-prompts.db")) as conn:
        return [
            (row["text"], row["created_by"])
            for row in prompt_store.history(conn, "doctrine", name)
        ]


def test_upgrade_updates_untouched_doctrines_and_reports_edited_ones(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(embed, "embed", instance_scenario.embed)
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    with closing(prompt_store.connect(tmp_path / "mycelium-prompts.db")) as conn:
        prompt_store.migrate(conn)
        for name in ("ingest", "docgen"):
            prompt_store.save(
                conn, type="doctrine", name=name, text="Old.", created_by="seed"
            )
        prompt_store.save(
            conn, type="doctrine", name="docgen", text="Mine.", created_by="ada"
        )
        conn.execute("DROP TABLE shipped_prompt_texts")

    with caplog.at_level(logging.WARNING, logger="mycelium.server"):
        runtime._ctx = None
        server.init(tmp_path)

    shipped = ai_prompts.shipped_text("ingest")
    assert _versions(tmp_path, "ingest") == [(shipped, "seed"), ("Old.", "seed")]
    assert ai_prompts.resolve("ingest").text == shipped
    assert _versions(tmp_path, "docgen") == [("Mine.", "ada"), ("Old.", "seed")]
    assert "saved docgen instructions predate" in caplog.text
    assert ai_prompts.editor("docgen").newer_default_since is not None
    assert ai_prompts.editor("ingest").newer_default_since is None
    listed = {item.name: item for item in ai_prompts.summaries()}
    assert listed["research"].edited and listed["research"].newer_default_since
    assert listed["ingest"].edited and listed["ingest"].newer_default_since is None

    runtime._ctx = None
    server.init(tmp_path)
    assert len(_versions(tmp_path, "ingest")) == 2
    runtime._ctx = None


def test_editor_works_when_the_configured_doctrine_file_is_missing(
    tmp_path, monkeypatch
):
    conn = prompt_store.connect(":memory:")
    prompt_store.migrate(conn)
    prompt_store.use_connection(conn)
    prompt_store.save(conn, type="doctrine", name="ingest", text="Mine.")
    monkeypatch.setenv("MYCELIUM_INGEST_DOCTRINE_PATH", str(tmp_path / "gone.md"))

    view = ai_prompts.editor("ingest")

    assert view.current.text == "Mine."
    assert view.newer_default_since is None
