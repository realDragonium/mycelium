from typing import Any

from fastapi.testclient import TestClient

from mycelium import store
from mycelium.server import runtime


def _dump() -> dict[str, Any]:
    def entity(id: str) -> dict[str, str]:
        return {"id": id, "name": id.title(), "description": ""}

    def statement(id: str, *mentions: str) -> dict[str, Any]:
        return {"id": id, "kind": "state", "text": id, "mentions": list(mentions)}

    return {
        "entities": [entity(e) for e in ("workspace", "invoice", "sso", "export")],
        "names": [
            {"id": f"n_{e}", "text": e, "entity": e}
            for e in ("workspace", "invoice", "sso", "export")
        ],
        "statements": [
            statement("s_bill", "workspace", "invoice"),
            statement("s_login", "workspace", "sso"),
            statement("s_csv", "export"),
            statement("s_lonely"),
        ],
        "links": [
            {"from": "s_bill", "to": "s_csv", "link_type": "triggers"},
            {"from": "s_login", "to": "s_bill", "link_type": "enables"},
        ],
        "entity_links": [
            {"from": "invoice", "to": "workspace", "link_type": "has"},
            {"from": "export", "to": "invoice", "link_type": "uses"},
        ],
    }


def _ids(records: list[dict[str, Any]]) -> set[str]:
    return {r["id"] for r in records}


def test_an_entity_brings_its_statements_their_entities_and_its_links():
    part = store.dump_neighbourhood(_dump(), "workspace")

    assert part is not None
    assert _ids(part["statements"]) == {"s_bill", "s_login"}
    assert _ids(part["entities"]) == {"workspace", "invoice", "sso"}
    assert {n["entity"] for n in part["names"]} == _ids(part["entities"])
    assert part["links"] == [
        {"from": "s_login", "to": "s_bill", "link_type": "enables"}
    ]
    assert part["entity_links"] == [
        {"from": "invoice", "to": "workspace", "link_type": "has"}
    ]


def test_a_statement_brings_the_statements_it_links_and_their_entities():
    part = store.dump_neighbourhood(_dump(), "s_bill")

    assert part is not None
    assert _ids(part["statements"]) == {"s_bill", "s_csv", "s_login"}
    assert _ids(part["entities"]) == {"workspace", "invoice", "sso", "export"}
    assert len(part["links"]) == 2


def test_an_unknown_focus_has_no_neighbourhood():
    assert store.dump_neighbourhood(_dump(), "nothing") is None


def test_concepts_are_ranked_by_how_many_statements_mention_them():
    degrees = store.concept_degrees(_dump())

    assert [(d["id"], d["statements"], d["links"]) for d in degrees] == [
        ("workspace", 2, 1),
        ("invoice", 1, 2),
        ("export", 1, 1),
        ("sso", 1, 0),
    ]


def test_the_graph_endpoints_read_the_callers_substrate(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    store.reset_substrate()
    runtime._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    from mycelium.http import create_app

    with TestClient(create_app()) as client:
        workspace = client.post(
            "/upsert-entity", json={"name": "Workspace", "description": ""}
        ).json()["entity_id"]
        concepts = client.get("/api/graph/concepts").json()
        assert concepts["statements"] == 0
        assert [c["name"] for c in concepts["concepts"]] == ["Workspace"]

        part = client.get("/api/graph/neighbourhood", params={"focus": workspace})
        assert part.status_code == 200
        assert _ids(part.json()["entities"]) == {workspace}
        missing = client.get("/api/graph/neighbourhood", params={"focus": "e_none"})
        assert missing.status_code == 404
