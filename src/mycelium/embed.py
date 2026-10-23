"""Ollama and OpenAI embeddings configured by MYCELIUM_EMBED_* environment variables.

Ollama also reads OLLAMA_URL and the legacy EMBED_MODEL. OpenAI reads
OPENAI_API_KEY for each request. EMBED_TIMEOUT_S bounds requests to either
provider.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Protocol, cast

import httpx
import ollama
from pydantic import BaseModel, ConfigDict, ValidationError

from . import vector
from .ai import usage
from .ai.types import ModelConfig, Usage

Provider = Literal["ollama", "openai"]


_LOG = logging.getLogger(__name__)


class _Closable(Protocol):
    def close(self) -> None: ...


LEGACY_IDENTITY = "ollama/nomic-embed-text/768"
MAX_RETRIES = 2
OPENAI_BATCH = 100
QUERY_CACHE_SIZE = 2048
#: A longer rate-limit wait is a failure: callers fall back rather than stall.
MAX_RETRY_AFTER_S = 20.0

# The provider clients default to no useful bound for this workload, and every
# embed occupies a worker thread for its whole duration. An unresponsive
# provider would therefore park threads permanently, exhausting the pool with
# no way back — a wedge the health check can't see, because the health check
# deliberately needs no thread. Bound it: embedding short text should finish
# well below this ceiling, and failing is recoverable in a way that hanging is
# not.
DEFAULT_TIMEOUT_S = 30.0


class EmbeddingError(RuntimeError):
    """An embedding provider could not return a usable vector."""


@dataclass(frozen=True)
class Settings:
    provider: Provider
    model: str
    timeout_s: float


@dataclass(frozen=True)
class Thresholds:
    near_duplicate: float
    statement_duplicate: float
    fact_exists: float
    fact_near: float
    name_match: float
    endpoint_match: float
    entity_search: float
    entity_duplicate: float
    subquery_dedup: float


_DEFAULT_MODELS: dict[Provider, str] = {
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
}
_THRESHOLDS: dict[tuple[Provider, str], Thresholds] = {
    ("ollama", "nomic-embed-text"): Thresholds(
        near_duplicate=0.85,
        statement_duplicate=0.92,
        fact_exists=0.85,
        fact_near=0.6,
        name_match=0.5,
        endpoint_match=0.5,
        entity_search=0.3,
        entity_duplicate=0.75,
        subquery_dedup=0.95,
    ),
    # Measured against nomic on a production copy: floors keep the same share
    # of hits and statement duplicate thresholds flag a similar number of
    # pairs. Names separate less well, so entity_duplicate trades a longer
    # review list for catching most known aliases.
    ("openai", "text-embedding-3-small"): Thresholds(
        near_duplicate=0.79,
        statement_duplicate=0.88,
        fact_exists=0.79,
        fact_near=0.45,
        name_match=0.35,
        endpoint_match=0.35,
        entity_search=0.20,
        entity_duplicate=0.66,
        subquery_dedup=0.93,
    ),
}


class _OpenAIEmbedding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int
    embedding: list[float]


class _OpenAIUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int


class _OpenAIResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: list[_OpenAIEmbedding]
    usage: _OpenAIUsage


_client_lock = threading.Lock()
_client: ollama.Client | None = None
_openai_client: httpx.Client | None = None
_sleep = time.sleep
_warned_threshold_models: set[tuple[Provider, str]] = set()


@lru_cache(maxsize=1)
def settings() -> Settings:
    raw_provider = os.environ.get("MYCELIUM_EMBED_PROVIDER", "ollama").strip()
    if raw_provider not in ("ollama", "openai"):
        raise ValueError("MYCELIUM_EMBED_PROVIDER must be one of: ollama, openai")
    provider = cast(Provider, raw_provider)
    configured_model = os.environ.get("MYCELIUM_EMBED_MODEL")
    if configured_model is not None:
        model = configured_model.strip()
    elif provider == "ollama":
        model = os.environ.get("EMBED_MODEL", "nomic-embed-text").strip()
    else:
        model = "text-embedding-3-small"
    if not model:
        raise ValueError("MYCELIUM_EMBED_MODEL must not be empty")
    timeout_s = float(os.environ.get("EMBED_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    if timeout_s <= 0:
        raise ValueError("EMBED_TIMEOUT_S must be greater than zero")
    return Settings(provider=provider, model=model, timeout_s=timeout_s)


def identity() -> str:
    configured = settings()
    return f"{configured.provider}/{configured.model}/{vector.DIM}"


def thresholds() -> Thresholds:
    configured = settings()
    key = (configured.provider, configured.model)
    selected = _THRESHOLDS.get(key)
    if selected is not None:
        return selected
    with _client_lock:
        if key not in _warned_threshold_models:
            _LOG.warning(
                "No tuned embedding thresholds for %s model %s; using %s defaults",
                configured.provider,
                configured.model,
                _DEFAULT_MODELS[configured.provider],
            )
            _warned_threshold_models.add(key)
    return _THRESHOLDS[(configured.provider, _DEFAULT_MODELS[configured.provider])]


def _get_client() -> ollama.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = ollama.Client(
                host=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
                timeout=settings().timeout_s,
            )
        return _client


def _http_client() -> httpx.Client:
    global _openai_client
    with _client_lock:
        if _openai_client is None:
            _openai_client = httpx.Client()
        return _openai_client


def reset() -> None:
    """Clear cached configuration, clients, and query embeddings."""
    global _client, _openai_client
    with _client_lock:
        if _client is not None:
            cast(_Closable, _client).close()
        if _openai_client is not None:
            _openai_client.close()
        _client = None
        _openai_client = None
        _warned_threshold_models.clear()
    settings.cache_clear()
    _cached_embed.cache_clear()


def _retry_delay(attempt: int, retry_after: str | None = None) -> None:
    delay = min(0.5 * 2**attempt, 4.0)
    if retry_after is not None:
        try:
            delay = max(delay, min(float(retry_after), MAX_RETRY_AFTER_S))
        except ValueError:
            pass
    _sleep(delay)


def _validate_vector(values: Sequence[float], model: str) -> list[float]:
    result = list(values)
    if len(result) != vector.DIM:
        raise EmbeddingError(
            f"Embedding model {model} returned {len(result)} dimensions; "
            f"expected {vector.DIM}"
        )
    return result


def _ollama_embed(text: str, configured: Settings) -> list[float]:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = _get_client().embeddings(
                model=configured.model,
                prompt=text,
            )
            return _validate_vector(response.embedding, configured.model)
        except ollama.ResponseError as exc:
            transient = exc.status_code in (408, 409, 429) or exc.status_code >= 500
            if not transient or attempt == MAX_RETRIES:
                raise EmbeddingError(
                    f"Ollama embedding request failed for {configured.model}"
                ) from exc
        except (ConnectionError, httpx.RequestError) as exc:
            if attempt == MAX_RETRIES:
                raise EmbeddingError(
                    f"Ollama embedding request failed for {configured.model}"
                ) from exc
        except (TypeError, ValueError, ValidationError) as exc:
            raise EmbeddingError(
                f"Ollama returned a malformed response for {configured.model}"
            ) from exc
        _retry_delay(attempt)
    raise EmbeddingError(f"Ollama embedding request failed for {configured.model}")


def _openai_batch(texts: list[str], configured: Settings) -> list[list[float]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise EmbeddingError("OPENAI_API_KEY is required for OpenAI embeddings")
    config = ModelConfig(
        provider="openai",
        model=configured.model,
        max_tokens=1,
        request_timeout_s=configured.timeout_s,
    )
    try:
        with usage.attributed("embedding"), usage.metered(config) as report:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = _http_client().post(
                        "https://api.openai.com/v1/embeddings",
                        json={
                            "model": configured.model,
                            "input": texts,
                            "dimensions": vector.DIM,
                            "encoding_format": "float",
                        },
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=configured.timeout_s,
                    )
                except httpx.RequestError as exc:
                    if attempt == MAX_RETRIES:
                        raise EmbeddingError(
                            f"OpenAI embedding request failed for {configured.model}"
                        ) from exc
                else:
                    transient = response.status_code in (408, 409, 429) or (
                        response.status_code >= 500
                    )
                    if response.is_error:
                        if transient and attempt < MAX_RETRIES:
                            _retry_delay(attempt, response.headers.get("retry-after"))
                            continue
                        raise EmbeddingError(
                            "OpenAI embedding request failed "
                            f"(HTTP {response.status_code})"
                        )
                    try:
                        parsed = _OpenAIResponse.model_validate_json(response.content)
                    except ValidationError as exc:
                        raise EmbeddingError(
                            f"OpenAI returned a malformed response for {configured.model}"
                        ) from exc
                    ordered = sorted(parsed.data, key=lambda item: item.index)
                    if [item.index for item in ordered] != list(range(len(texts))):
                        raise EmbeddingError(
                            f"OpenAI returned a malformed response for {configured.model}"
                        )
                    vectors = [
                        _validate_vector(item.embedding, configured.model)
                        for item in ordered
                    ]
                    report(Usage(input_tokens=parsed.usage.prompt_tokens))
                    return vectors
                _retry_delay(attempt)
    except usage.Paused as exc:
        raise EmbeddingError(f"OpenAI embeddings are paused: {exc}") from exc
    raise EmbeddingError(f"OpenAI embedding request failed for {configured.model}")


def embed_many(texts: Sequence[str]) -> list[list[float]]:
    """Embed texts in input order, batching requests where the provider allows."""
    if not texts:
        return []
    configured = settings()
    items = list(texts)
    if configured.provider == "ollama":
        return [_ollama_embed(text, configured) for text in items]
    vectors: list[list[float]] = []
    for start in range(0, len(items), OPENAI_BATCH):
        vectors.extend(_openai_batch(items[start : start + OPENAI_BATCH], configured))
    return vectors


def _embed_one(text: str) -> list[float]:
    configured = settings()
    if configured.provider == "ollama":
        return _ollama_embed(text, configured)
    return _openai_batch([text], configured)[0]


@lru_cache(maxsize=QUERY_CACHE_SIZE)
def _cached_embed(embedder_identity: str, text: str) -> tuple[float, ...]:
    del embedder_identity
    return tuple(_embed_one(text))


def embed(text: str) -> list[float]:
    """Return one embedding, caching successful query vectors."""
    return list(_cached_embed(identity(), text))
