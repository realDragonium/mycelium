"""Test-wide setup.

A test that serves HTTP builds its own app with `mycelium.http.create_app()`,
under the environment it set up, and runs at most one lifespan on it.
"""

import os

import pytest

from mycelium import embed as embed_module

_real_embed_many = embed_module.embed_many


@pytest.fixture(autouse=True)
def _route_batched_embeddings_through_embed(monkeypatch):
    """Keep rebuilds driven by each test's runtime monkeypatch of embed.embed."""

    def embed_many(texts):
        return [embed_module.embed(text) for text in texts]

    embed_module.reset()
    monkeypatch.setattr(embed_module, "embed_many", embed_many)
    yield
    embed_module.reset()


@pytest.fixture(autouse=True)
def _isolate_prompt_store():
    """Start every test with no prompt store or AI usage recorder wired up.

    The store is a process-global provider and the ingest/docgen doctrines
    read it at run start, so a `server.init()` in one test would otherwise
    decide what the next test's loop reads. Tests that want a store pin one
    (`prompt_store.use_connection`) or build a server.
    """
    from mycelium import ai_usage, prompt_store

    prompt_store.reset()
    ai_usage.uninstall()
    yield
    prompt_store.reset()
    ai_usage.uninstall()


# Credentials a model provider SDK would pick up. Removed for the whole run so a
# test that forgets its stub fails instead of making a paid call; a test that
# needs a key sets a fake one itself.
_PROVIDER_CREDENTIALS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
)


def pytest_configure(config):
    _require_spacy_model()
    for name in _PROVIDER_CREDENTIALS:
        os.environ.pop(name, None)
    # A test that starts the app without its own data dir would otherwise
    # share ./.mycelium (or an exported instance) with every other test,
    # worker and local server. Unusable on purpose: it fails at mkdir.
    os.environ["MYCELIUM_DATA_DIR"] = os.path.join(os.devnull, "mycelium")
    # TestClient's default host; the server refuses hosts it was not told of.
    os.environ.setdefault("MYCELIUM_ALLOWED_HOSTS", "testserver")
    # The async mention-recompute worker spawns a daemon thread per
    # server.init(); across many TestClient lifecycles that races the
    # assertions and leaks threads. Tests that exercise recompute call
    # `mention_worker.drain(conn)` synchronously instead.
    os.environ.setdefault("MYCELIUM_DISABLE_MENTION_WORKER", "1")
    # The review sweep wakes on a timer; tests call `draft_review_runs.sweep`
    # with an explicit clock instead.
    os.environ.setdefault("MYCELIUM_DISABLE_REVIEW_SWEEP", "1")
    os.environ.setdefault("MYCELIUM_DISABLE_AUDIENCE_WORKER", "1")
    # The document maintenance sweep too; tests call
    # `document_maintenance.sweep` with an explicit clock.
    os.environ.setdefault("MYCELIUM_DISABLE_MAINTENANCE_WORKER", "1")
    # Each server.init() otherwise spawns a layout-bake subprocess, and every
    # entity write arms a timer that spawns another one mid-suite.
    os.environ.setdefault("MYCELIUM_DISABLE_LAYOUT_BAKE", "1")


def _require_spacy_model():
    """Abort the run with one actionable line when phrasing validation
    can't load its spaCy model. Exercises the real load path rather than
    module discovery, since a half-installed model imports fine and only
    fails at `spacy.load`; the load also warms the cache the suite
    reuses. Without this, ~190 otherwise unrelated tests fail and the
    baseline reads as broken rather than unbootstrapped."""
    from mycelium import phrasing

    try:
        phrasing.check("A user submits the form.")
    except Exception as exc:
        raise pytest.UsageError(f"phrasing validation is unusable: {exc}") from exc
