"""External agents doing an action's model work through the task queue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mycelium import agent_tasks, docs_store, prompt_store, store, timestamps
from mycelium.docgen import loop
from mycelium.docgen.schema import ReviewCheck, ReviewRecord
from test_principal_audience import (
    SECRET,
    _bearer,
    _corpus,
    client,  # noqa: F401 — fixture
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def drafts(tmp_path):
    conn = docs_store.connect(tmp_path / "mycelium-drafts.db")
    docs_store.migrate(conn)
    yield conn
    conn.close()


def _queue(conn, excluded: str | None = None) -> str:
    return agent_tasks.create(
        conn, "documentation", subject_id=None, state={}, excluded_claimant=excluded
    )


def test_a_lease_renews_on_claim_and_expires_back_to_the_queue(drafts):
    first, second = _queue(drafts), _queue(drafts)

    chosen, renewed, _ = agent_tasks.claim(
        drafts, "documentation", claimant="a", limit=1, now=NOW
    )
    assert ([t.id for t in chosen], renewed) == ([first], [])
    later = NOW + timedelta(minutes=20)
    chosen, renewed, expires = agent_tasks.claim(
        drafts, "documentation", claimant="a", limit=0, now=later
    )
    assert (chosen, renewed) == ([], [first])
    assert expires == timestamps.of(later + agent_tasks.LEASE)

    chosen, _, _ = agent_tasks.claim(
        drafts, "documentation", claimant="b", limit=5, now=later + timedelta(hours=1)
    )
    assert [t.id for t in chosen] == [first, second]


def test_a_task_is_never_offered_to_the_claimant_it_excludes(drafts):
    task = _queue(drafts, excluded="writer")

    assert (
        agent_tasks.claim(drafts, "documentation", claimant="writer", limit=1, now=NOW)[
            0
        ]
        == []
    )
    chosen, _, _ = agent_tasks.claim(
        drafts, "documentation", claimant="other", limit=1, now=NOW
    )
    assert [t.id for t in chosen] == [task]


# --- documentation over HTTP ---------------------------------------------------


def _select_agent(http, admin, action: str, **extra) -> None:
    current = http.get("/api/model-settings", headers=admin).json()
    selected = next(a for a in current["actions"] if a["action"] == action)
    body = {
        key: selected[key]
        for key in (
            "provider",
            "claude_model",
            "openai_model",
            "claude_reasoning_effort",
            "openai_reasoning_effort",
            "revision",
        )
    }
    r = http.patch(
        f"/api/model-settings/{action}",
        headers=admin,
        json={**body, "external_agent": True, **extra},
    )
    assert r.status_code == 200, r.text


def _external_documentation(http, admin, monkeypatch, *, review="server"):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    prompt_store.save(
        prompt_store.connection(),
        type="guideline-set",
        name="kb-authoring/audience",
        text="external-technical",
    )
    _select_agent(http, admin, "docgen", agent_review=review)


def _request(http, writer) -> dict:
    r = http.post(
        "/request-documentation",
        headers=writer,
        json={
            "prompt": "Explain workspace exports",
            "guideline_set": "kb-authoring",
            "document_type": "how-to",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _call(http, headers, name: str, **body) -> dict:
    r = http.post(f"/{name.replace('_', '-')}", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _passing(*_args) -> ReviewRecord:
    passed = ReviewCheck(status="pass", findings=[])
    return ReviewRecord(exposure=passed, conformance=passed, attempts=1, passed=True)


def _document(public: str) -> dict:
    return {
        "title": "Export a workspace",
        "body": "# Export a workspace\n\nA workspace export downloads as a CSV file.",
        "statement_ids": [public],
    }


def test_an_external_agent_writes_inside_the_audience_and_its_gates(
    client,  # noqa: F811
    monkeypatch,
):
    admin = _bearer("admin")
    public, hidden, _entity = _corpus(client, admin)
    _external_documentation(client, admin, monkeypatch)
    writer = _bearer("writer")

    run = _request(client, writer)
    assert run["status"] == "waiting_for_agent"
    assert run["agent_task"]["status"] == "waiting"

    refused = client.post(
        "/claim-agent-task", headers=_bearer("drafter"), json={"kind": "documentation"}
    )
    assert refused.status_code == 403

    [task] = _call(client, writer, "claim_agent_task", kind="documentation")["tasks"]
    assert task["subject_id"] == run["id"]
    assert task["brief"]["audience"]["id"] == "external-technical"
    assert SECRET not in str(task["brief"])

    read = _call(
        client,
        writer,
        "read_for_agent_task",
        task_id=task["id"],
        tool="get_statements",
        arguments={"ids": [public, hidden]},
    )
    assert public in read["content"] and SECRET not in read["content"]

    leaked = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result={**_document(public), "statement_ids": [public, hidden]},
    )
    assert leaked["status"] == "refused"
    assert "outside this run's audience" in leaked["findings"][0]["problem"]

    monkeypatch.setattr(loop, "_review", _passing)
    saved = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result=_document(public),
    )
    assert saved["status"] == "accepted"
    done = _call(client, writer, "get_documentation_run", run_id=run["id"])
    assert done["outcome"] == "document_written"
    assert done["agent_task"]["status"] == "done"


def test_an_agent_review_is_never_the_writer_and_its_refusal_returns_findings(
    client,  # noqa: F811
    monkeypatch,
):
    admin = _bearer("admin")
    public, _hidden, _entity = _corpus(client, admin)
    _external_documentation(client, admin, monkeypatch, review="agent")
    writer, reviewer = _bearer("writer"), _bearer("writer")
    run = _request(client, writer)
    [task] = _call(client, writer, "claim_agent_task", kind="documentation")["tasks"]
    _call(
        client,
        writer,
        "read_for_agent_task",
        task_id=task["id"],
        tool="get_statements",
        arguments={"ids": [public]},
    )
    held = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result=_document(public),
    )
    assert held["status"] == "in_review"

    assert (
        _call(client, writer, "claim_agent_task", kind="document_review")["tasks"] == []
    )
    [review] = _call(client, reviewer, "claim_agent_task", kind="document_review")[
        "tasks"
    ]
    failing = {
        "exposure": {"status": "pass", "findings": []},
        "conformance": {
            "status": "fail",
            "findings": [{"where": "Steps", "problem": "No numbered steps."}],
        },
    }
    outcome = _call(
        client, reviewer, "submit_agent_task", task_id=review["id"], result=failing
    )
    assert outcome["status"] == "accepted"
    assert outcome["findings"][0]["check"] == "conformance"

    [again] = _call(client, writer, "claim_agent_task", kind="documentation")["tasks"]
    assert again["id"] == task["id"]
    assert again["findings"][0]["problem"] == "No numbered steps."
    current = _call(client, writer, "get_documentation_run", run_id=run["id"])
    assert current["status"] == "waiting_for_agent"


def test_a_waiting_run_survives_a_restart(client, monkeypatch):  # noqa: F811
    from mycelium.server import runtime

    admin = _bearer("admin")
    _corpus(client, admin)
    _external_documentation(client, admin, monkeypatch)
    run = _request(client, _bearer("writer"))

    assert docs_store.mark_orphaned(runtime._drafts_db()) == 0
    current = _call(client, admin, "get_documentation_run", run_id=run["id"])
    assert current["status"] == "waiting_for_agent"


def test_only_agent_capable_actions_take_an_external_agent(client):  # noqa: F811
    admin = _bearer("admin")
    current = client.get("/api/model-settings", headers=admin).json()
    supported = {a["action"] for a in current["actions"] if a["agent_supported"]}
    assert supported == {
        "docgen",
        "documentation_planning",
        "audience_labelling",
        "ingest",
        "connect",
        "alias_discovery",
    }
    with pytest.raises(AssertionError, match="cannot be done by an external agent"):
        _select_agent(client, admin, "ask")
    with pytest.raises(AssertionError, match="Only documentation has an agent review"):
        _select_agent(client, admin, "audience_labelling", agent_review="agent")


# --- audience labelling --------------------------------------------------------


def test_an_agent_labels_statements_only_with_audiences_that_exist(client):  # noqa: F811
    from mycelium.server import runtime

    admin = _bearer("admin")
    public, hidden, _entity = _corpus(client, admin)
    _select_agent(client, admin, "audience_labelling")
    writer = _bearer("writer")

    [task] = _call(client, writer, "claim_agent_task", kind="audience_labelling")[
        "tasks"
    ]
    assert hidden in task["brief"]["input"] and public not in task["brief"]["input"]

    def labels(audience: str) -> dict:
        return {
            "labels": [
                {
                    "statement_id": hidden,
                    "audiences": ["internal-technical", audience],
                    "reason": "Operators run the queue.",
                    "narrowing_reason": "",
                }
            ]
        }

    unknown = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result=labels("no-such-audience"),
    )
    assert unknown["status"] == "refused"
    assert unknown["findings"][0]["check"] == "labels"

    applied = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result=labels("internal-non-technical"),
    )
    assert applied["status"] == "accepted"
    label = store.audience_labels.get_label(runtime._db(), hidden)
    assert label is not None and "internal-non-technical" in label["audiences"]
    status = client.get("/api/audiences/labelling", headers=admin).json()
    assert status["external_agent"] is True
    assert status["agent_tasks"] == []


# --- ingest, connect and alias discovery ---------------------------------------


def _read(http, headers, task: str, tool: str, **arguments) -> dict:
    return _call(
        http,
        headers,
        "read_for_agent_task",
        task_id=task,
        tool=tool,
        arguments=arguments,
    )


def _reconcile(http, headers, task: str) -> None:
    """The reads ingest's floor asks for: reconcile, then search around."""
    _read(http, headers, task, "search_statements", query="workspace export")
    _read(http, headers, task, "search_statements", query="CSV download")


