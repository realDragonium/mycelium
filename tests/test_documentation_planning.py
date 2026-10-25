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
    assert task.brief["profile"]["name"] == "public"
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
    from mycelium import (
        documentation_plan_review,
        documentation_profiles,
        prompt_store,
        server,
    )

    _profile()
    _reviewed_by_ai()
    first, second = _two_items(client, monkeypatch)
    prompt_store.save(
        prompt_store.connection(),
        type="doctrine",
        name="plan_review",
        text="Approve only what admins need.",
    )
    prompts: list[str] = []

    def review(task, config):
        assert task.system.startswith("Approve only what admins need.")
        assert "=== FIXED REVIEW CONTRACT ===" in task.system
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
        assert review.brief["profile"]["name"] == "public"
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


# --- recovery and larger plans ---------------------------------------------------


def _slot(slot: str, text: str) -> None:
    from mycelium import guidelines, prompt_store

    prompt_store.save(
        prompt_store.connection(),
        type=guidelines.TYPE,
        name=f"public/{slot}",
        text=text,
    )


def test_a_failed_review_is_retried_then_given_up_while_ai_recovers(
    client, monkeypatch
):
    from mycelium import documentation_plan_review, documentation_profiles

    _profile()
    _reviewed_by_ai()
    _slot("recovery", "ai")
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
    for _ in range(4):
        documentation_plan_review.sweep(documentation_profiles.capture())
        documentation_plan_review.wait_all()

    # Two retry attempts by default, then the items wait for a person.
    assert len(calls) == 3
    items = client.get("/api/documentation/plans/public").json()["items"]
    assert [(item["state"], item["review"]["failures"]) for item in items] == [
        ("proposed", 3),
        ("proposed", 3),
    ]
    assert items[0]["review"]["reason"].startswith("The review failed 3 times")


def _sweep_plans() -> None:
    from mycelium import documentation_profiles, server

    documentation_planning.plan_automatically(
        server._drafts_db(), server._db(), documentation_profiles.capture()
    )
    documentation_planning.wait_all()
    doc_runs.wait_all()


def test_a_failed_automatic_plan_is_retried_within_the_attempts(client, monkeypatch):
    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile()
    _slot("planning", "propose")
    _slot("recovery", "ai")
    set_product(
        product_settings.DocumentationPlanningSettings(replan_hint_statements=1)
    )
    with store.transaction(server._db()):
        store.create_statement(server._db(), "capability", "admins export invoices")
    calls: list[str] = []

    def failing(task, config):
        calls.append(task.prompt)
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(documentation_planning, "_call", failing)
    _sweep_plans()
    plan = client.get("/api/documentation/plans/public").json()
    assert plan["recovery_note"] == ("Automatic planning tries again (retry 1 of 2).")
    for _ in range(3):
        _sweep_plans()

    assert len(calls) == 3
    plan = client.get("/api/documentation/plans/public").json()
    assert plan["recovery_note"].startswith("Automatic planning gave up after 3")


def test_an_item_that_could_not_start_is_tried_again(client, monkeypatch):
    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile()
    _slot("planning", "write")
    _slot("recovery", "ai")
    set_product(
        product_settings.DocumentationPlanningSettings(replan_hint_statements=1)
    )
    with store.transaction(server._db()):
        sid = store.create_statement(
            server._db(), "capability", "admins export invoices"
        )
    call, _prompts = _answer(_item(statement_ids=[sid]))
    monkeypatch.setattr(documentation_planning, "_call", call)
    approve = documentation_planning.approve
    failures = iter([RuntimeError("the writer is busy")])

    def flaky(item_id, **kwargs):
        if (failure := next(failures, None)) is not None:
            raise failure
        return approve(item_id, **kwargs)

    monkeypatch.setattr(documentation_planning, "approve", flaky)
    _sweep_plans()
    _sweep_plans()
    (item,) = client.get("/api/documentation/plans/public").json()["items"]
    assert (item["state"], item["start_error"]) == ("proposed", "the writer is busy")

    _sweep_plans()
    (item,) = client.get("/api/documentation/plans/public").json()["items"]
    assert (item["state"], item["start_error"]) == ("approved", None)
    assert item["run"]["status"] == "document_written"


