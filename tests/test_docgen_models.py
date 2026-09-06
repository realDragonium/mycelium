"""Provider routing and stateless Responses continuation, without API calls."""

from __future__ import annotations

import json
import threading
from dataclasses import replace

import httpx
import pytest
from pydantic import JsonValue

from mycelium import ai, doc_runs, docgen, docs_store
from mycelium.docgen.config import DocgenConfig, model_choices, resolve_provider
from mycelium.docgen.loop import _execute
from mycelium.docgen.schema import DocumentWritten, NothingWritten
from settings_helpers import save_model
from test_docgen import FakeGapReporter, _substrate


def _call(
    name: str, arguments: dict[str, JsonValue], call_id: str = "call_one"
) -> dict[str, JsonValue]:
    return {
        "type": "function_call",
        "id": "fc_one",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments),
    }


def _response(
    *items: dict[str, JsonValue], status: str = "completed"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": status,
            "output": list(items),
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "input_tokens_details": {"cached_tokens": 3},
            },
        },
    )


def _config() -> DocgenConfig:
    return DocgenConfig(
        provider="openai",
        model="configured-gpt",
        trace_dir="",
        input_per_mtok=None,
        output_per_mtok=None,
    )


def _model_config() -> ai.ModelConfig:
    return ai.ModelConfig(
        provider="openai",
        model="configured-gpt",
        max_tokens=12000,
        request_timeout_s=120,
    )


def _tool() -> dict[str, object]:
    return {
        "name": "lookup",
        "description": "read",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": [],
        },
    }


def test_responses_continuation_keeps_reasoning_and_forced_call_ids(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = []
    reasoning = {
        "type": "reasoning",
        "id": "rs_one",
        "summary": [],
        "encrypted_content": "opaque-reasoning",
    }
    call = _call("lookup", {"query": "SSO"})

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return _response(reasoning, call)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = ai.turn(
            ai.ToolTask(
                messages=[{"role": "user", "content": "write SSO"}],
                tools=[_tool()],
                system="writer",
                force_tool=None,
            ),
            _model_config(),
            client=client,
        )
        ai.turn(
            ai.ToolTask(
                messages=[
                    {"role": "user", "content": "write SSO"},
                    {"role": "assistant", "content": first.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call_one",
                                "content": "found",
                            }
                        ],
                    },
                ],
                tools=[_tool()],
                system="writer",
                force_tool="lookup",
            ),
            _model_config(),
            client=client,
        )
    assert captured[1]["input"][1:3] == [reasoning, call]
    assert captured[1]["input"][3] == {
        "type": "function_call_output",
        "call_id": "call_one",
        "output": "found",
    }
    assert captured[1]["tool_choice"] == {"type": "function", "name": "lookup"}
    assert captured[0]["store"] is False
    assert captured[0]["include"] == ["reasoning.encrypted_content"]
    assert captured[0]["parallel_tool_calls"] is False
    assert captured[0]["tools"][0]["strict"] is False
    assert captured[0]["tools"][0]["parameters"]["required"] == []
    assert first.usage.input_tokens == 8
    assert first.usage.cache_read_input_tokens == 3


@pytest.mark.parametrize(
    "response",
    [
        _response(status="incomplete"),
        httpx.Response(429, text="private error body"),
        _response(_call("lookup", {}), _call("lookup", {}, "call_two")),
        _response(
            {
                "type": "function_call",
                "call_id": "call_one",
                "name": "lookup",
                "arguments": "not json",
            }
        ),
    ],
)
def test_api_failures_do_not_yield_tool_calls(monkeypatch, response):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(ValueError) as error:
            ai.turn(
                ai.ToolTask(
                    messages=[],
                    tools=[_tool()],
                    system="writer",
                    force_tool=None,
                ),
                _model_config(),
                client=client,
            )
    assert "private error body" not in str(error.value)


