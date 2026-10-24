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
from settings_helpers import assume_configured_models


@pytest.fixture(autouse=True)
def _anthropic_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    assume_configured_models(monkeypatch)


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


def test_a_batch_beyond_the_run_limit_queues_in_order(client, monkeypatch):
    import threading

    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile()
    set_product(product_settings.ConcurrencySettings(documentation_runs=1))
    set_product(product_settings.DocumentationPlanningSettings(approve_batch=3))
    release = threading.Event()
    written = doc_runs.RUNNER

    def runner(prompt, *, guideline_set, document_type):
        release.wait()
        return written(prompt, guideline_set=guideline_set, document_type=document_type)

    doc_runs.RUNNER = runner
    conn = server._db()
    with store.transaction(conn):
        statement = store.create_statement(conn, "capability", "invoices export")
    titles = ("Export invoices", "Invoice limits", "Invoice fields")
    items = _plan(
        client,
        monkeypatch,
        *(_item(title=title, statement_ids=[statement]) for title in titles),
    )["items"]

    approved = client.post(
        "/api/documentation/plan-items/approve",
        json={"item_ids": [item["id"] for item in items]},
    ).json()

    assert [entry["error"] for entry in approved] == [None, None, None]
    runs = [
        item["run"]
        for item in client.get("/api/documentation/plans/public").json()["items"]
    ]
    assert [(run["status"], run["queue_position"]) for run in runs] == [
        ("running", None),
        ("queued", 1),
        ("queued", 2),
    ]
    release.set()
    doc_runs.wait_all()
    finished = client.get("/api/documentation/plans/public").json()["items"]
    assert all(item["run"]["status"] not in ("queued", "running") for item in finished)


