"""Documentation planning: what the planner may see, what it keeps, and the
review flow that turns approved items into documentation runs."""

from __future__ import annotations

import json

import pytest

from mycelium import (
    ai,
    audiences,
    doc_plans,
    doc_runs,
    docs_store,
    document_freshness,
    documentation_planning,
    store,
)
from mycelium.audiences import Audience
from mycelium.documentation_planning import (
    Concept,
    ExistingDocument,
    Overview,
    Proposal,
    ProposedItem,
)
from mycelium.documentation_profiles import PromptRevision, TemplateSnapshot
from product_settings_helpers import connection as product_connection

EXTERNAL = Audience(
    "external-technical", "External technical", "external", "Integrators.", 1
)
HOW_TO = TemplateSnapshot("how-to", PromptRevision("p1", 1, "Numbered steps."))


def _item(**overrides: object) -> ProposedItem:
    values: dict[str, object] = {
        "action": "create",
        "title": "Export invoices",
        "document_type": "how-to",
        "anchor_entity_id": None,
        "rationale": "Admins export invoices monthly.",
        "priority": "high",
        "statement_ids": ["s1"],
    }
    values.update(overrides)
    return ProposedItem.model_validate(values)


def _answer(*items: ProposedItem):
    prompts: list[str] = []

    def call(task, config):
        prompts.append(task.prompt)
        return Proposal(items=list(items)), ai.Usage(input_tokens=10, output_tokens=5)

    return call, prompts


@pytest.fixture
def stores(tmp_path):
    audiences.seed(product_connection())
    substrate = store.connect(tmp_path / "mycelium.db")
    store.migrate(substrate)
    drafts = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(drafts)
    try:
        yield substrate, drafts
    finally:
        substrate.close()
        drafts.close()


def test_an_external_plan_sees_and_keeps_only_what_its_audience_may_see(stores):
    substrate, drafts = stores
    public = store.create_statement(
        substrate, "capability", "workspace admins can export invoices as csv"
    )
    private = store.create_statement(
        substrate, "capability", "the export worker retries on the billing queue"
    )
    exports = store.create_entity(substrate, "Curator notes on invoice exports.")
    store.create_name(substrate, "invoice exports", exports)
    store.create_name(substrate, "export worker", exports)
    queue = store.create_entity(substrate, "An internal queue.")
    store.create_name(substrate, "billing queue", queue)
    index = store.build_name_index(substrate)
    store.derive_mentions(
        substrate, public, "workspace admins can export invoice exports", index
    )
    store.derive_mentions(
        substrate, private, "the export worker retries on the billing queue", index
    )
    store.audience_labels.set_label(
        substrate, public, [EXTERNAL.id], source="ai", reason="public feature"
    )
    substrate.commit()
    call, prompts = _answer(
        _item(anchor_entity_id=exports, statement_ids=[private, public]),
        _item(title="Queue tuning", anchor_entity_id=queue, statement_ids=[public]),
        _item(title="Worker retries", statement_ids=[private, "stm_invented"]),
    )
    plan_id = doc_plans.create_plan(
        drafts,
        guideline_set="public",
        audience_id=EXTERNAL.id,
        created_by=None,
        provider="claude",
        model="m",
    )

    documentation_planning.plan(
        drafts,
        substrate,
        plan_id,
        documentation_planning.Target("public", EXTERNAL, (HOW_TO,)),
        call=call,
    )

    sent = prompts[0]
    for hidden in (
        "billing queue",
        "export worker",
        "Curator notes",
        "An internal queue",
        private,
        queue,
    ):
        assert hidden not in sent
    assert [item["id"] for item in json.loads(sent)["key_statements"]] == [public]
    [kept] = doc_plans.items(drafts, plan_id)
    assert kept["anchor_entity_id"] == exports
    assert json.loads(kept["statement_ids"]) == [public]
    summary = json.loads(doc_plans.latest_plan(drafts, "public")["summary"])
    assert summary["dropped"] == {
        "concept outside the overview": 1,
        "no visible statements": 1,
    }


def _overview() -> Overview:
    return Overview(
        visible=frozenset({"s1", "s2", "s3", "s4"}),
        concepts={
            "ent_sso": Concept(
                "ent_sso", "SSO", None, None, 4, {"capability": 4}, ("s2", "s3", "s4")
            )
        },
        key_statements=(),
    )


def _document(**overrides: object) -> ExistingDocument:
    values: dict[str, object] = {
        "id": "doc_1",
        "title": "Set up SSO",
        "document_type": "how-to",
        "anchor_entity_id": "ent_sso",
        "revision": 3,
        "freshness": document_freshness.Freshness("current"),
    }
    values.update(overrides)
    return ExistingDocument(**values)  # type: ignore[arg-type]


def _accept(
    *items: ProposedItem, dismissed: frozenset[str] = frozenset(), max_items: int = 10
):
    return documentation_planning.accept(
        Proposal(items=list(items)),
        overview=_overview(),
        document_types=["how-to", "reference"],
        documents=[_document()],
        dismissed=set(dismissed),
        max_items=max_items,
    )


