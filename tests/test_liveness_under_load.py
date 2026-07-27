"""The health probe must answer while every worker thread is busy.

Tool calls run in anyio's worker pool (see `server._offloaded`). That pool is
bounded, so anything that also needs a thread queues behind the tools once they
fill it — and when the queued request is a deployment's health check, a merely
busy server is taken out of rotation and every caller gets a 503. Two things
keep the probe out of that queue: the endpoint is async, and an anonymous
request resolves its (absent) credentials without touching the auth DB.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time

import anyio
import anyio.to_thread
import httpx
import pytest

from mycelium import auth
from mycelium.http import AuthMiddleware, app, get_server_info


def test_health_endpoint_is_async_so_it_never_needs_a_worker_thread():
    assert inspect.iscoroutinefunction(get_server_info)


def test_health_route_is_registered_as_the_async_endpoint():
    route = next(
        r for r in app.routes if getattr(r, "path", None) == "/api/server-info"
    )

    assert inspect.iscoroutinefunction(route.endpoint)


def test_anonymous_request_resolves_without_touching_the_auth_db(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("anonymous request must not hit the auth DB")

    monkeypatch.setattr(AuthMiddleware, "_lookup", staticmethod(explode))

    assert asyncio.run(AuthMiddleware._resolve(None, None)) is None
    assert asyncio.run(AuthMiddleware._resolve(None, "")) is None


def test_credentialed_request_is_looked_up_off_the_event_loop(monkeypatch):
    calling_thread = {}

    def record(raw, user_id):
        calling_thread["ident"] = threading.get_ident()
        return auth.Principal(id=raw, name="t", role="reader", type="service")

    monkeypatch.setattr(AuthMiddleware, "_lookup", staticmethod(record))

    async def scenario():
        principal = await AuthMiddleware._resolve("myc_tok", None)
        return principal, threading.get_ident()

    principal, loop_thread = asyncio.run(scenario())

    assert principal.id == "myc_tok"
    assert calling_thread["ident"] != loop_thread


@pytest.mark.parametrize(
    "headers,session,expected",
    [
        ({}, {}, (None, None)),
        ({"authorization": "Bearer myc_abc"}, {}, ("myc_abc", None)),
        ({}, {"user_id": "usr_1"}, (None, "usr_1")),
        ({"authorization": "Basic nope"}, {"user_id": "usr_1"}, (None, "usr_1")),
    ],
)
def test_credentials_extraction_is_pure(headers, session, expected):
    class FakeRequest:
        def __init__(self):
            self.headers = headers
            self.session = session

    assert AuthMiddleware._credentials(FakeRequest()) == expected


def test_embed_client_bounds_its_calls(monkeypatch):
    """An embed with no timeout parks its worker thread forever if the sidecar
    stops answering, and enough of those exhaust the pool permanently — the one
    wedge an intentionally thread-free health check cannot detect."""
    monkeypatch.setenv("EMBED_TIMEOUT_S", "7")
    import importlib

    from mycelium import embed

    reloaded = importlib.reload(embed)
    try:
        assert reloaded._get_client()._client.timeout.read == 7.0
    finally:
        monkeypatch.delenv("EMBED_TIMEOUT_S")
        importlib.reload(embed)


def test_health_answers_while_the_worker_pool_is_saturated(tmp_path, monkeypatch):
    """The regression that matters: hold every thread in the pool, then probe.
    Before the endpoint was async this timed out — which is exactly what a
    health check sees, and why a busy server got taken out of rotation."""
    monkeypatch.setenv("MYCELIUM_AUTH", "off")

    async def scenario():
        pool = anyio.to_thread.current_default_thread_limiter()
        occupied = threading.Event()
        release = threading.Event()
        holders = int(pool.total_tokens)

        def hold():
            occupied.set()
            release.wait(timeout=30)

        async with anyio.create_task_group() as tg:
            for _ in range(holders):
                tg.start_soon(anyio.to_thread.run_sync, hold)

            # Wait until the pool is genuinely full, not merely scheduled.
            while pool.available_tokens > 0:
                await asyncio.sleep(0.01)
            assert occupied.is_set()

            try:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://probe"
                ) as client:
                    started = time.monotonic()
                    response = await client.get("/api/server-info", timeout=10)
                    elapsed = time.monotonic() - started
            finally:
                # Without this, a probe that raises leaves the holders parked
                # until their own timeout — making the failing path, the one
                # worth iterating on, the slowest to report.
                release.set()

        return response.status_code, elapsed

    status, elapsed = asyncio.run(scenario())

    assert status == 200
    assert elapsed < 1.0
