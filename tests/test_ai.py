"""Provider contracts exercised through isolated real SDK/HTTP transports."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from mycelium import ai

_OBJECT = TypeAdapter(dict[str, JsonValue])
_TOOLS: list[dict[str, object]] = [
    {
        "name": "read",
        "description": "Read a record",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    }
]


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


@pytest.fixture(autouse=True)
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-claude")


def _config(provider: ai.Provider) -> ai.ModelConfig:
    return ai.ModelConfig(provider, "configured-model", 1000, 10)


def _task(
    messages: list[dict[str, object]] | None = None,
    *,
    parallel: bool = False,
    force: str | None = None,
) -> ai.ToolTask:
    return ai.ToolTask(
        "Task instructions",
        messages or [{"role": "user", "content": "Question"}],
        _TOOLS,
        force_tool=force,
        parallel_tools=parallel,
    )


def _openai_call(identity: str) -> dict[str, JsonValue]:
    return {
        "type": "function_call",
        "call_id": identity,
        "name": "read",
        "arguments": '{"id":"record"}',
    }


def _claude_call(identity: str) -> dict[str, JsonValue]:
    return {
        "type": "tool_use",
        "id": identity,
        "name": "read",
        "input": {"id": "record"},
    }


def _envelope(
    provider: ai.Provider,
    blocks: list[dict[str, JsonValue]],
    *,
    stop: str | None = None,
) -> dict[str, JsonValue]:
    if provider == "openai":
        return {
            "status": stop or "completed",
            "output": blocks,
            "usage": {
                "input_tokens": 11,
                "output_tokens": 5,
                "input_tokens_details": {"cached_tokens": 3},
            },
        }
    return {
        "id": "msg-test",
        "type": "message",
        "role": "assistant",
        "model": "configured-model",
        "content": blocks,
        "stop_reason": stop or "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 8, "output_tokens": 5, "cache_read_input_tokens": 3},
    }


def _reply(request: httpx.Request, body: dict[str, JsonValue]) -> httpx.Response:
    """Answer as the API does: a Claude turn streams, so it gets events."""
    if body.get("type") != "message" or not _OBJECT.validate_json(request.content).get(
        "stream"
    ):
        return httpx.Response(200, json=body)
    content = body["content"]
    assert isinstance(content, list)
    events: list[dict[str, JsonValue]] = [
        {
            "type": "message_start",
            "message": {**body, "content": [], "stop_reason": None},
        },
        *(
            {"type": "content_block_start", "index": index, "content_block": block}
            for index, block in enumerate(content)
        ),
        {
            "type": "message_delta",
            "delta": {"stop_reason": body["stop_reason"], "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    stream = "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    )
    return httpx.Response(
        200, text=stream, headers={"content-type": "text/event-stream"}
    )


def _structured_envelope(provider: ai.Provider) -> dict[str, JsonValue]:
    if provider == "openai":
        return _envelope(
            provider,
            [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"answer":"yes"}'}],
                }
            ],
        )
    return _envelope(
        provider,
        [{"type": "text", "text": '{"answer":"yes"}'}],
        stop="end_turn",
    )


def test_openai_preserves_reasoning_parallel_calls_and_result_order() -> None:
    sent: list[dict[str, JsonValue]] = []
    output = [
        {
            "type": "reasoning",
            "id": "reason-1",
            "encrypted_content": "opaque",
            "summary": [],
        },
        _openai_call("call-1"),
        _openai_call("call-2"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(_OBJECT.validate_json(request.content))
        return httpx.Response(200, json=_envelope("openai", output))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ai.turn(_task(parallel=True), _config("openai"), client=client)
        assert [
            block.id for block in result.content if isinstance(block, ai.ToolUse)
        ] == ["call-1", "call-2"]
        ai.turn(
            _task(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Question",
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    },
                    {"role": "assistant", "content": result.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-1",
                                "content": "first",
                                "is_error": False,
                            },
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-2",
                                "content": "second",
                                "is_error": False,
                            },
                        ],
                    },
                ],
                parallel=True,
            ),
            _config("openai"),
            client=client,
        )
        assert not client.is_closed
    assert sent[1]["input"] == [
        {"role": "user", "content": "Question"},
        *output,
        {"type": "function_call_output", "call_id": "call-1", "output": "first"},
        {"type": "function_call_output", "call_id": "call-2", "output": "second"},
    ]
    assert sent[0]["store"] is False
    assert sent[0]["parallel_tool_calls"] is True
    assert sent[0]["include"] == ["reasoning.encrypted_content"]
    assert result.usage.input_tokens == 11 - 3
    assert result.usage.cache_read_input_tokens == 3


def test_claude_signed_history_cache_and_forced_terminal() -> None:
    sent: list[dict[str, JsonValue]] = []
    thinking: dict[str, JsonValue] = {
        "type": "thinking",
        "thinking": "private",
        "signature": "signed",
    }
    output = [thinking, _claude_call("call-1")]

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(_OBJECT.validate_json(request.content))
        return _reply(request, _envelope("claude", output))

    config = replace(_config("claude"), thinking=True, cache=True)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ai.turn(_task(parallel=True), config, client=client)
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": result.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": "read result",
                        "is_error": False,
                    }
                ],
            },
        ]
        ai.turn(_task(messages), config, client=client)
        ai.turn(_task(messages, force="read"), config, client=client)
        assert not client.is_closed
    assert all(body["stream"] is True for body in sent)
    assert sent[0]["thinking"] == {"type": "adaptive"}
    assert sent[0]["tool_choice"] == {
        "type": "auto",
        "disable_parallel_tool_use": False,
    }
    assert sent[2]["tool_choice"] == {
        "type": "tool",
        "name": "read",
        "disable_parallel_tool_use": True,
    }
    # Forcing keeps thinking and the signed history, so the forced turn reads
    # the same cached prefix as the turns before it.
    assert sent[2]["thinking"] == {"type": "adaptive"}
    regular = sent[1]["messages"]
    forced = sent[2]["messages"]
    assert isinstance(regular, list) and isinstance(regular[1], dict)
    assert isinstance(forced, list) and isinstance(forced[1], dict)
    assert regular[1]["content"] == output
    assert forced[1]["content"] == output
    assert sent[0]["system"] == [
        {
            "type": "text",
            "text": "Task instructions",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert isinstance(regular[-1], dict)
    assert regular[-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call-1",
            "content": "read result",
            "is_error": False,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    original = messages[-1]["content"]
    assert isinstance(original, list) and "cache_control" not in original[0]


def test_claude_learns_that_a_model_refuses_a_forced_tool(monkeypatch, caplog) -> None:
    from mycelium.ai import claude

    monkeypatch.setattr(claude, "_refused_forcing", set())
    sent: list[dict[str, JsonValue]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _OBJECT.validate_json(request.content)
        sent.append(body)
        choice = body["tool_choice"]
        if isinstance(choice, dict) and choice["type"] == "tool":
            message = (
                'tool_choice: type "tool" and "any" are not supported for this model.'
            )
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": message},
                },
            )
        return _reply(request, _envelope("claude", [_claude_call("call-1")]))

    config = replace(_config("claude"), model="claude-newer-model")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ai.turn(_task(force="read"), config, client=client)
        ai.turn(_task(force="read"), config, client=client)

    learnt = [r for r in caplog.records if r.name == "mycelium.ai.claude"]
    assert [(r.levelname, r.args) for r in learnt] == [
        ("WARNING", ("claude-newer-model",))
    ]
    assert [request["tool_choice"] for request in sent] == [
        {"type": "tool", "name": "read", "disable_parallel_tool_use": True},
        {"type": "auto", "disable_parallel_tool_use": True},
        {"type": "auto", "disable_parallel_tool_use": True},
    ]


def test_claude_learns_that_a_model_refuses_thinking_with_a_forced_tool(
    monkeypatch, caplog
) -> None:
    from mycelium.ai import claude

    monkeypatch.setattr(claude, "_refused_thinking_when_forced", set())
    sent: list[dict[str, JsonValue]] = []
    output = [
        {"type": "thinking", "thinking": "private", "signature": "signed"},
        _claude_call("call-1"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = _OBJECT.validate_json(request.content)
        sent.append(body)
        if "thinking" in body:
            message = "Thinking may not be enabled when tool_choice forces tool use."
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": message},
                },
            )
        return _reply(request, _envelope("claude", [_claude_call("call-2")]))

    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": output},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "x"}
            ],
        },
    ]
    config = replace(_config("claude"), model="claude-older-model", thinking=True)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ai.turn(_task(messages, force="read"), config, client=client)
        ai.turn(_task(messages, force="read"), config, client=client)

    assert ["thinking" in request for request in sent] == [True, False, False]
    history = sent[-1]["messages"]
    assert isinstance(history, list) and isinstance(history[1], dict)
    assert history[1]["content"] == [_claude_call("call-1")]
    learnt = [r for r in caplog.records if r.name == "mycelium.ai.claude"]
    assert [r.args for r in learnt] == [("claude-older-model",)]


def test_claude_keeps_the_finished_part_of_a_tool_call_cut_off_at_max_tokens() -> None:
    cut = {
        "type": "tool_use",
        "id": "call-1",
        "name": "read",
        "input": {"id": "record", "items": [{"n": 1}, {"n": 2}, {"n": 3, "te": ""}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _reply(request, _envelope("claude", [cut], stop="max_tokens"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ai.IncompleteTurn) as caught:
            ai.turn(_task(), _config("claude"), client=client)

    assert caught.value.usage.input_tokens == 8
    truncated = caught.value.truncated
    assert truncated is not None and truncated.id == "call-1"
    # The last array was still being written: its last item may be partial.
    assert truncated.input == {"id": "record", "items": [{"n": 1}, {"n": 2}]}


def test_claude_turn_stops_at_its_deadline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _reply(request, _envelope("claude", [_claude_call("call-1")]))

    task = replace(_task(), deadline=0.0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ai.IncompleteTurn, match="deadline") as caught:
            ai.turn(task, _config("claude"), client=client)

    assert caught.value.usage.input_tokens == 8


def test_claude_asks_for_a_required_tool_on_a_model_that_cannot_be_forced() -> None:
    sent: list[dict[str, JsonValue]] = []
    thinking: dict[str, JsonValue] = {
        "type": "thinking",
        "thinking": "",
        "signature": "signed",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(_OBJECT.validate_json(request.content))
        return _reply(request, _envelope("claude", [thinking, _claude_call("call-1")]))

    config = replace(
        _config("claude"), model="claude-sonnet-5-5", thinking=True, cache=True
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = ai.turn(_task(), config, client=client)
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": first.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": "read result",
                        "is_error": False,
                    }
                ],
            },
        ]
        ai.turn(_task(messages, force="read"), config, client=client)

    request = sent[1]
    assert request["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert request["thinking"] == {"type": "adaptive"}
    history = request["messages"]
    assert isinstance(history, list) and isinstance(history[1], dict)
    # The signed thinking stays: these models reject an edited history.
    assert history[1]["content"] == [thinking, _claude_call("call-1")]
    assert isinstance(history[-1], dict)
    assert history[-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call-1",
            "content": "read result",
            "is_error": False,
        },
        {
            "type": "text",
            "text": "Respond now by calling the `read` tool exactly once.",
            "cache_control": {"type": "ephemeral"},
        },
    ]


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_structured_output_uses_schema_and_keeps_borrowed_client_open(
    provider: ai.Provider,
) -> None:
    sent: list[dict[str, JsonValue]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(_OBJECT.validate_json(request.content))
        return httpx.Response(200, json=_structured_envelope(provider))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ai.structured(
            ai.StructuredTask("Judge", "Evidence", Result),
            _config(provider),
            client=client,
        )
        assert not client.is_closed
    assert result == Result(answer="yes")
    assert sent[0]["model"] == "configured-model"
    assert "tools" not in sent[0]
    assert "output_config" in sent[0] if provider == "claude" else "text" in sent[0]


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_serial_task_rejects_parallel_output(provider: ai.Provider) -> None:
    call = _claude_call if provider == "claude" else _openai_call
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: _reply(
                request, _envelope(provider, [call("one"), call("two")])
            )
        )
    ) as client:
        with pytest.raises(ai.ModelError, match="parallel"):
            ai.turn(_task(), _config(provider), client=client)


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_forced_task_rejects_missing_call(provider: ai.Provider) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: _reply(
                request,
                _envelope(
                    provider,
                    [],
                    stop="end_turn" if provider == "claude" else "completed",
                ),
            )
        )
    ) as client:
        with pytest.raises(ai.ModelError, match="required tool"):
            ai.turn(_task(force="read"), _config(provider), client=client)


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_truncation_never_returns_a_structured_result(provider: ai.Provider) -> None:
    envelope = _structured_envelope(provider)
    envelope["stop_reason" if provider == "claude" else "status"] = (
        "max_tokens" if provider == "claude" else "incomplete"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope))
    ) as client:
        with pytest.raises(ai.ModelError):
            ai.structured(
                ai.StructuredTask("Judge", "Evidence", Result),
                _config(provider),
                client=client,
            )


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_errors_do_not_echo_provider_bodies(provider: ai.Provider) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                401, json={"error": {"message": "secret evidence"}}
            )
        )
    ) as client:
        with pytest.raises(ai.ModelError) as caught:
            ai.structured(
                ai.StructuredTask("Judge", "Evidence", Result),
                _config(provider),
                client=client,
            )
    assert "secret evidence" not in str(caught.value)
    assert "401" in str(caught.value)


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_cannot_reuse_another_providers_history(provider: ai.Provider) -> None:
    other: ai.Provider = "openai" if provider == "claude" else "claude"
    messages: list[dict[str, object]] = [
        {
            "role": "assistant",
            "content": [ai.ProviderHistory(provider=other, output=[])],
        }
    ]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: pytest.fail("history mismatch must not call provider")
        )
    ) as client:
        with pytest.raises(ai.ModelError, match="change providers"):
            ai.turn(_task(messages), _config(provider), client=client)


def test_openai_retries_only_within_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.ai import openai

    waits: list[float] = []
    monkeypatch.setattr(openai.time, "sleep", waits.append)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429 if len(calls) == 1 else 200, json=_structured_envelope("openai")
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ai.structured(
            ai.StructuredTask("Judge", "Evidence", Result),
            replace(_config("openai"), max_retries=1),
            client=client,
        )
    assert len(calls) == 2
    assert waits == [0.5]


@pytest.mark.parametrize("provider", ["claude", "openai"])
@pytest.mark.parametrize("feature", ["ask", "docgen"])
def test_existing_terminal_schemas_cross_the_shared_boundary(
    provider: ai.Provider, feature: str
) -> None:
    from mycelium.ask.tools import build_tools as ask_tools
    from mycelium.docgen.tools import build_tools as docgen_tools

    task = replace(
        _task(), tools=ask_tools([]) if feature == "ask" else docgen_tools([])
    )
    sent: list[dict[str, JsonValue]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(_OBJECT.validate_json(request.content))
        return _reply(
            request,
            _envelope(
                provider, [], stop="end_turn" if provider == "claude" else "completed"
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ai.turn(task, _config(provider), client=client)
    definitions = sent[0]["tools"]
    assert isinstance(definitions, list) and definitions
    assert all(isinstance(tool, dict) for tool in definitions)
    assert all(
        tool.get("strict") is (provider == "claude")
        for tool in definitions
        if isinstance(tool, dict)
    )


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_malformed_structured_output_does_not_echo_evidence(
    provider: ai.Provider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocks: list[dict[str, JsonValue]] = (
        [{"type": "text", "text": '{"secret evidence":true}'}]
        if provider == "claude"
        else [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"secret evidence":true}'}
                ],
            }
        ]
    )
    envelope = _envelope(
        provider, blocks, stop="end_turn" if provider == "claude" else "completed"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope))
    ) as client:
        with pytest.raises(ai.ModelError) as caught:
            ai.structured(
                ai.StructuredTask("Judge", "Evidence", Result),
                _config(provider),
                client=client,
            )
    assert "secret evidence" not in str(caught.value)
    assert "secret evidence" not in caplog.text
    diagnostic = next(
        record for record in caplog.records if record.name == "mycelium.ai"
    )
    assert (
        f"provider={provider} operation=structured category=validation"
        in diagnostic.message
    )
    assert diagnostic.exc_info is None


@pytest.mark.parametrize(
    "provider,effort",
    [
        ("claude", None),
        ("claude", "low"),
        ("claude", "xhigh"),
        ("openai", None),
        ("openai", "none"),
        ("openai", "minimal"),
        ("openai", "max"),
    ],
)
@pytest.mark.parametrize("structured", [False, True])
def test_native_effort_reaches_both_transports(
    provider: ai.Provider, effort: ai.ReasoningEffort | None, structured: bool
) -> None:
    sent: list[dict[str, JsonValue]] = []
    call = _claude_call if provider == "claude" else _openai_call

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(_OBJECT.validate_json(request.content))
        return _reply(
            request,
            _structured_envelope(provider)
            if structured
            else _envelope(provider, [call("one")]),
        )

    config = replace(_config(provider), reasoning_effort=effort)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if structured:
            assert ai.structured(
                ai.StructuredTask("Judge", "Evidence", Result), config, client=client
            ) == Result(answer="yes")
        else:
            ai.turn(_task(force="read"), config, client=client)
    key = "output_config" if provider == "claude" else "reasoning"
    options = sent[0].get(key, {})
    assert isinstance(options, dict)
    if effort is None:
        assert "effort" not in options
    else:
        assert options["effort"] == effort
    if structured and provider == "claude":
        assert isinstance(options["format"], dict)
        assert options["format"]["type"] == "json_schema"


def test_a_truncated_claude_turn_names_its_stop_reason() -> None:
    envelope = _envelope("claude", [], stop="max_tokens")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: _reply(request, envelope))
    ) as client:
        with pytest.raises(ai.IncompleteTurn, match="stop_reason=max_tokens") as raised:
            ai.turn(_task(), _config("claude"), client=client)
    assert raised.value.usage.output_tokens == 5


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_every_turn_is_metered_with_its_attribution(provider: ai.Provider) -> None:
    calls: list[ai.usage.Call] = []
    ai.usage.install(calls.append)
    envelope = _envelope(provider, [])
    config = replace(
        _config(provider),
        model="claude-opus-5-5" if provider == "claude" else "gpt-5.4",
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: _reply(request, envelope))
    ) as client:
        with ai.usage.attributed("docgen", run_id="drn_1"):
            ai.turn(_task(), config, client=client)
        ai.turn(_task(), config, client=client)
    first, second = calls
    assert (first.action, first.run_id, first.ok) == ("docgen", "drn_1", True)
    assert first.usage.cache_read_input_tokens == 3
    assert first.cost_usd is not None and first.cost_usd > 0
    assert (second.action, second.run_id) == ("other", None)


@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_a_failed_turn_is_metered_with_the_tokens_it_used(
    provider: ai.Provider,
) -> None:
    calls: list[ai.usage.Call] = []
    ai.usage.install(calls.append)
    envelope = _envelope(
        provider, [], stop="max_tokens" if provider == "claude" else "incomplete"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: _reply(request, envelope))
    ) as client:
        with pytest.raises(ai.IncompleteTurn) as raised:
            ai.turn(_task(), _config(provider), client=client)
    assert raised.value.usage.output_tokens == 5
    assert [(call.ok, call.usage.output_tokens) for call in calls] == [(False, 5)]
    assert calls[0].cost_usd is None  # an unpriced model keeps its tokens only


def test_a_recorder_failure_never_fails_the_call() -> None:
    def broken(_: ai.usage.Call) -> None:
        raise RuntimeError("disk full")

    ai.usage.install(broken)
    envelope = _envelope("openai", [])
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: _reply(request, envelope))
    ) as client:
        assert ai.turn(_task(), _config("openai"), client=client).usage.output_tokens


def test_a_gated_action_is_refused_before_the_provider_is_called() -> None:
    sent: list[httpx.Request] = []
    calls: list[ai.usage.Call] = []
    ai.usage.install(
        calls.append, lambda action: "Paused" if action == "draft_review" else None
    )
    with httpx.Client(transport=httpx.MockTransport(sent.append)) as client:
        with ai.usage.attributed("draft_review"), pytest.raises(ai.usage.Paused):
            ai.structured(
                ai.StructuredTask("Judge", "Evidence", Result),
                _config("openai"),
                client=client,
            )
    assert sent == [] and calls == []
