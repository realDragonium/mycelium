"""Ollama embedding client."""

from __future__ import annotations

import os

from ollama import Client

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(host=OLLAMA_URL)
    return _client


def embed(text: str) -> list[float]:
    """Return a 768-dim embedding for `text`."""
    response = _get_client().embeddings(model=EMBED_MODEL, prompt=text)
    return list(response["embedding"])
