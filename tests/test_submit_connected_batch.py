from __future__ import annotations

import zlib

import pytest
from fastapi.testclient import TestClient

from mycelium import auth_store, drafts_store, server, store
from mycelium.connect.nli import NliLabel


def _word_embed(text: str) -> list[float]:
    vector = [0.0] * 768
    for word in text.lower().split():
        vector[zlib.crc32(word.encode()) % 768] += 1.0
    return vector


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    server._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", _word_embed)
    from mycelium.http import app

    return TestClient(app)


def _statement(kind: str, text: str) -> str:
    result = server.upsert_statement(
        kind=kind,
        text=text,
        links=[],
        allow_phrasing_violations=True,
    )
    assert "statement_id" in result, result
    return result["statement_id"]


def _company_entity() -> str:
    return server.upsert_entity(name="Company", description="an organization account")[
        "entity_id"
    ]


def _happy_statements(existing_id: str) -> list[dict]:
    return [
        {"kind": "property", "text": "Company"},
        {
            "kind": "capability",
            "text": "notification cadence can be configured on Company",
        },
        {
            "kind": "event",
            "text": "system records the company update",
            "links": [
                {"to_id": "@0", "link_type": "requires"},
                {"to_id": existing_id, "link_type": "requires"},
            ],
        },
    ]


