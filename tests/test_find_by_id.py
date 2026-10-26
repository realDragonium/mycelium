"""A query that is a statement id finds that statement, in every search."""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pytest

from mycelium import audience_scope, embed, phrasing, server, store
from mycelium.audiences import Audience
from mycelium.server import runtime

EXTERNAL = Audience(
    "external-technical", "External technical", "external", "Integrators.", 1
)


def _vector(text: str) -> list[float]:
    seed = zlib.crc32(text.casefold().encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


@pytest.fixture
def statements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(embed, "embed", _vector)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    store.reset_substrate()
    runtime._ctx = None
    server.init(tmp_path)
    return {
        text: server.upsert_statement(kind=kind, text=text, links=[])["statement_id"]
        for kind, text in (
            ("state", "Workspace exports are available as CSV"),
            ("event", "An invoice is sent when the billing period closes"),
            ("capability", "An admin can enable SSO for a workspace"),
        )
    }


def _searches(query: str, **filters: str) -> dict[str, list[dict[str, object]]]:
    return {
        "semantic": server.search_statements(query, limit=2, **filters),
        "survey": server.search_statements(query, limit=2, decompose=True, **filters),
        "grep": server.grep_statements(query, limit=2, **filters)["statements"],
    }


def test_an_id_query_returns_that_statement_first_in_every_mode(statements):
    target = statements["An invoice is sent when the billing period closes"]

    for mode, hits in _searches(f"  {target}\n").items():
        assert hits[0]["id"] == target, mode
        assert hits[0]["matched_via"] == "id", mode
        assert "score" not in hits[0], mode
        assert [hit["id"] for hit in hits].count(target) == 1, mode
    assert len(server.search_statements(target, limit=2)) == 2

    for mode, hits in _searches(target, kind="state").items():
        assert target not in {hit["id"] for hit in hits}, mode


def test_an_unknown_id_falls_through_to_the_text_search(statements):
    for mode, hits in _searches("stm_0000").items():
        assert all(hit.get("matched_via") != "id" for hit in hits), mode
    assert server.grep_statements("stm_0000")["total"] == 0


def test_an_id_outside_the_audience_is_not_found(statements):
    visible = statements["Workspace exports are available as CSV"]
    hidden = statements["An admin can enable SSO for a workspace"]
    conn = store.substrate_connection()
    store.audience_labels.set_label(
        conn, visible, [EXTERNAL.id], source="ai", reason="r"
    )
    conn.commit()

    with audience_scope.applied(conn, audience_scope.capture(conn, EXTERNAL)):
        found = _searches(visible)
        hidden_found = _searches(hidden)

    for mode, hits in found.items():
        assert hits[0]["id"] == visible, mode
    for mode, hits in hidden_found.items():
        assert hidden not in {hit["id"] for hit in hits}, mode
