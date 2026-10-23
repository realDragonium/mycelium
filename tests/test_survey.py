"""Tests for `search_statements(decompose=True)` and its pure-logic module
`survey`.

Two layers:
  * Pure-logic unit tests on `mycelium.survey` — plain data in, plain data
    out, no server / index / Ollama.
  * Integration tests on `server.search_statements` with a real hnswlib
    index and a deterministic concept-based fake embedder.

The fake embedder maps each "concept" keyword to its own orthonormal axis,
so a query carrying two concepts embeds to the *blend* of both axes (cosine
0.707 to each), while a sub-query carrying one concept aligns perfectly with
statements about it. That is exactly the whole-question-blur the primitive
exists to fix, and it makes the geometry fully deterministic.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mycelium import auth_store, drafts_store, embed, phrasing, server, store, survey
from mycelium.server import runtime

# --- concept-based fake embedder --------------------------------------------

_CONCEPTS = {"rank": 0, "filter": 1, "permission": 2, "embed": 3}
_NEUTRAL_AXIS = 700  # for text carrying no concept keyword


def concept_embed(text: str) -> list[float]:
    """Deterministic 768-dim unit vector built from the concept keywords
    present in `text` (substring match). No concept → a neutral axis,
    orthogonal to every concept."""
    vec = np.zeros(768, dtype=np.float32)
    lowered = text.lower()
    axes = [axis for kw, axis in _CONCEPTS.items() if kw in lowered]
    if not axes:
        vec[_NEUTRAL_AXIS] = 1.0
        return vec.tolist()
    for axis in axes:
        vec[axis] = 1.0
    vec /= np.linalg.norm(vec)
    return vec.tolist()


# === pure-logic unit tests (no server, no index) ============================


def test_decompose_splits_on_conjunctions_preserving_verbs():
    subs = survey.decompose(
        "how does the flow rank statements and how are permissions assigned"
    )
    assert subs == ["how does the flow rank statements", "how are permissions assigned"]
    # verbs survive the split (matters for an action-phrased substrate)
    assert any("rank" in s for s in subs)
    assert any("assigned" in s for s in subs)


def test_decompose_splits_on_punctuation_and_slash_and_or():
    assert survey.decompose("ranking; filtering, ordering?") == [
        "ranking",
        "filtering",
        "ordering",
    ]
    assert survey.decompose("rank and/or filter") == ["rank", "filter"]
    assert survey.decompose("reader vs writer") == ["reader", "writer"]


def test_decompose_does_not_split_inside_words():
    # "android"/"corridor" contain and/or but have no word boundary there
    assert survey.decompose("android corridor") == ["android corridor"]


def test_decompose_single_part_returns_whole_query():
    assert survey.decompose("nearest neighbor search") == ["nearest neighbor search"]


def test_usable_drops_stopword_only_and_single_char():
    assert survey.usable("the") is False
    assert survey.usable("of the") is False
    assert survey.usable("how does it") is False
    assert survey.usable("a") is False
    assert survey.usable("x") is False
    assert survey.usable("permissions") is True
    assert survey.usable("how are permissions assigned") is True


def test_cosine():
    assert survey.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert survey.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert survey.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0  # zero vector → 0
    assert survey.cosine([1.0, 1.0], [1.0, 0.0]) == pytest.approx(1 / math.sqrt(2))


def test_dedup_subqueries_keeps_first_and_is_order_preserving():
    v0 = [1.0, 0.0, 0.0]
    v0_dup = [1.0, 0.0, 0.0]  # cosine 1.0 with v0 → dropped
    v1 = [0.0, 1.0, 0.0]
    kept = survey.dedup_subqueries(
        [("rank", v0), ("ranking", v0_dup), ("filter", v1)], threshold=0.95
    )
    assert kept == [("rank", v0), ("filter", v1)]


def test_dedup_subqueries_keeps_distinct_angles():
    v0 = [1.0, 0.0]
    v1 = [0.0, 1.0]
    kept = survey.dedup_subqueries([("a", v0), ("b", v1)], threshold=0.95)
    assert [s for s, _ in kept] == ["a", "b"]


def test_rank_statements_count_then_cosine_then_id():
    union = {
        "stm_single_hi": (1, 0.99),  # high score, but only one sub-query
        "stm_multi": (2, 0.50),  # two sub-queries → ranks first
        "stm_b": (1, 0.80),
        "stm_a": (1, 0.80),  # tie with stm_b on (count, cosine) → id breaks it
    }
    ranked = survey.rank_statements(union)
    assert ranked[0] == ("stm_multi", 0.50)  # count dominates
    assert ranked[1] == ("stm_single_hi", 0.99)  # then cosine
    assert [sid for sid, _ in ranked[2:]] == ["stm_a", "stm_b"]  # id asc tiebreak


# === integration harness ====================================================


def _reset_server() -> None:
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None


def _client(tmp_path, monkeypatch, embedder=concept_embed) -> TestClient:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    _reset_server()
    monkeypatch.setattr(embed, "embed", embedder)
    # Bypass phrasing (and its spaCy load) so test statements insert cleanly.
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    from mycelium.http import create_app

    return TestClient(create_app())


def _add(text: str) -> str:
    return server.upsert_statement(kind="event", text=text, links=[])["statement_id"]


# === integration tests ======================================================


def _decomposed(query: str, limit: int, **kwargs) -> list[dict]:
    return server.search_statements(
        query, limit=limit, name_boost=0.0, decompose=True, **kwargs
    )


def test_decompose_finds_what_whole_query_search_misses(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch):
        rank_id = _add("the flow ranks the statements")  # axis: rank
        perm_id = _add("the system assigns permission to reviewers")  # axis: permission

        query = "how does the flow rank and how is permission assigned"

        # The whole-query vector blends both concepts; at limit=1 only one
        # part's statement comes back.
        whole = {h["id"] for h in server.search_statements(query, limit=1)}
        assert len(whole) == 1

        assert {h["id"] for h in _decomposed(query, 1)} == {rank_id, perm_id}


def test_multi_surfaced_statement_ranks_above_single_and_dedupes(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch):
        rank_id = _add("the flow ranks the statements")  # rank
        perm_id = _add("the system assigns permission to reviewers")  # permission
        both_id = _add("the flow ranks and applies permission")  # rank + permission
        _add("the embedder processes the batch")  # distractor (embed)

        # limit=2: each part's top-2 is [its own statement, the blended one].
        ids = [h["id"] for h in _decomposed("rank and permission", 2)]

        assert ids.count(both_id) == 1
        assert ids.index(both_id) < ids.index(rank_id)  # count beats raw cosine
        assert ids.index(both_id) < ids.index(perm_id)


def test_decompose_applies_the_kind_filter_to_every_part(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch):
        _add("the flow ranks the statements")
        state_id = server.upsert_statement(
            kind="state", text="the permission is assigned", links=[]
        )["statement_id"]

        hits = _decomposed("rank and permission", 5, kind="state")

        assert [h["id"] for h in hits] == [state_id]


def test_identical_part_angles_are_searched_once(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch):
        _add("the flow ranks the statements")

        calls = {"n": 0}
        original = runtime._idx().search

        def counting_search(vec, k):
            calls["n"] += 1
            return original(vec, k)

        monkeypatch.setattr(runtime._idx(), "search", counting_search)

        # "rank" and "ranking" both embed to the rank axis → one vector.
        _decomposed("rank and ranking", 5)
        assert calls["n"] == 1


def test_whole_query_fallback_when_decomposition_is_dry(tmp_path, monkeypatch):
    seen: list[str] = []

    def recording_embed(text):
        seen.append(text)
        return concept_embed(text)

    with _client(tmp_path, monkeypatch, embedder=recording_embed):
        _add("the flow ranks the statements")
        seen.clear()

        query = "the and of the"  # decomposes to all-stopword fragments
        assert _decomposed(query, 5)
        assert seen == [query]


def test_total_embed_outage_falls_back_to_keywords(tmp_path, monkeypatch):
    def boom(text):
        raise embed.EmbeddingError("embedding provider down")

    with _client(tmp_path, monkeypatch):
        statement_id = _add("Workspace exports include invoice totals")
        monkeypatch.setattr(embed, "embed", boom)

        hits = _decomposed("workspace and invoice exports", 5)

        assert hits[0]["id"] == statement_id
        assert hits[0]["retrieval"] == "keyword"
        assert hits[0]["score"] == 1.0


def test_dedup_subqueries_threshold_value_and_direction():
    """The 0.95 default must actually be 0.95: a 0.96-similar pair collapses,
    a 0.94-similar pair is kept. Pins both the constant and the comparison
    direction (a regression to 0.80 or 0.99 would fail)."""

    def unit_at(cos_target):
        theta = math.acos(cos_target)
        return [math.cos(theta), math.sin(theta)]

    base = [1.0, 0.0]
    assert len(survey.dedup_subqueries([("a", base), ("b", unit_at(0.96))], 0.95)) == 1
    assert len(survey.dedup_subqueries([("a", base), ("b", unit_at(0.94))], 0.95)) == 2