def test_happy_path_writes_one_batch_and_provenanced_proposals(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        _company_entity()
        existing_id = _statement(
            "property", "the account profile stores contact details"
        )
        statements = _happy_statements(existing_id)

        response = server.submit_connected_batch(statements, title="Company cadence")

        assert response["draft_id"].startswith("drf_")
        assert response["results"] == [
            {"accepted": True, "batch_index": 0},
            {"accepted": True, "batch_index": 1},
            {"accepted": True, "batch_index": 2},
        ]
        assert response["proposals"] == {
            "links": len(response["links"]),
            "merges": len(response["merges"]),
            "conflicts": len(response["conflicts"]),
        }
        proposal_count = sum(response["proposals"].values())
        assert response["draft"] == {
            "status": "open",
            "op_count": 1 + proposal_count,
        }
        assert response["unresolved_hints"] == []
        assert any(
            link["batch_index"] == 1
            and link["target"] == "@0"
            and link["link_type"] == "configures"
            and link["pattern"] == "configures-capability"
            for link in response["links"]
        )

        draft = server.get_draft(response["draft_id"])
        assert draft["status"] == "open"
        assert draft["title"] == "Company cadence"
        assert draft["ops"][0]["seq"] == 1
        assert draft["ops"][0]["kind"] == "upsert_statements"
        assert draft["ops"][0]["payload"] == {"statements": statements}
        assert draft["ops"][0]["provenance"] is None
        assert len(draft["ops"]) == 1 + proposal_count
        assert all(op["provenance"] is not None for op in draft["ops"][1:])


def test_phrasing_rejections_match_upsert_and_survivor_refs_are_reindexed(
    tmp_path, monkeypatch
):
    statements = [
        {
            "kind": "event",
            "text": "user clicks the home button",
            "links": [
                {
                    "to_id": "@3",
                    "link_type": "triggers",
                    "when": {"statement_id": "@3"},
                }
            ],
        },
        {"kind": "event", "text": "user must verify email"},
        {
            "kind": "event",
            "text": "system retries the request",
            "links": [{"to_id": "@1", "link_type": "triggers"}],
        },
        {"kind": "event", "text": "system sends a confirmation email"},
    ]
    with _app(tmp_path / "connected", monkeypatch):
        connected = server.submit_connected_batch(statements)
        draft = server.get_draft(connected["draft_id"])

        assert connected["results"][0] == {"accepted": True, "batch_index": 0}
        assert connected["results"][1]["rejected"] is True
        assert connected["results"][1]["violations"][0]["category"] == "rule_shaped"
        assert connected["results"][2] == {
            "rejected": True,
            "reason": "depends_on_rejected",
            "depends_on": [1],
        }
        assert connected["results"][3] == {"accepted": True, "batch_index": 1}
        payload = draft["ops"][0]["payload"]["statements"]
        assert [item["text"] for item in payload] == [
            "user clicks the home button",
            "system sends a confirmation email",
        ]
        assert payload[0]["links"] == [
            {
                "to_id": "@1",
                "link_type": "triggers",
                "when": {"statement_id": "@1"},
            }
        ]

    with _app(tmp_path / "upsert", monkeypatch):
        upsert = server.upsert_statements(statements)

    connected_rejections = {
        index: result
        for index, result in enumerate(connected["results"])
        if result.get("rejected")
    }
    upsert_rejections = {
        index: result
        for index, result in enumerate(upsert["results"])
        if result.get("rejected")
    }
    assert connected_rejections == upsert_rejections


def test_phrasing_bypass_accepts_and_reports_the_violation(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.submit_connected_batch(
            [
                {
                    "kind": "event",
                    "text": "user must verify email",
                    "allow_phrasing_violations": True,
                }
            ]
        )

        assert response["results"][0]["accepted"] is True
        assert response["results"][0]["batch_index"] == 0
        assert (
            response["results"][0]["phrasing_violations"][0]["category"]
            == "rule_shaped"
        )
        draft = server.get_draft(response["draft_id"])
        assert draft["ops"][0]["payload"]["statements"] == [
            {
                "kind": "event",
                "text": "user must verify email",
                "allow_phrasing_violations": True,
            }
        ]


def test_unknown_mention_hint_is_reported_without_creating_records(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch):
        conn = server._db()
        entity_count = len(store.list_entities(conn))

        response = server.submit_connected_batch(
            [
                {
                    "kind": "event",
                    "text": "service returns the cached response",
                    "mention_hints": ["Unknown Account", "Unknown Account"],
                }
            ]
        )

        assert response["draft_id"].startswith("drf_")
        assert response["unresolved_hints"] == ["Unknown Account"]
        assert store.get_name_by_text(conn, "Unknown Account") is None
        assert len(store.list_entities(conn)) == entity_count


def test_resolved_mention_hint_is_not_reported(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        entity_id = _company_entity()

        response = server.submit_connected_batch(
            [
                {
                    "kind": "event",
                    "text": "service returns the cached response",
                    "mention_hints": ["Company"],
                }
            ]
        )

        assert response["unresolved_hints"] == []
        assert store.get_name_by_text(server._db(), "Company")["entity_id"] == entity_id


def test_nli_unavailable_keeps_similarity_only_merge(tmp_path, monkeypatch):
    text = "service returns the cached response"
    with _app(tmp_path, monkeypatch):
        existing_id = _statement("event", text)

        response = server.submit_connected_batch([{"kind": "event", "text": text}])

        assert response["nli"] == "unavailable"
        assert response["proposals"] == {"links": 0, "merges": 1, "conflicts": 0}
        assert len(response["merges"]) == 1
        merge = response["merges"][0]
        assert merge["batch_index"] == 0
        assert merge["into"] == existing_id
        assert merge["into_text"] == text
        assert 0.99 <= merge["score"] <= 1.0
        assert merge["nli"] is None
        # The only candidate became a proposal, so nothing is left to report.
        assert response["related"] == []


class FakeNli:
    def __init__(self, label: str) -> None:
        self._label = label

    def classify(self, pairs: list[tuple[str, str]]) -> list[NliLabel]:
        return [NliLabel(self._label, 0.9) for pair in pairs]


@pytest.mark.parametrize(
    ("label", "proposal_key"),
    [("entailment", "merges"), ("contradiction", "conflicts")],
)
def test_nli_proposals_include_directional_evidence(
    tmp_path, monkeypatch, label, proposal_key
):
    text = "service returns the cached response"
    with _app(tmp_path, monkeypatch):
        existing_id = _statement("event", text)
        monkeypatch.setattr(
            "mycelium.connect.nli.default_model", lambda: FakeNli(label)
        )

        response = server.submit_connected_batch([{"kind": "event", "text": text}])

        assert response["nli"] == "ran"
        assert len(response[proposal_key]) == 1
        proposal = response[proposal_key][0]
        target_key = "into" if proposal_key == "merges" else "statement_id"
        assert proposal[target_key] == existing_id
        assert proposal["nli"] == {
            "forward": {"label": label, "confidence": 0.9},
            "backward": {"label": label, "confidence": 0.9},
        }


def test_http_transport_and_mcp_registration(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch) as client:
        response = client.post(
            "/submit-connected-batch",
            json={
                "statements": [
                    {"kind": "event", "text": "service returns the cached response"}
                ]
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "draft_id",
            "results",
            "proposals",
            "links",
            "merges",
            "conflicts",
            "related",
            "dropped_merges",
            "unresolved_hints",
            "nli",
            "draft",
        }
        assert body["results"] == [{"accepted": True, "batch_index": 0}]
        assert body["draft"] == {"status": "open", "op_count": 1}
        registered = server.mcp._tool_manager.list_tools()
        assert "submit_connected_batch" in {tool.name for tool in registered}


def test_apply_connected_draft_replays_batch_and_proposed_link(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        _company_entity()
        response = server.submit_connected_batch(
            [
                {"kind": "property", "text": "Company"},
                {
                    "kind": "capability",
                    "text": "notification cadence can be configured on Company",
                },
            ]
        )
        assert len(response["links"]) == 1
        link = response["links"][0]
        assert link["batch_index"] == 1
        assert link["target"] == "@0"
        assert link["link_type"] == "configures"
        assert link["cue"] == "can be configured on"
        assert link["pattern"] == "configures-capability"
        assert 0.99 <= link["score"] <= 1.0

        applied = server.apply_draft(response["draft_id"])

        assert applied["applied"] == 2
        rows = store.list_statements(server._db(), limit=10)
        by_text = {row["text"]: row for row in rows}
        assert set(by_text) == {
            "Company",
            "notification cadence can be configured on Company",
        }
        source_id = by_text["notification cadence can be configured on Company"]["id"]
        target_id = by_text["Company"]["id"]
        assert store.get_links(server._db(), source_id) == [
            (target_id, "configures", None)
        ]