def _row(candidate: str, classification: str, matched: list[str]) -> dict:
    return {
        "candidate": candidate,
        "classification": classification,
        "matched_against": matched,
        "link_candidates_considered": matched,
        "note": "",
    }


def test_an_agent_ingests_text_through_the_loops_floor(client):  # noqa: F811
    import json

    admin = _bearer("admin")
    public, _hidden, _entity = _corpus(client, admin)
    _select_agent(client, admin, "ingest")
    requester, agent = _bearer("writer"), _bearer("writer")

    queued = _call(
        client, requester, "ingest", text="A workspace export can be scheduled."
    )
    assert queued["outcome"] == "waiting_for_agent"
    [task] = _call(client, agent, "claim_agent_task", kind="ingest")["tasks"]
    assert task["id"] == queued["agent_task"]
    assert "A workspace export can be scheduled." in task["brief"]["input"]
    assert "emit_draft" not in {t["name"] for t in task["brief"]["read_tools"]}
    emit = {
        "ops": [
            {
                "op": "upsert_statement",
                "payload_json": json.dumps(
                    {
                        "kind": "capability",
                        "text": "a workspace export can be scheduled",
                        "links": [],
                    }
                ),
                "rationale": "new",
                "targets_existing": [public],
            }
        ],
        "ledger": [_row("a workspace export can be scheduled", "new", [public])],
        "flagged": [],
        "skipped_duplicates": [],
    }

    unread = _call(client, agent, "submit_agent_task", task_id=task["id"], result=emit)
    assert unread["status"] == "refused"
    assert unread["findings"][0]["check"] == "floor"

    _reconcile(client, agent, task["id"])
    done = _call(client, agent, "submit_agent_task", task_id=task["id"], result=emit)
    assert done["status"] == "accepted", done
    followed = _call(client, requester, "get_agent_task", task_id=task["id"])
    assert followed["status"] == "done"
    assert followed["result"]["outcome"] == "draft_created"
    draft = client.get(
        f"/api/drafts/{followed['result']['draft_id']}", headers=admin
    ).json()
    assert "a workspace export can be scheduled" in json.dumps(draft)
    stranger = client.post(
        "/get-agent-task", headers=_bearer("drafter"), json={"task_id": task["id"]}
    )
    assert stranger.status_code != 200


