"""Starting in the background: what the server answers before it is ready,
and the copy-of-production quarantine."""

from __future__ import annotations

import logging
import sys

import pytest
from fastapi.testclient import TestClient

from mycelium import draft_review_runs, quarantine, request_timing, tracing
from mycelium.docgen import destinations
from mycelium.http import create_app, main
from mycelium.server import startup
from settings_helpers import set_review_controls
from test_reviewed_application import _app


@pytest.fixture
def starting(monkeypatch):
    monkeypatch.setattr(startup, "_startup", None)
    startup.mark_starting()
    startup._report("migrating", "substrate migration v21 (audience labels): starting")
    return TestClient(create_app())


def test_while_starting_only_the_startup_state_answers(starting):
    info = starting.get("/api/server-info")
    assert info.status_code == 200
    assert info.json()["state"] == "migrating"
    assert "v21 (audience labels)" in info.json()["detail"]

    api = starting.get("/api/me")
    assert api.status_code == 503
    assert api.headers["retry-after"] == "5"
    assert "starting up" in api.json()["detail"]

    page = starting.get("/ui/", headers={"accept": "text/html"})
    assert page.status_code == 503
    assert 'http-equiv="refresh"' in page.text


def test_answers_while_starting_are_not_logged_as_slow_requests(
    starting, monkeypatch, caplog
):
    monkeypatch.setenv("MYCELIUM_SLOW_REQUEST_MS", "0")
    performance_logger = logging.getLogger("mycelium.performance")
    performance_logger.addHandler(caplog.handler)
    try:
        response = starting.get("/api/server-info")
        assert response.json()["state"] == "migrating"
        assert not any(
            request_timing.SLOW_TOKEN in record.getMessage()
            for record in caplog.records
        )

        startup._report("ready")
        response = starting.get("/api/server-info")
        assert response.status_code == 200
        assert any(
            request_timing.SLOW_TOKEN in record.getMessage()
            and "route=GET_/api/server-info" in record.getMessage()
            for record in caplog.records
        )
    finally:
        performance_logger.removeHandler(caplog.handler)


def test_a_failed_start_says_why(starting):
    startup._report("failed", "database schema version 99 is newer")
    response = starting.get("/api/server-info")
    assert response.status_code == 503
    info = response.json()
    assert info["state"] == "failed"
    assert "schema version 99" in info["detail"]


def test_a_contradictory_domain_policy_refuses_to_start_before_listening(
    monkeypatch, caplog
):
    monkeypatch.setattr(startup, "_startup", None)
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.setenv("MYCELIUM_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("MYCELIUM_ALLOWED_EMAIL_DOMAINS", "example.com")
    monkeypatch.setenv("MYCELIUM_JIT_DOMAINS", "example.org")
    failed: list[bool] = []
    app = create_app(on_startup_failure=lambda: failed.append(True))

    with caplog.at_level(logging.ERROR, logger="mycelium.errors"):
        with pytest.raises(RuntimeError, match="MYCELIUM_JIT_DOMAINS"):
            with TestClient(app):
                pass
    assert startup.status() is None
    assert failed == []
    assert any(
        record.name == "mycelium.errors"
        and record.getMessage().startswith(tracing.ERROR_TOKEN)
        and "where=startup" in record.getMessage()
        and record.exc_info is not None
        for record in caplog.records
    )


def test_a_start_refused_by_configuration_is_logged_as_an_error(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("MYCELIUM_AUTH", "on")
    monkeypatch.delenv("MYCELIUM_SESSION_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["mycelium-http"])
    monkeypatch.setattr(tracing, "configure_logging", lambda: None)

    with caplog.at_level(logging.ERROR, logger="mycelium.errors"):
        with pytest.raises(SystemExit) as raised:
            main()

    assert raised.value.code == 1
    assert any(
        record.name == "mycelium.errors"
        and record.getMessage().startswith(tracing.ERROR_TOKEN)
        and "where=startup" in record.getMessage()
        and "MYCELIUM_SESSION_SECRET" in record.getMessage()
        and record.exc_info is not None
        for record in caplog.records
    )


def test_startup_reports_ready_after_init(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "_startup", None)
    startup.mark_starting()
    with _app(tmp_path, monkeypatch) as client:
        assert startup.status().state == "ready"
        info = client.get("/api/server-info")
        assert info.status_code == 200
        assert (info.json()["state"], info.json()["quarantine"]) == ("ready", False)


def test_quarantine_turns_review_and_delivery_off_without_saving(tmp_path, monkeypatch):
    monkeypatch.setenv(quarantine.ENV, "1")
    with _app(tmp_path, monkeypatch) as client:
        set_review_controls(mode="review-only")
        assert draft_review_runs.mode() == "off"
        assert client.get("/api/draft-review/settings").json()["mode"] == "review-only"
        assert client.get("/api/server-info").json()["quarantine"] is True
        config = destinations.DestinationConfig("docs", "github", "docs/{slug}.md", {})
        with pytest.raises(destinations.DestinationError, match="quarantine"):
            destinations.deliver_document(config, None)