def test_timeout_is_bounded_and_does_not_expose_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 9
        raise httpx.ReadTimeout("secret server response")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="failed to reach") as error:
            ai.turn(
                ai.ToolTask(
                    messages=[],
                    tools=[],
                    system="",
                    force_tool=None,
                ),
                replace(_model_config(), request_timeout_s=9),
                client=client,
            )
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("review_pass", [True, False])
def test_gpt_generation_retains_grounding_and_fresh_review(monkeypatch, review_pass):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = []
    emitted = _call(
        "emit_document",
        {
            "title": "SSO setup",
            "body": "# SSO setup\nEnable SSO.",
            "statement_ids": ["stm_1"],
            "gaps": [],
        },
    )
    review = _call(
        "record_review",
        {
            "exposure": {"status": "pass", "findings": []},
            "conformance": {
                "status": "pass" if review_pass else "fail",
                "findings": []
                if review_pass
                else [{"where": "body", "problem": "missing steps"}],
            },
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        # Use the harness's actual forced review tool name.
        if isinstance(payload["tool_choice"], dict):
            review["name"] = payload["tool_choice"]["name"]
            return _response(review)
        return _response(emitted)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = _execute(
            "document SSO",
            requested_set="kb",
            requested_type="how-to",
            client=client,
            substrate=_substrate(),
            report_gap=FakeGapReporter(),
            config=_config(),
            doctrine_text="",
            doctrine_note=None,
            catalogue={"kb": ["how-to"]},
            load_texts=lambda *_: ("be clear", "public facts only", "steps"),
        )
    assert isinstance(result, DocumentWritten if review_pass else NothingWritten)
    assert all(turn["model"] == "configured-gpt" for turn in captured)
    assert result.trace["provider"] == "openai"
    assert result.trace["cost_usd"] is None
    reviews = [turn for turn in captured if isinstance(turn["tool_choice"], dict)]
    assert reviews
    assert all(len(turn["input"]) == 1 for turn in reviews)
    assert all(turn["instructions"] != captured[0]["instructions"] for turn in reviews)


def test_configuration_keeps_claude_default_and_requires_gpt_model(monkeypatch):
    monkeypatch.delenv("MYCELIUM_DOCGEN_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_DOCGEN_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    save_model("docgen", claude_model="configured-claude")
    assert DocgenConfig.from_env().model == "configured-claude"
    assert DocgenConfig.from_env().provider == "claude"
    assert DocgenConfig.from_env(provider="openai").model == ""
    assert model_choices()[1]["available"] is False
    assert "AI settings" in model_choices()[1]["reason"]
    with pytest.raises(ValueError, match="provider"):
        resolve_provider("bad-provider")


def test_admission_captures_model_before_worker_wait(monkeypatch, tmp_path):
    save_model("docgen", openai_model="gpt-at-admission")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    conn = docs_store.connect(tmp_path / "drafts.db")
    docs_store.migrate(conn)
    entered, release = threading.Event(), threading.Event()
    observed = []

    def fake_run(prompt, *, config, **kwargs):
        entered.set()
        assert release.wait(5)
        observed.append(config)
        return {"outcome": "nothing_written", "reason": "fixture"}

    monkeypatch.setattr(docgen, "run_docgen", fake_run)
    try:
        run_id = doc_runs.start_run(
            prompt="SSO",
            guideline_set=None,
            document_type=None,
            created_by=None,
            conn=conn,
            provider="openai",
        )
        assert entered.wait(5)
        save_model("docgen", openai_model="gpt-after-admission")
        release.set()
        doc_runs.wait_all()
        row = docs_store.serialize_run(docs_store.get_run(conn, run_id))
        assert row["model"] == observed[0].model == "gpt-at-admission"
        assert row["provider"] == observed[0].provider == "openai"
    finally:
        release.set()
        doc_runs.wait_all()
        conn.close()


@pytest.mark.parametrize(
    "role,expected",
    [("reader", 403), ("drafter", 403), ("writer", 200), ("admin", 200)],
)
def test_http_selection_and_real_role(monkeypatch, tmp_path, role, expected):
    from fastapi.testclient import TestClient

    from mycelium import auth, guidelines, prompt_store, server
    from mycelium.http import AuthMiddleware, app

    principal = auth.Principal(id="fixture", name="Fixture", role=role, type="human")

    async def resolve(*_):
        return principal

    monkeypatch.setattr(AuthMiddleware, "_resolve", resolve)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-claude-key")
    conn = docs_store.connect(tmp_path / "drafts.db")
    docs_store.migrate(conn)
    prompts = prompt_store.connect(":memory:")
    prompt_store.migrate(prompts)
    prompt_store.save(prompts, type=guidelines.TYPE, name="public/how-to", text="steps")
    monkeypatch.setattr(server, "_drafts_db", lambda: conn)
    prompt_store.use_connection(prompts)
    save_model("docgen", openai_model="configured-gpt")
    monkeypatch.setattr(prompt_store, "connection", lambda: prompts)
    monkeypatch.setattr(prompt_store, "is_configured", lambda: True)
    monkeypatch.setattr(
        doc_runs,
        "RUNNER",
        lambda *_, **__: {"outcome": "nothing_written", "reason": "fixture"},
    )
    try:
        client = TestClient(app)
        options = client.get("/api/documentation/options")
        assert options.status_code == 200
        assert options.json()["can_generate"] is (expected == 200)
        assert options.json()["models"][1]["model"] == "configured-gpt"
        assert options.json()["guideline_sets"] == {"public": ["how-to"]}
        assert "test-key" not in options.text
        for path, detail in (
            ("runs", "documentation run not found: missing"),
            ("documents", "generated document not found: missing"),
        ):
            missing = client.get(f"/api/documentation/{path}/missing")
            assert missing.status_code == 404
            assert missing.json() == {"detail": detail}
        response = client.post(
            "/api/documentation/runs", json={"prompt": "SSO", "provider": "openai"}
        )
        assert response.status_code == expected
        doc_runs.wait_all()
        if expected == 200:
            run_id = response.json()["id"]
            detail = client.get(f"/api/documentation/runs/{run_id}").json()
            assert detail["model"] == "configured-gpt"
            assert detail["provider"] == "openai"
            assert detail["created_by"] == "fixture"
            assert (
                client.get("/api/documentation/runs").json()["runs"][0]["id"] == run_id
            )
            assert (
                client.post(
                    "/api/documentation/runs",
                    json={"prompt": "SSO", "provider": "unknown"},
                ).status_code
                == 422
            )
        else:
            assert docs_store.list_runs(conn) == []
    finally:
        doc_runs.wait_all()
        conn.close()
        prompts.close()


def test_missing_gpt_configuration_refuses_before_creating_a_run(monkeypatch, tmp_path):
    conn = docs_store.connect(tmp_path / "drafts.db")
    docs_store.migrate(conn)
    monkeypatch.delenv("MYCELIUM_DOCGEN_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        with pytest.raises(ValueError, match="AI settings"):
            doc_runs.start_run(
                prompt="SSO",
                guideline_set=None,
                document_type=None,
                created_by=None,
                conn=conn,
                provider="openai",
            )
        save_model("docgen", openai_model="configured-gpt")
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            doc_runs.start_run(
                prompt="SSO",
                guideline_set=None,
                document_type=None,
                created_by=None,
                conn=conn,
                provider="openai",
            )
        assert docs_store.list_runs(conn) == []
    finally:
        conn.close()


def test_claude_token_credentials_remain_selectable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-token")
    assert model_choices()[0]["available"] is True


def test_gpt_matching_resolution_and_reads_use_same_transport(monkeypatch):
    from mycelium.docgen.schema import ExistingDocument
    from mycelium.docgen.tools import EMIT_TOOL, MATCH_TOOL, RESOLVE_TOOL, REVIEW_TOOL

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    requests = []
    read = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal read
        payload = json.loads(request.content)
        requests.append(payload)
        choice = payload["tool_choice"]
        name = choice["name"] if isinstance(choice, dict) else None
        if name == MATCH_TOOL:
            return _response(_call(name, {"document_id": None, "reason": "new topic"}))
        if name == RESOLVE_TOOL:
            return _response(
                _call(
                    name,
                    {
                        "guideline_set": "kb",
                        "document_type": "how-to",
                        "reason": "requested instructions",
                    },
                )
            )
        if name == REVIEW_TOOL:
            return _response(
                _call(
                    name,
                    {
                        "exposure": {"status": "pass", "findings": []},
                        "conformance": {"status": "pass", "findings": []},
                    },
                )
            )
        if not read:
            read = True
            return _response(_call("get_statements", {"ids": ["stm_1"]}, "read_call"))
        return _response(
            _call(
                EMIT_TOOL,
                {
                    "title": "New topic",
                    "body": "# New topic\nEnable SSO.",
                    "statement_ids": ["stm_1"],
                    "gaps": [],
                },
            )
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = _execute(
            "document SSO",
            requested_set=None,
            requested_type=None,
            client=client,
            substrate=_substrate(),
            report_gap=FakeGapReporter(),
            config=_config(),
            doctrine_text="",
            doctrine_note=None,
            catalogue={"kb": ["how-to"]},
            load_texts=lambda *_: ("clear", "public", "steps"),
            existing_documents=(
                ExistingDocument(
                    id="doc_other",
                    slug="other",
                    title="Other",
                    guideline_set="kb",
                    document_type="how-to",
                    body_digest="old",
                ),
            ),
        )
    assert isinstance(result, DocumentWritten)
    assert [request["model"] for request in requests] == ["configured-gpt"] * 5
    assert requests[0]["tool_choice"]["name"] == MATCH_TOOL
    assert requests[1]["tool_choice"]["name"] == RESOLVE_TOOL
    assert requests[3]["input"][-1]["type"] == "function_call_output"
    assert requests[3]["input"][-1]["call_id"] == "read_call"
    assert len(requests[4]["input"]) == 1


def test_gpt_cannot_emit_unretrieved_knowledge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            _call(
                "emit_document",
                {
                    "title": "SSO",
                    "body": "SSO exists",
                    "statement_ids": ["stm_invented"],
                    "gaps": [],
                },
            )
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = _execute(
            "document SSO",
            requested_set="kb",
            requested_type="how-to",
            client=client,
            substrate=_substrate(),
            report_gap=FakeGapReporter(),
            config=_config(),
            doctrine_text="",
            doctrine_note=None,
            catalogue={"kb": ["how-to"]},
            load_texts=lambda *_: ("clear", "public", "steps"),
        )
    assert isinstance(result, NothingWritten)
    assert result.trace["refused_emits"]
    assert not result.trace["reviews"]


def test_migration_preserves_unknown_historical_model(tmp_path):
    conn = docs_store.connect(tmp_path / "old.db")
    conn.executescript(
        docs_store.DOCUMENTATION_RUNS_SCHEMA.replace(
            ",\n    provider      TEXT,\n    model         TEXT", ""
        )
    )
    conn.execute(
        "INSERT INTO documentation_runs(id,prompt,created_at) VALUES ('old', 'SSO', '2026-01-01')"
    )
    conn.commit()
    docs_store.migrate(conn)
    row = docs_store.serialize_run(docs_store.get_run(conn, "old"))
    assert row["provider"] is None
    assert row["model"] is None
    conn.close()


def test_broken_claude_profile_does_not_hide_configured_gpt(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_PROFILE", " invalid-profile")
    save_model("docgen", openai_model="configured-gpt")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    choices = model_choices()
    assert choices[0]["available"] is False
    assert choices[1]["available"] is True
    assert "invalid-profile" not in choices[0]["reason"]


def test_provider_failure_reaches_run_result_without_api_body(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, text="private provider error")
        )
    ) as client:
        result = _execute(
            "document SSO",
            requested_set="kb",
            requested_type="how-to",
            client=client,
            substrate=_substrate(),
            report_gap=FakeGapReporter(),
            config=_config(),
            doctrine_text="",
            doctrine_note=None,
            catalogue={"kb": ["how-to"]},
            load_texts=lambda *_: ("clear", "public", "steps"),
        )
    assert isinstance(result, NothingWritten)
    assert "OPENAI_API_KEY" in result.reason
    assert "401" in result.reason
    assert "private provider error" not in result.reason
