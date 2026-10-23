import inspect
import threading
import time

import httpx
import ollama
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from mycelium import auth, auth_store, embed, request_timing, store
from mycelium.request_timing import Phase, Recorder, Sample, Spread, TimedLock
from mycelium.server import runtime


def _sample(
    label: str,
    total: float,
    at: float = 100.0,
    phases: dict[Phase, float] | None = None,
) -> Sample:
    return Sample(label=label, at=at, total=total, phases=phases or {}, failed=False)


def test_summary_reports_nearest_rank_spread_per_route_slowest_first():
    recorder = Recorder(window_s=60, max_samples=100)
    for ms in range(1, 21):
        recorder.add(_sample("GET /slow", ms / 1000))
    recorder.add(_sample("GET /fast", 0.001, phases={"embed": 0.0005}))
    recorder.add(_sample("GET /fast", 0.002))
    recorder.add(_sample("GET /gone", 9.0, at=10.0))

    slow, fast = recorder.summary(now=120.0)

    assert slow.label == "GET /slow"
    assert slow.total == Spread(p50_ms=10.0, p95_ms=19.0, max_ms=20.0)
    assert fast.count == 2
    assert fast.phases == {"embed": Spread(p50_ms=0.5, p95_ms=0.5, max_ms=0.5)}


def test_lock_charges_a_contended_wait_and_only_the_outermost_hold():
    lock = TimedLock()
    held = threading.Event()
    release = threading.Event()

    def holder():
        with lock.held():
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)
    threading.Timer(0.05, release.set).start()
    with request_timing.track("test") as timing:
        with lock.held():
            with lock.held():
                pass
    thread.join()

    assert timing.phases["lock_wait"] >= 0.04
    assert timing.phases["lock_held"] < 0.04


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_a_provider_embedding_is_timed_and_a_cached_one_is_not(provider, monkeypatch):
    monkeypatch.setenv("MYCELIUM_EMBED_PROVIDER", provider)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("MYCELIUM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    embed.reset()

    class Ollama:
        def embeddings(self, *, model: str, prompt: str) -> ollama.EmbeddingsResponse:
            time.sleep(0.02)
            return ollama.EmbeddingsResponse(embedding=[1.0] * 768)

    def openai(request: httpx.Request) -> httpx.Response:
        time.sleep(0.02)
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [1.0] * 768}],
                "usage": {"prompt_tokens": 1},
            },
        )

    monkeypatch.setattr(embed, "_get_client", Ollama)
    monkeypatch.setattr(
        embed, "_openai_client", httpx.Client(transport=httpx.MockTransport(openai))
    )
    try:
        with request_timing.track("first") as first:
            embed.embed("workspace invites")
        with request_timing.track("again") as again:
            embed.embed("workspace invites")
    finally:
        embed.reset()

    assert first.phases["embed"] >= 0.02
    assert "embed" not in again.phases


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    store.reset_substrate()
    auth_store.reset()
    runtime._ctx = None
    from mycelium.http import create_app

    with TestClient(create_app()) as c:
        yield c


def _bearer(role: str) -> dict[str, str]:
    conn = runtime._auth_db()
    with store.transaction(conn):
        user = auth.create_user(conn, name=role, role=role, type="service")
        raw, _ = auth.issue_token(conn, user_id=user, name="t", scope=role)
    return {"Authorization": f"Bearer {raw}"}


def test_performance_summary_is_admin_only_and_names_routes_by_template(client):
    reader, admin = _bearer("reader"), _bearer("admin")
    client.get("/api/statements/st_missing/audiences", headers=admin)

    assert client.get("/api/admin/performance", headers=reader).status_code == 403
    summary = client.get("/api/admin/performance", headers=admin).json()
    route = next(
        r
        for r in summary["routes"]
        if r["label"] == "GET /api/statements/{statement_id}/audiences"
    )
    assert "thread_run" in route["phases"]


def test_every_route_times_its_wait_for_a_worker_thread():
    from mycelium.http import create_app

    plain = [
        route.path
        for route in create_app().routes
        if isinstance(route, APIRoute)
        and not inspect.iscoroutinefunction(route.endpoint)
    ]
    assert plain == [], "build these routers with route_class=TimedRoute"