def test_a_plan_item_that_could_not_start_gives_up_at_its_own_limit(
    client, monkeypatch
):
    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile()
    _slot("planning", "write")
    _slot("recovery", "ai")
    set_product(
        product_settings.DocumentationPlanningSettings(
            item_start_retries=0, replan_hint_statements=1
        )
    )
    with store.transaction(server._db()):
        sid = store.create_statement(
            server._db(), "capability", "admins export invoices"
        )
    call, _prompts = _answer(_item(statement_ids=[sid]))
    monkeypatch.setattr(documentation_planning, "_call", call)
    attempts: list[str] = []

    def unavailable(item_id, **kwargs):
        attempts.append(item_id)
        raise RuntimeError("the writer is busy")

    monkeypatch.setattr(documentation_planning, "approve", unavailable)
    _sweep_plans()
    for _ in range(3):
        _sweep_plans()

    (item,) = client.get("/api/documentation/plans/public").json()["items"]
    assert item["state"] == "proposed"
    assert item["given_up"].startswith("Gave up after 1 attempt to start its run")
    assert len(attempts) == 1


def test_an_item_the_ai_reviewer_dismissed_is_not_proposed_again_by_automatic_planning(
    client, monkeypatch
):
    from mycelium import (
        documentation_plan_review,
        documentation_profiles,
        product_settings,
        server,
    )
    from product_settings_helpers import set_product

    _profile()
    _reviewed_by_ai()
    _slot("planning", "propose")
    set_product(
        product_settings.DocumentationPlanningSettings(replan_hint_statements=1)
    )
    statements = _statements(1)
    planning_calls: list[str] = []

    def propose(task, config):
        planning_calls.append(task.prompt)
        return Proposal(items=[_item(statement_ids=statements)]), ai.Usage()

    review_calls: list[str] = []

    def dismiss(task, config):
        review_calls.append(task.prompt)
        (item,) = json.loads(task.prompt)["items"]
        decision = {
            "item_id": item["item_id"],
            "decision": "dismiss",
            "reason": "The export guide is not needed.",
        }
        return documentation_plan_review.Verdicts(decisions=[decision]), ai.Usage()

    monkeypatch.setattr(documentation_planning, "_call", propose)
    monkeypatch.setattr(documentation_plan_review, "_call", dismiss)
    _sweep_plans()
    documentation_plan_review.sweep(documentation_profiles.capture())
    documentation_plan_review.wait_all()
    with store.transaction(server._db()):
        store.create_statement(
            server._db(), "capability", "workspace exports include invoice totals"
        )
    _sweep_plans()
    documentation_plan_review.sweep(documentation_profiles.capture())
    documentation_plan_review.wait_all()
    for _ in range(3):
        _sweep_plans()

    plan = client.get("/api/documentation/plans/public").json()
    assert plan["latest"]["dropped"] == {"dismissed before": 1}
    assert (len(planning_calls), len(review_calls)) == (2, 1)


def test_an_item_whose_run_gave_up_is_not_proposed_again_until_a_person_retries(
    client, monkeypatch
):
    from mycelium import document_maintenance, product_settings, server
    from product_settings_helpers import set_product

    _profile()
    _slot("planning", "write")
    _slot("recovery", "ai")
    set_product(
        product_settings.DocumentationPlanningSettings(replan_hint_statements=1)
    )
    set_product(product_settings.DocumentationMaintenanceSettings(run_retries=0))
    [statement] = _statements(1)
    call, _prompts = _answer(_item(statement_ids=[statement]))
    monkeypatch.setattr(documentation_planning, "_call", call)
    written = doc_runs.RUNNER
    refusal = {
        "outcome": "nothing_written",
        "reason": "the document did not include export steps",
    }
    doc_runs.RUNNER = lambda prompt, *, guideline_set, document_type: refusal
    _sweep_plans()
    _sweep_plans()
    document_maintenance.sweep()
    (failed,) = client.get("/api/documentation/plans/public").json()["items"]
    assert failed["given_up"].startswith("Gave up without an automatic retry")
    with store.transaction(server._db()):
        store.create_statement(
            server._db(), "capability", "workspace exports include invoice dates"
        )
    _sweep_plans()

    plan = client.get("/api/documentation/plans/public").json()
    assert plan["latest"]["dropped"] == {"given up before": 1}
    assert next(item for item in plan["items"] if item["id"] == failed["id"])[
        "given_up"
    ]

    doc_runs.RUNNER = written
    retried = client.post(
        f"/api/documentation/plan-items/{failed['id']}/retry", json={}
    )
    assert retried.status_code == 200, retried.text
    assert documentation_planning.given_up(server._drafts_db(), "public") == {}
    doc_runs.wait_all()