def test_an_approved_item_that_wrote_nothing_is_retried_from_the_plan(
    client, monkeypatch
):
    from mycelium import server

    _profile()
    refusal = {
        "outcome": "nothing_written",
        "reason": "the document failed review: conformance: Steps - no steps",
        "trace": {"summary": {"turns": 1}},
        "review": {
            "exposure": {"status": "pass", "findings": []},
            "conformance": {
                "status": "fail",
                "findings": [{"where": "Steps", "problem": "no steps"}],
            },
            "attempts": 2,
            "passed": False,
        },
    }
    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: refusal
    conn = server._db()
    with store.transaction(conn):
        statement = store.create_statement(conn, "capability", "invoices have limits")
    (item,) = _plan(
        client, monkeypatch, _item(title="Invoice limits", statement_ids=[statement])
    )["items"]
    client.post(
        "/api/documentation/plan-items/approve", json={"item_ids": [item["id"]]}
    )
    doc_runs.wait_all()
    refused = client.get("/api/documentation/plans/public").json()["items"][0]["run"]
    assert refused["status"] == "nothing_written"
    assert refused["review_notes"] is True

    retry = client.post(
        f"/api/documentation/plan-items/{item['id']}/retry",
        json={"with_review_notes": True},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["review_notes"] == [
        {"check": "conformance", "where": "Steps", "problem": "no steps"}
    ]
    doc_runs.wait_all()

    followed = client.get("/api/documentation/plans/public").json()["items"][0]["run"]
    assert followed["id"] == retry.json()["id"] != refused["id"]


def test_an_agent_plans_a_profile_and_its_proposal_is_kept_as_a_models(client):
    from mycelium import server

    _profile()
    conn = server._db()
    with store.transaction(conn):
        sid = store.create_statement(conn, "capability", "admins can export invoices")
    selected = next(
        action
        for action in client.get("/api/model-settings").json()["actions"]
        if action["action"] == "documentation_planning"
    )
    saved = client.patch(
        "/api/model-settings/documentation_planning",
        json={
            **{
                key: selected[key]
                for key in (
                    "provider",
                    "claude_model",
                    "openai_model",
                    "claude_reasoning_effort",
                    "openai_reasoning_effort",
                    "revision",
                )
            },
            "external_agent": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert client.post("/api/documentation/plans/public").status_code == 200
    assert (
        client.get("/api/documentation/plans/public").json()["latest"]["agent_task"][
            "status"
        ]
        == "waiting"
    )

    [task] = server.claim_agent_task("documentation_planning").tasks
    assert sid in str(task.brief)
    malformed = server.submit_agent_task(task.id, {"items": [{"title": "x"}]})
    assert malformed.status == "refused"
    kept = server.submit_agent_task(
        task.id,
        {"items": [json.loads(_item(statement_ids=[sid]).model_dump_json())]},
    )
    assert kept.status == "accepted"

    plan = client.get("/api/documentation/plans/public").json()
    assert plan["latest"]["outcome"] == "planned"
    assert [item["title"] for item in plan["items"]] == ["Export invoices"]


# --- AI plan review ---------------------------------------------------------------


def _reviewed_by_ai() -> None:
    from mycelium import guidelines, prompt_store

    prompt_store.save(
        prompt_store.connection(),
        type=guidelines.TYPE,
        name="public/plan_review",
        text="ai",
    )


def _two_items(client, monkeypatch) -> list[dict]:
    from mycelium import server

    conn = server._db()
    with store.transaction(conn):
        sid = store.create_statement(conn, "capability", "admins can export invoices")
    return _plan(
        client,
        monkeypatch,
        _item(statement_ids=[sid]),
        _item(title="Invoice limits", statement_ids=[sid]),
    )["items"]


def test_an_ai_reviewer_approves_and_dismisses_with_reasons(client, monkeypatch):
    from mycelium import documentation_plan_review, documentation_profiles, server

    _profile()
    _reviewed_by_ai()
    first, second = _two_items(client, monkeypatch)
    prompts: list[str] = []

    def review(task, config):
        prompts.append(task.prompt)
        verdicts = documentation_plan_review.Verdicts(
            decisions=[
                {"item_id": first["id"], "decision": "approve", "reason": "Needed."},
                {"item_id": second["id"], "decision": "dismiss", "reason": "Thin."},
            ]
        )
        return verdicts, ai.Usage(input_tokens=10, output_tokens=5)

    monkeypatch.setattr(documentation_plan_review, "_call", review)
    documentation_plan_review.sweep(documentation_profiles.capture())
    documentation_plan_review.wait_all()
    doc_runs.wait_all()

    assert "admins can export invoices" in prompts[0]
    items = client.get("/api/documentation/plans/public").json()["items"]
    assert [
        (item["state"], item["review"]["decision"], item["review"]["reason"])
        for item in items
    ] == [("approved", "approve", "Needed."), ("dismissed", "dismiss", "Thin.")]
    assert items[0]["run"]["status"] == "document_written"
    drafts = server._drafts_db()
    assert [row["key"] for row in doc_plans.dismissed(drafts, "public")] == [
        doc_plans.get_item(drafts, second["id"])["key"]
    ]
    # Decided items are not reviewed again.
    documentation_plan_review.sweep(documentation_profiles.capture())
    documentation_plan_review.wait_all()
    assert len(prompts) == 1


def test_a_failed_review_leaves_the_items_for_a_person(client, monkeypatch):
    from mycelium import documentation_plan_review, documentation_profiles

    _profile()
    _reviewed_by_ai()
    first, _second = _two_items(client, monkeypatch)
    calls: list[str] = []

    def review(task, config):
        calls.append(task.prompt)
        verdicts = documentation_plan_review.Verdicts(
            decisions=[
                {"item_id": first["id"], "decision": "approve", "reason": "Needed."}
            ]
        )
        return verdicts, ai.Usage()

    monkeypatch.setattr(documentation_plan_review, "_call", review)
    for _ in range(2):
        documentation_plan_review.sweep(documentation_profiles.capture())
        documentation_plan_review.wait_all()

    items = client.get("/api/documentation/plans/public").json()["items"]
    assert [(item["state"], item["review"]["decision"]) for item in items] == [
        ("proposed", None),
        ("proposed", None),
    ]
    assert "not decided" in items[0]["review"]["reason"]
    assert len(calls) == 1


def _external(client, action: str) -> None:
    selected = next(
        entry
        for entry in client.get("/api/model-settings").json()["actions"]
        if entry["action"] == action
    )
    saved = client.patch(
        f"/api/model-settings/{action}",
        json={
            **{
                key: selected[key]
                for key in (
                    "provider",
                    "claude_model",
                    "openai_model",
                    "claude_reasoning_effort",
                    "openai_reasoning_effort",
                    "revision",
                )
            },
            "external_agent": True,
        },
    )
    assert saved.status_code == 200, saved.text


def _as(principal_id: str):
    from mycelium import auth

    return auth.current_principal.set(
        auth.Principal(id=principal_id, name=principal_id, role="writer", type="human")
    )


def test_an_agent_reviews_another_agents_plan_over_the_task_queue(client):
    from mycelium import auth, server

    _profile()
    _reviewed_by_ai()
    _external(client, "documentation_planning")
    conn = server._db()
    with store.transaction(conn):
        sid = store.create_statement(conn, "capability", "admins can export invoices")

    planner = _as("planner")
    try:
        requested = server.request_documentation_plan("public")
        assert requested.agent_task is not None
        [task] = server.claim_agent_task("documentation_planning").tasks
        proposal = [
            json.loads(_item(title=title, statement_ids=[sid]).model_dump_json())
            for title in ("Export invoices", "Invoice limits")
        ]
        assert server.submit_agent_task(task.id, {"items": proposal}).status == (
            "accepted"
        )
        own = server.claim_agent_task("plan_review")
        assert own.tasks == [] and own.note and "a plan you made" in own.note
    finally:
        auth.current_principal.reset(planner)

    reviewer = _as("reviewer")
    try:
        [review] = server.claim_agent_task("plan_review").tasks
        first, second = (
            item["item_id"] for item in json.loads(str(review.brief["input"]))["items"]
        )
        partial = {
            "decisions": [
                {"item_id": first, "decision": "approve", "reason": "Needed."}
            ]
        }
        refused = server.submit_agent_task(review.id, partial)
        assert [f.where for f in refused.findings] == [second]
        done = server.submit_agent_task(
            review.id,
            {
                "decisions": [
                    *partial["decisions"],
                    {"item_id": second, "decision": "dismiss", "reason": "Duplicate."},
                ]
            },
        )
    finally:
        auth.current_principal.reset(reviewer)
    doc_runs.wait_all()

    assert done.status == "accepted", done.message
    items = client.get("/api/documentation/plans/public").json()["items"]
    assert [(item["state"], item["review"]["reviewer"]) for item in items] == [
        ("approved", "reviewer"),
        ("dismissed", "reviewer"),
    ]
    assert items[0]["run"]["status"] == "document_written"