def test_an_agent_connect_pass_records_what_it_looked_at(client):  # noqa: F811
    from mycelium.server import runtime

    admin = _bearer("admin")
    _public, hidden, _entity = _corpus(client, admin)
    lone = _call(
        client,
        admin,
        "upsert_statement",
        kind="state",
        text="An invoice lists every workspace seat.",
        links=[],
        allow_phrasing_violations=True,
    )["statement_id"]
    _select_agent(client, admin, "connect")
    writer = _bearer("writer")

    def offered() -> set[str]:
        page = client.get(
            "/api/knowledge-health/statements/isolated?to_connect=true", headers=admin
        ).json()
        return {item["id"] for item in page["items"]}

    assert lone in offered()
    queued = _call(client, writer, "connect_statements", statement_ids=[lone])
    assert queued["outcome"] == "waiting_for_agent"
    assert lone not in offered()
    [task] = _call(client, writer, "claim_agent_task", kind="connect")["tasks"]
    assert lone in task["brief"]["input"]
    _reconcile(client, writer, task["id"])
    done = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result={
            "ops": [],
            "ledger": [_row(lone, "duplicate", [hidden])],
            "flagged": [],
            "skipped_duplicates": [],
        },
    )
    assert done["status"] == "accepted", done
    looked = runtime._db().execute(
        "SELECT neighbours FROM curation_attempts WHERE item_id = ?", (lone,)
    )
    assert [row[0] for row in looked] == [f'["{hidden}"]']


def test_an_agent_alias_scan_keeps_only_evidence_from_the_selection(client):  # noqa: F811
    admin = _bearer("admin")
    public, hidden, entity = _corpus(client, admin)
    _select_agent(client, admin, "alias_discovery")
    writer = _bearer("writer")

    r = client.post(
        "/api/alias-suggestions/scan", headers=writer, json={"statement_ids": [public]}
    )
    assert r.status_code == 200, r.text
    queued = r.json()
    assert queued["suggestions"] == [] and queued["agent_task"]
    [task] = _call(client, writer, "claim_agent_task", kind="alias_discovery")["tasks"]
    assert SECRET not in task["brief"]["input"].split('"concepts"')[0]

    def proposal(statement_id: str) -> dict:
        return {
            "suggestions": [
                {
                    "entity_id": entity,
                    "alias": "CSV file",
                    "quote": "downloads as a CSV file",
                    "reason": "Names the export by its file.",
                    "ambiguity": "",
                    "statement_id": statement_id,
                }
            ]
        }

    outside = _call(
        client,
        writer,
        "submit_agent_task",
        task_id=task["id"],
        result=proposal(hidden),
    )
    assert outside["status"] == "refused"
    assert outside["findings"][0]["check"] == "evidence"
    kept = _call(
        client, writer, "submit_agent_task", task_id=task["id"], result=proposal(public)
    )
    assert kept["status"] == "accepted", kept
    pending = client.get("/api/alias-suggestions", headers=admin).json()
    [entry] = pending["suggestions"]
    assert entry["suggestion"]["model"].startswith("agent:")
    assert entry["suggestion"]["proposal"]["alias"] == "CSV file"
