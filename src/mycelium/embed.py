"""Ollama embedding client."""

from __future__ import annotations

import os

from ollama import Client

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768
# The ollama client defaults to NO timeout, and every embed occupies a worker
# thread for its whole duration. An unresponsive sidecar would therefore park
# threads permanently, exhausting the pool with no way back — a wedge the health
# check can't see, because the health check deliberately needs no thread. Bound
# it: embedding one short text is sub-second, so anything near this ceiling is a
# failure, and failing is recoverable in a way that hanging is not.
EMBED_TIMEOUT_S = float(os.environ.get("EMBED_TIMEOUT_S") or 30.0)

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(host=OLLAMA_URL, timeout=EMBED_TIMEOUT_S)
    return _client


def embed(text: str) -> list[float]:
    """Return a 768-dim embedding for `text`."""
    response = _get_client().embeddings(model=EMBED_MODEL, prompt=text)
    return list(response["embedding"])
