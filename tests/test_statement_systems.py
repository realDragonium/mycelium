"""A statement's system: the app or platform its behaviour or step belongs
to, written, read, filtered and kept consistent through the server tools."""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mycelium import audience_scope, embed, phrasing, server, store
from mycelium.ask.substrate import InProcessSubstrate
from mycelium.audiences import Audience
from mycelium.server import runtime

INTERNAL = Audience("internal-technical", "Internal technical", "internal", "All.", 1)
STEP = "Copy the signing secret from the Paylark Webhooks page"


def _vector(text: str) -> list[float]:
    seed = zlib.crc32(text.casefold().encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


@pytest.fixture
def paylark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(embed, "embed", _vector)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    store.reset_substrate()
    runtime._ctx = None
    server.init(tmp_path)
    entity_id: str = server.upsert_entity(
        name="Paylark", description="A payment platform."
    )["entity_id"]
    return entity_id


def _create(text: str, **system: str | None) -> str:
    statement_id: str = server.upsert_statement(
        kind="action", text=text, links=[], **system
    )["statement_id"]
    return statement_id


def _record(statement_id: str) -> dict[str, object]:
    [record] = server.get_statements([statement_id])["statements"]
    return record


def _system_id(statement_id: str) -> str | None:
    row = store.get_statement(store.substrate_connection(), statement_id)
    assert row is not None
    return row["system_entity_id"]


def test_a_step_in_another_platform_reads_back_with_its_system(paylark):
    step = _create(STEP, system="paylark")
    ours = _create("Open the workspace billing settings")

    assert _record(step)["system"] == {"entity_id": paylark, "name": "Paylark"}
    assert "system" not in _record(ours)


def test_an_update_keeps_the_system_unless_it_is_cleared(paylark, monkeypatch):
    step = _create(STEP, system=paylark)
    server.upsert_statement(id=step, kind="action", text=STEP + ".", links=[])
    assert _system_id(step) == paylark

    mentions = store.get_mentions(store.substrate_connection(), step)
    assert mentions
    monkeypatch.setattr(embed, "embed", lambda text: pytest.fail("re-embedded"))
    server.patch_statement(id=step, system=None)

    assert _system_id(step) is None
    assert _record(step)["text"] == STEP + "."
    assert store.get_mentions(store.substrate_connection(), step) == mentions


def test_an_unknown_system_fails_before_anything_is_written(paylark):
    with pytest.raises(ValueError, match="Paylrk"):
        _create(STEP, system="Paylrk")
    with pytest.raises(ValueError, match="Paylrk"):
        server.upsert_statements([{"kind": "action", "text": STEP}], system="Paylrk")

    assert store.count_statements(store.substrate_connection()) == 0


def test_a_batch_system_applies_to_items_that_do_not_override_it(paylark):
    result = server.upsert_statements(
        [
            {"kind": "action", "text": "Open the Paylark dashboard"},
            {"kind": "action", "text": STEP},
            {"kind": "action", "text": "Paste the secret", "system": None},
        ],
        system="Paylark",
    )

    ids = [r["statement_id"] for r in result["results"]]
    assert [_system_id(i) for i in ids] == [paylark, paylark, None]


def test_reads_filter_by_system(paylark):
    step = _create(STEP, system=paylark)
    ours = _create("Copy the invoice number from the invoice page")

    listed = server.list_statements(system="Paylark")
    assert (listed["total"], [r["id"] for r in listed["statements"]]) == (1, [step])
    assert listed["statements"][0]["system"]["name"] == "Paylark"
    assert [h["id"] for h in server.search_statements("copy", system="main")] == [ours]
    grepped = server.grep_statements("Copy", system="main")
    assert [r["id"] for r in grepped["statements"]] == [ours]
    assert "system" not in grepped["statements"][0]


def test_an_unresolved_system_filter_matches_nothing(paylark):
    _create(STEP, system=paylark)

    assert server.grep_statements("Copy", system="Paylrk") == {
        "total": 0,
        "statements": [],
        "missing": ["Paylrk"],
    }
    assert server.list_statements(system="Paylrk")["missing"] == ["Paylrk"]
    assert server.search_statements("Copy", system="Paylrk") == []


def test_statements_of_different_systems_do_not_merge(paylark):
    ours = _create("A webhook delivery is retried")
    theirs = _create("A webhook delivery is retried", system=paylark)

    with pytest.raises(ValueError, match=r"no system.*'Paylark'"):
        server.merge_statements(from_id=ours, into_id=theirs)

    assert server.get_statements([ours, theirs])["missing"] == []


def test_merging_entities_moves_their_system_references(paylark):
    dashboard = server.upsert_entity(name="Paylark Dashboard", description="")[
        "entity_id"
    ]
    steps = [_create(f"Step {n} in the dashboard", system=dashboard) for n in range(3)]

    server.merge_entities(from_entity_id=dashboard, into_entity_id=paylark)

    assert [_system_id(s) for s in steps] == [paylark] * 3


def test_an_entity_used_as_a_system_cannot_be_deleted(paylark):
    for n in range(5):
        _create(f"Step {n} in Paylark", system=paylark)

    with pytest.raises(ValueError, match="system of 5 statements"):
        server.delete_entity(paylark)

    assert store.get_entity_by_id(store.substrate_connection(), paylark) is not None


def test_scoped_reads_leave_the_system_out(paylark):
    step = _create(STEP, system=paylark)
    conn = store.substrate_connection()

    with audience_scope.applied(conn, audience_scope.capture(conn, INTERNAL)):
        record = _record(step)
        with pytest.raises(ValueError, match="audience-scoped"):
            server.list_statements(system="main")

    assert "system" not in record
    scoped = audience_scope.scoped(InProcessSubstrate(), INTERNAL)
    [search] = [s for s in scoped.tool_specs() if s.name == "search_statements"]
    assert "system" not in search.input_schema["properties"]
    assert search.description.endswith(audience_scope.SCOPED_SYSTEM_NOTE)


def test_the_http_mirror_keeps_an_omitted_system_and_clears_a_null_one(
    paylark, tmp_path, monkeypatch
):
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    step = _create(STEP, system=paylark)
    runtime._ctx = None
    from mycelium.http import create_app

    with TestClient(create_app()) as client:
        kept = client.post("/patch-statement", json={"id": step, "kind": "check"})
        assert kept.status_code == 200, kept.text
        assert _system_id(step) == paylark
        cleared = client.post("/patch-statement", json={"id": step, "system": None})
        assert cleared.status_code == 200, cleared.text
        assert _system_id(step) is None


def _updated_at(statement_id: str) -> str:
    row = store.get_statement(store.substrate_connection(), statement_id)
    assert row is not None
    return str(row["updated_at"])


def test_a_system_change_is_not_a_content_change(paylark):
    dashboard = server.upsert_entity(name="Paylark Dashboard", description="")[
        "entity_id"
    ]
    step = _create(STEP, system=dashboard)
    before = "2026-01-01T00:00:00.000Z"
    store.substrate_connection().execute(
        "UPDATE statements SET updated_at = ? WHERE id = ?", (before, step)
    )

    server.merge_entities(from_entity_id=dashboard, into_entity_id=paylark)
    server.patch_statement(id=step, system=None)
    server.patch_statement(id=step, system=None)

    assert _updated_at(step) == before
    updates = server.get_history(op="update", target_kind="statement", q=step)
    assert updates["total"] == 2


def test_duplicates_pair_only_statements_of_one_system(paylark):
    ours = _create("A webhook delivery is retried")
    theirs = _create("A webhook delivery is retried", system=paylark)
    twin = _create("A webhook delivery is retried", system=paylark)

    pairs = {frozenset((p["a_id"], p["b_id"])) for p in server.find_duplicates()}

    assert pairs == {frozenset((theirs, twin))}
    assert ours not in {i for pair in pairs for i in pair}


def test_a_system_duplicate_claim_looks_past_other_systems_pairs(paylark):
    from mycelium.server.curation import duplicate_candidates

    for n in range(3):
        _create(f"An invoice export {n} is requested")
        _create(f"An invoice export {n} is requested")
    theirs = sorted(_create("A payout is sent", system=paylark) for _ in range(2))

    pairs, context = duplicate_candidates(limit=1, system=paylark)

    assert [p.id for p in pairs] == ["~".join(theirs)]
    side = context[pairs[0].id]["a"]
    assert isinstance(side, dict)
    assert side["system"] == {"entity_id": paylark, "name": "Paylark"}
