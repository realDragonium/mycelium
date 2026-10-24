import json
from pathlib import Path

import pytest

from mycelium import agentloop


def test_trace_log_rotates_one_generation_at_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "logs" / "ask_trace.jsonl"
    record = {"question": "Can I export invoices in €?"}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    monkeypatch.setenv("MYCELIUM_TRACE_LOG_MAX_BYTES", str(len(line.encode()) * 2))

    agentloop.write_record(path, record)
    agentloop.write_record(path, record)
    assert path.read_text() == line * 2
    rotated = path.with_name(path.name + ".1")
    assert not rotated.exists()

    agentloop.write_record(path, {"question": "How do I configure SSO?"})
    assert rotated.read_text() == line * 2
    assert json.loads(path.read_text()) == {"question": "How do I configure SSO?"}

    monkeypatch.setenv("MYCELIUM_TRACE_LOG_MAX_BYTES", "1")
    agentloop.write_record(path, {"question": "How do I sign in?"})
    assert json.loads(rotated.read_text()) == {"question": "How do I configure SSO?"}
    assert json.loads(path.read_text()) == {"question": "How do I sign in?"}
    assert not path.with_name(path.name + ".2").exists()


@pytest.mark.parametrize("limit", ["0", "invalid", "-1"])
def test_trace_log_disabled_or_invalid_limit_still_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_LOG_MAX_BYTES", limit)
    path = tmp_path / "ingest_trace.jsonl"
    for i in range(3):
        agentloop.write_record(path, {"run": i})
    assert [json.loads(line) for line in path.read_text().splitlines()] == [
        {"run": i} for i in range(3)
    ]
    assert not path.with_name(path.name + ".1").exists()


def test_trace_log_failure_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYCELIUM_TRACE_LOG_MAX_BYTES", "1")
    path = tmp_path / "docgen_trace.jsonl"
    path.write_text('{"run": 1}\n')

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("rotation unavailable")

    monkeypatch.setattr(Path, "replace", fail_replace)
    agentloop.write_record(path, {"run": 2})
