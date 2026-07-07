"""Tests for `survey_statements` and its pure-logic module `survey`.

Two layers:
  * Pure-logic unit tests on `mycelium.survey` — plain data in, plain data
    out, no server / index / Ollama.
  * Integration tests on `server.survey_statements` with a real hnswlib
    index and a deterministic concept-based fake embedder, proving the six
    acceptance criteria by construction.

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

from mycelium import embed, phrasing, server, store, survey

# --- concept-based fake embedder --------------------------------------------

_CONCEPTS = {"rank": 0, "filter": 1, "permission": 2, "recruiter": 3}
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
    subs = survey.decompose("how does the flow rank candidates and how are permissions assigned")
    assert subs == ["how does the flow rank candidates", "how are permissions assigned"]
    # verbs survive the split (matters for an action-phrased substrate)
    assert any("rank" in s for s in subs)
    assert any("assigned" in s for s in subs)


def test_decompose_splits_on_punctuation_and_slash_and_or():
    assert survey.decompose("ranking; filtering, ordering?") == ["ranking", "filtering", "ordering"]
    assert survey.decompose("rank and/or filter") == ["rank", "filter"]
    assert survey.decompose("recruiter vs reviewer") == ["recruiter", "reviewer"]


def test_decompose_does_not_split_inside_words():
    # "android"/"corridor" contain and/or but have no word boundary there
    assert survey.decompose("android corridor") == ["android corridor"]


def test_decompose_single_part_returns_whole_query():
    assert survey.decompose("candidate selection flow") == ["candidate selection flow"]


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
    kept = survey.dedup_subqueries([("rank", v0), ("ranking", v0_dup), ("filter", v1)])
    assert kept == [("rank", v0), ("filter", v1)]


def test_dedup_subqueries_keeps_distinct_angles():
    v0 = [1.0, 0.0]
    v1 = [0.0, 1.0]
    kept = survey.dedup_subqueries([("a", v0), ("b", v1)])
    assert [s for s, _ in kept] == ["a", "b"]


def test_rank_statements_count_then_cosine_then_id():
    union = {
        "stm_single_hi": (1, 0.99),   # high score, but only one sub-query
        "stm_multi": (2, 0.50),       # two sub-queries → ranks first
        "stm_b": (1, 0.80),
        "stm_a": (1, 0.80),           # tie with stm_b on (count, cosine) → id breaks it
    }
    ranked = survey.rank_statements(union)
    assert ranked[0] == ("stm_multi", 0.50)            # count dominates
    assert ranked[1] == ("stm_single_hi", 0.99)        # then cosine
    assert [sid for sid, _ in ranked[2:]] == ["stm_a", "stm_b"]  # id asc tiebreak


# === integration harness ====================================================


def _reset_server() -> None:
    server._conn = None
    server._auth_conn = None
    server._drafts_conn = None
    server._index = None
    server._index_path = None
    server._ann_index = None
    server._ann_index_path = None
    server._name_index = None
    server._name_index_path = None


def _client(tmp_path, monkeypatch, embedder=concept_embed) -> TestClient:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    _reset_server()
    monkeypatch.setattr(embed, "embed", embedder)
    # Bypass phrasing (and its spaCy load) so test statements insert cleanly.
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    from mycelium.http import app

    return TestClient(app)


def _add(text: str) -> str:
    return server.upsert_statement(kind="event", text=text, links=[])["statement_id"]


# === acceptance-criteria integration tests ==================================


def test_survey_finds_what_search_misses(tmp_path, monkeypatch):
    """Criterion 1: on a multi-part query, survey surfaces statements the
    whole-query search misses."""
    with _client(tmp_path, monkeypatch):
        rank_id = _add("the flow ranks the candidates")          # axis: rank
        perm_id = _add("the system assigns permission to reviewers")  # axis: permission

        query = "how does the flow rank and how is permission assigned"

        # Whole-query vector blends both concepts (0.707 to each); at limit=1
        # only one part's statement comes back.
        search_hits = server.search_statements(query, limit=1, name_boost=0.0)
        assert len(search_hits) == 1
        search_ids = {h["id"] for h in search_hits}

        survey_hits = server.survey_statements(query, k=5)
        survey_ids = {h["id"] for h in survey_hits}

        # Survey covers BOTH parts; the one search dropped is among them.
        assert {rank_id, perm_id} <= survey_ids
        missed = {rank_id, perm_id} - search_ids
        assert missed and missed <= survey_ids


def test_shape_parity_with_search_statements(tmp_path, monkeypatch):
    """Criterion 2: a hit's shape is byte-for-byte the same type
    search_statements returns — a consumer cannot tell decomposition
    happened."""
    expected_keys = {
        "id", "kind", "text", "created_at", "updated_at",
        "created_by", "updated_by", "mentions", "links", "score",
        # search/survey hits are now fully hydrated, same as get_statements:
        "incoming_links", "when_references",
    }
    with _client(tmp_path, monkeypatch):
        rank_id = _add("the flow ranks the candidates")

        survey_hit = next(h for h in server.survey_statements("rank", k=5) if h["id"] == rank_id)
        search_hit = next(
            h for h in server.search_statements("rank", limit=5, name_boost=0.0)
            if h["id"] == rank_id
        )

        assert set(survey_hit) == set(search_hit) == expected_keys
        assert isinstance(survey_hit["score"], float)


def test_search_hits_fully_hydrated_with_capped_reverse_edges(tmp_path, monkeypatch):
    """A search hit now carries `incoming_links` + `when_references` (so no
    follow-up `get_statements` on the same id is needed), and the reverse edges
    are capped per hit so a convergence hub can't dominate the result — a
    `*_truncated` count points at `get_statements` for the complete set, which
    is itself uncapped."""
    from mycelium.server import _REVERSE_EDGE_CAP

    with _client(tmp_path, monkeypatch):
        target = _add("the flow ranks the candidates")
        n = _REVERSE_EDGE_CAP + 5
        for i in range(n):  # a hub: many statements point AT the target
            server.upsert_statement(
                kind="event",
                text=f"rank rule {i} governs the ranking",
                links=[{"link_type": "configures", "to_id": target}],
            )

        hit = next(
            h for h in server.search_statements("rank", limit=50, name_boost=0.0)
            if h["id"] == target
        )
        assert "incoming_links" in hit and "when_references" in hit
        assert len(hit["incoming_links"]) == _REVERSE_EDGE_CAP
        assert hit["incoming_links_truncated"] == n

        # get_statements is the explicit, targeted fetch — complete, uncapped.
        full = server.get_statements([target])["statements"][0]
        assert len(full["incoming_links"]) == n
        assert "incoming_links_truncated" not in full


def test_multi_surfaced_statement_ranks_above_single_and_dedupes(tmp_path, monkeypatch):
    """Criterion 3: a statement surfaced by several sub-queries ranks above
    one surfaced by a single sub-query, and appears exactly once."""
    with _client(tmp_path, monkeypatch):
        rank_id = _add("the flow ranks the candidates")               # rank
        perm_id = _add("the system assigns permission to reviewers")  # permission
        both_id = _add("the flow ranks and applies permission")       # rank + permission
        _add("a recruiter reviews the application")                   # distractor (recruiter)

        # k=2: each sub-query's top-2 is [its own statement, the blended one].
        hits = server.survey_statements("rank and permission", k=2)
        ids = [h["id"] for h in hits]

        assert ids.count(both_id) == 1  # deduped
        assert ids.index(both_id) < ids.index(rank_id)  # count beats raw cosine
        assert ids.index(both_id) < ids.index(perm_id)


def test_subquery_vector_dedup_collapses_identical_angles(tmp_path, monkeypatch):
    """Near-identical sub-query vectors are searched once, not twice."""
    with _client(tmp_path, monkeypatch):
        _add("the flow ranks the candidates")

        calls = {"n": 0}
        original = server._index.search

        def counting_search(vec, k):
            calls["n"] += 1
            return original(vec, k)

        monkeypatch.setattr(server._index, "search", counting_search)

        # "rank" and "ranking" both embed to the rank axis → one vector.
        server.survey_statements("rank and ranking", k=5)
        assert calls["n"] == 1


def test_empty_query_returns_empty_without_embedding(tmp_path, monkeypatch):
    """Edge case: blank query short-circuits before touching Ollama."""
    calls = {"n": 0}

    def counting_embed(text):
        calls["n"] += 1
        return concept_embed(text)

    with _client(tmp_path, monkeypatch, embedder=counting_embed):
        _add("the flow ranks the candidates")
        calls["n"] = 0  # reset after the upsert's embed
        assert server.survey_statements("   ", k=5) == []
        assert calls["n"] == 0


def test_whole_query_fallback_when_decomposition_is_dry(tmp_path, monkeypatch):
    """Criterion 4: a query whose decomposition yields nothing usable still
    returns results via the whole-query fallback."""
    seen: list[str] = []

    def recording_embed(text):
        seen.append(text)
        return concept_embed(text)

    with _client(tmp_path, monkeypatch, embedder=recording_embed):
        _add("the flow ranks the candidates")
        _add("the system assigns permission to reviewers")
        seen.clear()

        query = "the and of the"  # decomposes to all-stopword fragments
        hits = server.survey_statements(query, k=5)

        assert hits  # not empty-handed
        assert seen == [query]  # only the whole query was embedded (fallback)


def test_total_embed_outage_raises(tmp_path, monkeypatch):
    """Persistent embed failure on the fallback path is a real outage, not
    dry decomposition — it surfaces rather than masquerading as 'no hits'."""
    def boom(text):
        raise RuntimeError("ollama down")

    with _client(tmp_path, monkeypatch, embedder=boom):
        with pytest.raises(RuntimeError, match="ollama down"):
            server.survey_statements("rank and permission", k=5)


def test_partial_subquery_failure_degrades_gracefully(tmp_path, monkeypatch):
    """One sub-query failing to embed drops only that part; survivors still
    produce results (no fallback, no raise)."""
    seen: list[str] = []

    def flaky(text):
        seen.append(text)
        # Fail only on the decomposed "permission" sub-query, not on the
        # statement text embedded at upsert time.
        if text.strip().lower() == "permission":
            raise RuntimeError("flaky")
        return concept_embed(text)

    with _client(tmp_path, monkeypatch, embedder=flaky):
        rank_id = _add("the flow ranks the candidates")
        _add("the system assigns permission to reviewers")
        seen.clear()

        hits = server.survey_statements("rank and permission", k=5)
        ids = {h["id"] for h in hits}
        assert rank_id in ids  # the surviving "rank" sub-query still searched
        # This is graceful degrade, NOT whole-query fallback: the surviving
        # "rank" part was embedded; the whole query never was. (A regression
        # tripping the fallback on a single failure would embed the whole
        # query and this would catch it.)
        assert "rank" in seen
        assert "rank and permission" not in seen


def test_output_is_deterministic(tmp_path, monkeypatch):
    """Criterion: identical input yields identical output (ids, scores, order)."""
    with _client(tmp_path, monkeypatch):
        _add("the flow ranks the candidates")
        _add("the system assigns permission to reviewers")
        _add("the flow ranks and applies permission")

        query = "rank and permission"
        runs = [
            [(h["id"], h["score"]) for h in server.survey_statements(query, k=3)]
            for _ in range(3)
        ]
        assert runs[0] == runs[1] == runs[2]


def test_empty_index_returns_empty(tmp_path, monkeypatch):
    """No statements indexed → empty result, not an error."""
    with _client(tmp_path, monkeypatch):
        assert server.survey_statements("rank and permission", k=5) == []


def test_embed_retry_recovers_after_one_failure(tmp_path, monkeypatch):
    """Production requirement: retry once on a transient embed failure before
    treating the sub-query as empty — and the retry must actually recover."""
    state = {"rank_calls": 0}

    def flaky_once(text):
        if text.strip().lower() == "rank":
            state["rank_calls"] += 1
            if state["rank_calls"] == 1:
                raise RuntimeError("transient")
        return concept_embed(text)

    with _client(tmp_path, monkeypatch, embedder=flaky_once):
        rank_id = _add("the flow ranks the candidates")
        _add("a recruiter reviews the application")
        _add("the recruiter approves the application")

        # k=1 so the "recruiter" sub-query cannot surface the rank statement;
        # rank_id can only appear via the "rank" sub-query recovering on retry.
        hits = server.survey_statements("rank and recruiter", k=1)
        assert state["rank_calls"] == 2  # failed once, retried, succeeded
        assert rank_id in {h["id"] for h in hits}


def test_index_search_retry_recovers_after_one_failure(tmp_path, monkeypatch):
    """Production requirement: retry once on a transient index failure."""
    with _client(tmp_path, monkeypatch):
        rank_id = _add("the flow ranks the candidates")
        original = server._index.search
        state = {"n": 0}

        def flaky_search(vec, k):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("transient index")
            return original(vec, k)

        monkeypatch.setattr(server._index, "search", flaky_search)
        hits = server.survey_statements("rank", k=5)
        assert state["n"] == 2  # failed once, retried, succeeded
        assert rank_id in {h["id"] for h in hits}


def test_index_search_persistent_failure_yields_empty_not_error(tmp_path, monkeypatch):
    """A sub-query whose index search keeps failing contributes nothing — it
    is not an error and must not raise."""
    with _client(tmp_path, monkeypatch):
        _add("the flow ranks the candidates")

        def always_raise(vec, k):
            raise RuntimeError("index down")

        monkeypatch.setattr(server._index, "search", always_raise)
        # Every sub-query's search fails twice → empty union → empty result,
        # without raising.
        assert server.survey_statements("rank and permission", k=5) == []


def test_dedup_subqueries_threshold_value_and_direction():
    """The 0.95 default must actually be 0.95: a 0.96-similar pair collapses,
    a 0.94-similar pair is kept. Pins both the constant and the comparison
    direction (a regression to 0.80 or 0.99 would fail)."""
    def unit_at(cos_target):
        theta = math.acos(cos_target)
        return [math.cos(theta), math.sin(theta)]

    base = [1.0, 0.0]
    assert len(survey.dedup_subqueries([("a", base), ("b", unit_at(0.96))])) == 1
    assert len(survey.dedup_subqueries([("a", base), ("b", unit_at(0.94))])) == 2


def test_duplicate_vids_in_one_subquery_do_not_inflate_count(tmp_path, monkeypatch):
    """The per-sub-query `surfaced` guard: one sub-query that returns the same
    statement via two vector_ids must not out-rank a statement genuinely
    surfaced by two distinct sub-queries."""
    with _client(tmp_path, monkeypatch):
        dup_id = _add("the flow ranks the candidates")          # rank axis
        multi_id = _add("a recruiter reviews the application")  # recruiter axis

        def search(vec, k):
            if vec[0] == 1.0:  # the "rank" sub-query — same statement, two vids
                return [(101, 0.0), (102, 0.05)]   # cosines 1.0 and 0.95
            return [(200, 0.1)]                    # everything else → multi_id

        vid_map = {101: dup_id, 102: dup_id, 200: multi_id}
        monkeypatch.setattr(server._index, "search", search)
        monkeypatch.setattr(
            store, "get_statement_id_by_vector_id", lambda conn, vid: vid_map.get(vid)
        )

        # "rank" surfaces dup_id (twice, but counts once); "recruiter" and
        # "reviewer" each surface multi_id → multi_id count 2 > dup_id count 1,
        # so multi_id ranks first despite dup_id's higher cosine.
        hits = server.survey_statements("rank and recruiter and reviewer", k=5)
        ids = [h["id"] for h in hits]
        assert ids.index(multi_id) < ids.index(dup_id)
