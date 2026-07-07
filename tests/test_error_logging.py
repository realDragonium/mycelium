"""The top-level error capture: an uncaught exception must produce one
structured, greppable line (so a CloudWatch metric filter can count it) and an
opaque 500, while deliberate ValueErrors keep their 400 and don't pollute the
error stream.

The handlers are exercised on a throwaway FastAPI app wired with the *real*
handler functions from `http`, so the test needs no server lifespan or DB."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mycelium import http, tracing


def _app_with_handlers() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(ValueError, http._value_error_handler)
    app.add_exception_handler(Exception, http._unhandled_error_handler)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/bad")
    def bad():
        raise ValueError("nope")

    return app


def test_unhandled_error_returns_500_and_logs_token(caplog):
    client = TestClient(_app_with_handlers(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="mycelium.errors"):
        r = client.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}

    line = "\n".join(rec.getMessage() for rec in caplog.records)
    assert tracing.ERROR_TOKEN in line
    assert "exc=RuntimeError" in line
    assert "where=http" in line
    assert "path=/boom" in line
    assert "method=GET" in line
    # The traceback is attached for triage, not just the message.
    assert any(rec.exc_info for rec in caplog.records)


def test_value_error_keeps_400_and_is_not_logged_as_error(caplog):
    client = TestClient(_app_with_handlers(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="mycelium.errors"):
        r = client.get("/bad")
    assert r.status_code == 400
    assert r.json() == {"detail": "nope"}
    assert tracing.ERROR_TOKEN not in "\n".join(rec.getMessage() for rec in caplog.records)


def test_emit_error_is_structured_and_never_raises(caplog):
    with caplog.at_level(logging.ERROR, logger="mycelium.errors"):
        try:
            raise KeyError("missing")
        except KeyError as exc:
            tracing.emit_error(where="unit", exc=exc, path="/x", method="GET")
    assert any(
        tracing.ERROR_TOKEN in m and "exc=KeyError" in m and "where=unit" in m
        for m in (rec.getMessage() for rec in caplog.records)
    )