def test_an_anchored_create_for_an_existing_document_becomes_its_update():
    [item] = _accept(
        _item(title="Configure SSO", anchor_entity_id="ent_sso", statement_ids=["s1"])
    ).items

    assert (item.action, item.document_id, item.key) == (
        "update",
        "doc_1",
        "update:doc_1:r3",
    )
    # Topped up from the concept's own statements.
    assert item.statement_ids == ("s1", "s2", "s3")


def test_unknown_duplicate_and_dismissed_proposals_are_dropped():
    dismissed = documentation_planning.create_key("reference", None, "Invoice fields")
    result = _accept(
        _item(document_type="tutorial"),
        _item(title="Set up SSO!"),
        _item(action="update", document_id="doc_gone"),
        _item(document_type="reference", title="Invoice fields"),
        _item(title="Export invoices"),
        _item(title="export  invoices"),
        _item(title="Invoice limits"),
        dismissed=frozenset({dismissed}),
        max_items=1,
    )

    assert [item.title for item in result.items] == ["Export invoices"]
    assert result.dropped == {
        "unknown document type": 1,
        "duplicates an existing document": 1,
        "update of an unknown document": 1,
        "dismissed before": 1,
        "duplicates another item": 1,
        "over the item limit": 1,
    }


# --- HTTP ----------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    from test_prompt_texts import _app

    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: {
        "outcome": "document_written",
        "slug": "export-invoices",
        "title": "Export invoices",
        "body": "# Export invoices\n",
        "statement_ids": ["stm_x"],
    }
    try:
        with _app(tmp_path, monkeypatch) as client:
            yield client
    finally:
        documentation_planning.wait_all()
        doc_runs.wait_all()
        doc_runs.RUNNER = None


def _profile() -> None:
    from mycelium import guidelines, prompt_store

    for slot, text in (("guidance", "Plain words."), ("how-to", "Numbered steps.")):
        prompt_store.save(
            prompt_store.connection(),
            type=guidelines.TYPE,
            name=f"public/{slot}",
            text=text,
        )


def _plan(client, monkeypatch, *items: ProposedItem) -> dict:
    call, _prompts = _answer(*items)
    monkeypatch.setattr(documentation_planning, "_call", call)
    started = client.post("/api/documentation/plans/public")
    assert started.status_code == 200, started.text
    documentation_planning.wait_all()
    return client.get("/api/documentation/plans/public").json()


def test_a_plan_is_reviewed_into_runs_and_a_dismissal_sticks(client, monkeypatch):
    from mycelium import server

    _profile()
    conn = server._db()
    with store.transaction(conn):
        exports = store.create_entity(conn, None)
        store.create_name(conn, "invoice export", exports)
        index = store.build_name_index(conn)
        ids = []
        for n in range(10):
            text = f"invoice export step {n} is available"
            ids.append(store.create_statement(conn, "capability", text))
            store.derive_mentions(conn, ids[-1], text, index)
    proposals = (
        _item(anchor_entity_id=exports, statement_ids=ids[:2]),
        _item(title="Invoice limits", statement_ids=ids[2:3]),
    )

    plan = _plan(client, monkeypatch, *proposals)

    assert plan["latest"]["outcome"] == "planned", plan["latest"]
    assert [item["title"] for item in plan["items"]] == [
        "Export invoices",
        "Invoice limits",
    ]
    assert [gap["entity_id"] for gap in plan["coverage"]] == [exports]
    first, second = plan["items"]
    approved = client.post(
        "/api/documentation/plan-items/approve", json={"item_ids": [first["id"]]}
    ).json()
    assert approved[0]["run"]["anchor_entity_id"] == exports
    doc_runs.wait_all()
    assert client.post(f"/api/documentation/plan-items/{second['id']}/dismiss").json()

    plan = client.get("/api/documentation/plans/public").json()
    assert [
        (item["state"], item["run"] and item["run"]["status"]) for item in plan["items"]
    ] == [
        ("approved", "document_written"),
        ("dismissed", None),
    ]
    assert plan["coverage"] == []
    # This profile's audience is internal and already saw the unlabelled
    # statement, so labelling it adds nothing new since the plan.
    with store.transaction(conn):
        store.audience_labels.set_label(
            conn, ids[9], ["internal-technical"], source="ai", reason="internal"
        )
    assert client.get("/api/documentation/plans/public").json()["new_since_plan"] == 0
    again = client.post(
        "/api/documentation/plan-items/approve", json={"item_ids": [first["id"]]}
    ).json()
    assert again[0]["error"] == "This item was already approved."

    replanned = _plan(client, monkeypatch, *proposals)
    # The anchored document now exists, so proposing it again is an update;
    # the dismissed proposal stays gone.
    assert [(item["action"], item["title"]) for item in replanned["items"]] == [
        ("update", "Export invoices")
    ]
    assert replanned["latest"]["dropped"] == {"dismissed before": 1}