def test_a_given_up_item_stays_visible_after_a_newer_automatic_plan(
    client, monkeypatch
):
    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile()
    _slot("planning", "write")
    _slot("recovery", "ai")
    set_product(
        product_settings.DocumentationPlanningSettings(
            item_start_retries=0, replan_hint_statements=1
        )
    )
    [statement] = _statements(1)
    call, _prompts = _answer(_item(statement_ids=[statement]))
    monkeypatch.setattr(documentation_planning, "_call", call)

    def busy(item_id, **kwargs):
        raise RuntimeError("writer busy")

    monkeypatch.setattr(documentation_planning, "approve", busy)
    _sweep_plans()
    _sweep_plans()
    first = client.get("/api/documentation/plans/public").json()["items"][0]
    with store.transaction(server._db()):
        store.create_statement(
            server._db(), "capability", "workspace exports include invoice status"
        )
    _sweep_plans()

    plan = client.get("/api/documentation/plans/public").json()
    shown = next(item for item in plan["items"] if item["id"] == first["id"])
    assert shown["given_up"].startswith("Gave up after 1 attempt")
    assert plan["latest"]["dropped"] == {"given up before": 1}


def _statements(count: int) -> list[str]:
    from mycelium import server

    with store.transaction(server._db()):
        return [
            store.create_statement(
                server._db(), "capability", f"workspace export {n} is available"
            )
            for n in range(count)
        ]


def test_a_large_backlog_is_planned_over_several_calls(client, monkeypatch):
    from mycelium import product_settings
    from product_settings_helpers import set_product

    _profile()
    set_product(
        product_settings.DocumentationPlanningSettings(max_uncovered=2, max_calls=3)
    )
    ids = _statements(3)
    prompts: list[str] = []
    answers = iter(
        [
            _item(title="Export workspaces", statement_ids=ids[:2]),
            _item(title="Export limits", statement_ids=ids[2:]),
        ]
    )

    def call(task, config):
        prompts.append(task.prompt)
        return Proposal(items=[next(answers)]), ai.Usage(input_tokens=10)

    monkeypatch.setattr(documentation_planning, "_call", call)
    client.post("/api/documentation/plans/public")
    documentation_planning.wait_all()

    # The third call is not made: every statement was offered.
    assert len(prompts) == 2
    assert "already_proposed" not in json.loads(prompts[0])
    assert [item["title"] for item in json.loads(prompts[1])["already_proposed"]] == [
        "Export workspaces"
    ]
    plan = client.get("/api/documentation/plans/public").json()
    assert [item["title"] for item in plan["items"]] == [
        "Export workspaces",
        "Export limits",
    ]
    assert plan["latest"]["outcome"] == "planned"


def test_an_agent_plans_a_large_backlog_in_one_task_per_call(client):
    from mycelium import product_settings, server
    from product_settings_helpers import set_product

    _profile()
    _external(client, "documentation_planning")
    set_product(
        product_settings.DocumentationPlanningSettings(max_uncovered=2, max_calls=2)
    )
    ids = _statements(3)
    client.post("/api/documentation/plans/public")

    for title, statements in (
        ("Export workspaces", ids[:2]),
        ("Export limits", ids[2:]),
    ):
        [task] = server.claim_agent_task("documentation_planning").tasks
        item = json.loads(
            _item(title=title, statement_ids=statements).model_dump_json()
        )
        assert server.submit_agent_task(task.id, {"items": [item]}).status == "accepted"
    # The second call's brief listed what the first one proposed.
    assert "already_proposed" in str(task.brief["input"])

    plan = client.get("/api/documentation/plans/public").json()
    assert [item["title"] for item in plan["items"]] == [
        "Export workspaces",
        "Export limits",
    ]
    assert server.claim_agent_task("documentation_planning").tasks == []


def test_a_dismissed_statement_is_restored_and_the_plan_reads_over_mcp(client):
    from mycelium import server

    _profile()
    (sid,) = _statements(1)
    route = f"/api/documentation/plans/public/uncovered/{sid}"
    assert client.post(f"{route}/dismiss").status_code == 200

    plan = server.get_documentation_plan("public")
    assert [item.id for item in plan.dismissed_uncovered] == [sid]
    assert plan.uncovered_statements == 0

    assert client.post(f"{route}/restore").json() == {"restored": True}
    assert client.post(f"{route}/restore").status_code == 404
    plan = server.get_documentation_plan("public")
    assert (plan.dismissed_uncovered, plan.uncovered_statements) == ([], 1)
