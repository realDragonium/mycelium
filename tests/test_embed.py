from __future__ import annotations

import json

import httpx
import ollama
import pytest

from mycelium import embed as embed_module
from mycelium.ai import usage
from mycelium.embed import embed_many as real_embed_many


def _configure_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    embed_module.reset()


def _response(inputs: list[str], *, prompt_tokens: int = 1) -> httpx.Response:
    data = [
        {"index": index, "embedding": [float(int(text))] * 768}
        for index, text in enumerate(inputs)
    ]
    return httpx.Response(
        200,
        json={"data": list(reversed(data)), "usage": {"prompt_tokens": prompt_tokens}},
    )


def test_default_settings_are_legacy_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYCELIUM_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed_module.reset()

    assert embed_module.settings() == embed_module.Settings(
        provider="ollama", model="nomic-embed-text", timeout_s=30.0
    )
    assert embed_module.identity() == "ollama/nomic-embed-text/768"


def test_openai_has_its_own_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_openai(monkeypatch)

    assert embed_module.settings().model == "text-embedding-3-small"
    assert embed_module.identity() == "openai/text-embedding-3-small/768"


def test_thresholds_follow_the_configured_embedder(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("MYCELIUM_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed_module.reset()
    nomic = embed_module.thresholds()
    assert nomic.near_duplicate == 0.85

    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", "openai")
    embed_module.reset()
    assert embed_module.thresholds().near_duplicate < nomic.near_duplicate

    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", "ollama")
    monkeypatch.setenv("MYCELIUM_EMBED_MODEL", "other-embedder")
    embed_module.reset()
    caplog.clear()
    assert embed_module.thresholds() == nomic
    assert embed_module.thresholds() == nomic
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "other-embedder" in warnings[0].message


def test_ollama_honours_legacy_model_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", "ollama")
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.setenv("EMBED_MODEL", "catalog-embedder")
    embed_module.reset()

    assert embed_module.settings().model == "catalog-embedder"


def test_invalid_provider_names_the_allowed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", "other")
    embed_module.reset()

    with pytest.raises(ValueError, match="ollama, openai"):
        embed_module.settings()


def test_empty_batch_does_not_read_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", "other")
    embed_module.reset()

    assert real_embed_many([]) == []


def test_openai_batches_and_restores_response_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_openai(monkeypatch)
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["dimensions"] == 768
        assert payload["model"] == "text-embedding-3-small"
        assert request.headers["authorization"] == "Bearer test-key"
        return _response(payload["input"])

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))
    texts = [str(index) for index in range(250)]

    vectors = real_embed_many(texts)

    assert [len(request["input"]) for request in requests] == [100, 100, 50]
    assert [vector[0] for vector in vectors] == [float(index) for index in range(250)]


def test_openai_retries_429_after_the_requested_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_openai(monkeypatch)
    slept: list[float] = []
    monkeypatch.setattr(embed_module, "_sleep", slept.append)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429, json={"error": "slow down"}, headers={"retry-after": "3"}
            )
        payload = json.loads(request.content)
        return _response(payload["input"])

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))

    assert real_embed_many(["4"])[0][0] == 4.0
    assert attempts == 2
    assert slept == [3.0]


def test_ollama_retries_transient_response_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYCELIUM_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed_module.reset()
    monkeypatch.setattr(embed_module, "_sleep", lambda seconds: None)
    attempts = 0

    class FakeClient:
        def embeddings(self, *, model: str, prompt: str):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ollama.ResponseError("try later", 429)
            return ollama.EmbeddingsResponse(embedding=[1.0] * 768)

    monkeypatch.setattr(embed_module, "_get_client", lambda: FakeClient())

    assert real_embed_many(["workspace search"])[0][0] == 1.0
    assert attempts == 2


def test_openai_does_not_retry_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_openai(monkeypatch)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "invalid key"})

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(embed_module.EmbeddingError, match="HTTP 401"):
        real_embed_many(["1"])
    assert attempts == 1


def test_openai_requires_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_openai(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(embed_module.EmbeddingError, match="OPENAI_API_KEY"):
        real_embed_many(["1"])


def test_openai_embedding_usage_is_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_openai(monkeypatch)
    calls: list[usage.Call] = []
    usage.install(calls.append)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return _response(payload["input"], prompt_tokens=100)

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        real_embed_many(["2"])
    finally:
        usage.install(None)

    assert len(calls) == 1
    call = calls[0]
    assert (call.action, call.provider, call.model) == (
        "embedding",
        "openai",
        "text-embedding-3-small",
    )
    assert call.usage.input_tokens == 100
    assert call.cost_usd == 0.000002
    assert call.ok is True


def test_embed_caches_success_and_returns_fresh_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_openai(monkeypatch)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        payload = json.loads(request.content)
        return _response(payload["input"])

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))

    first = embed_module.embed("3")
    first[0] = -1.0
    second = embed_module.embed("3")

    assert attempts == 1
    assert second[0] == 3.0


def test_embed_does_not_cache_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_openai(monkeypatch)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(401, json={"error": "invalid key"})
        payload = json.loads(request.content)
        return _response(payload["input"])

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(embed_module.EmbeddingError):
        embed_module.embed("5")
    assert embed_module.embed("5")[0] == 5.0
    assert attempts == 2


def test_wrong_dimension_is_an_embedding_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_openai(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [1.0, 2.0]}],
                "usage": {"prompt_tokens": 1},
            },
        )

    embed_module._openai_client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(
        embed_module.EmbeddingError,
        match="text-embedding-3-small returned 2 dimensions",
    ):
        real_embed_many(["1"])
